"""
tdx 日线全量重播种 — 用 tdx 精确前复权数据覆盖 chan.db 内 Tushare QFQ 存量

背景(2026-11 校验结论): Tushare 增量更新在除权日不重算历史,库内 44/50 抽样股
存在除权拼接断裂(假跳空 → 假笔/假信号)。tdx QFQ 经腾讯行情锚点校验通过。

用法:
    python -m scripts.reseed_tdx --limit 10        # 试跑 10 只验证
    python -m scripts.reseed_tdx --codes 000001 600519
    python -m scripts.reseed_tdx --all             # 全量(约 1.5-2.5 小时,断点续跑)

行为:
- 每只股票: tdx 拉前复权日线 → 删除库内该股 DAY 行 → 写入新行
- 深度对齐: 只保留"不早于该股库内现有最早日期"的bar(CChan 计算负载不变)
- 断点续跑: 进度存 scripts/_reseed_progress.json,中断后重跑自动跳过已完成
- 注意: 运行期间避免启动全市场扫描(SQLite 写锁)
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows 控制台/重定向默认 GBK,强制 UTF-8 避免 ✓ 等字符崩溃
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ChanAnalyzer.database import get_db, KLineData
from ChanAnalyzer.tdx_source import TdxSource

PROGRESS_FILE = Path(__file__).parent / "_reseed_progress.json"


def load_progress() -> set:
    if PROGRESS_FILE.exists():
        try:
            return set(json.loads(PROGRESS_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_progress(done: set):
    PROGRESS_FILE.write_text(json.dumps(sorted(done)), encoding="utf-8")


def detect_date_format() -> str:
    """探测库内现有 date 格式,新数据沿用(避免格式不一致破坏引擎/前端解析)"""
    with get_db() as db:
        row = db.query(KLineData).filter(KLineData.kl_type == "DAY").first()
        if row is None:
            return "%Y/%m/%d %H:%M:%S"  # 空库默认
    return "%Y/%m/%d %H:%M:%S" if "/" in row.date[:5] else "%Y-%m-%d %H:%M:%S"


def reseed_one(src: TdxSource, code: str, date_fmt: str) -> tuple:
    """重播种单只股票。返回 (code, ok, rows, msg)"""
    # 库内该股现有最早日期(深度对齐用)与行数
    with get_db() as db:
        first = (
            db.query(KLineData)
            .filter(KLineData.code == code, KLineData.kl_type == "DAY")
            .order_by(KLineData.timestamp.asc())
            .first()
        )
        if first is None:
            return code, False, 0, "库内无此股,跳过"
        min_date = first.timestamp

    df = src.get_daily_qfq(code, pages=2)  # 1400根 ≈ 5.5年
    if df is None or len(df) == 0:
        return code, False, 0, "tdx 拉取失败"

    df = df[df["date"] >= min_date]  # 深度对齐:不早于现有最早日期
    if len(df) == 0:
        return code, False, 0, "tdx 数据均早于库内起点"

    rows = []
    for _, r in df.iterrows():
        dt = r["date"].to_pydatetime().replace(hour=15, minute=0, second=0)
        rows.append(KLineData(
            code=code, kl_type="DAY",
            date=dt.strftime(date_fmt),
            timestamp=dt,
            open=float(r["open"]), high=float(r["high"]),
            low=float(r["low"]), close=float(r["close"]),
            volume=float(r["volume"]) if r["volume"] else 0,
            amount=round(float(r["amount"]), 2) if r.get("amount") else None,
            turnover_rate=None,
        ))

    with get_db() as db:
        db.query(KLineData).filter(
            KLineData.code == code, KLineData.kl_type == "DAY"
        ).delete(synchronize_session=False)
        db.add_all(rows)
        db.commit()
    return code, True, len(rows), ""


def main():
    parser = argparse.ArgumentParser(description="tdx 日线全量重播种")
    parser.add_argument("--all", action="store_true", help="重播种库内全部股票")
    parser.add_argument("--codes", nargs="*", help="指定股票代码")
    parser.add_argument("--limit", type=int, help="限制数量(试跑)")
    args = parser.parse_args()

    with get_db() as db:
        codes = [
            r[0] for r in db.query(KLineData.code)
            .filter(KLineData.kl_type == "DAY").distinct().all()
        ]
    if args.codes:
        codes = [c.zfill(6) for c in args.codes]
    elif not args.all and not args.limit:
        print("未指定 --all 或 --codes。试跑请加 --limit 10,全量请加 --all")
        return
    if args.limit:
        codes = codes[:args.limit]

    done = load_progress()
    date_fmt = detect_date_format()
    print(f"目标 {len(codes)} 只,date 格式={date_fmt!r},已完成 {len(done & set(codes))} 只(断点跳过)")

    src = TdxSource()
    failed, t0 = [], time.time()
    try:
        for i, code in enumerate(codes):
            if code in done:
                continue
            try:
                _, ok, rows, msg = reseed_one(src, code, date_fmt)
            except Exception as e:
                ok, rows, msg = False, 0, f"{type(e).__name__}: {str(e)[:60]}"
            if ok:
                done.add(code)
                if len(done) % 50 == 0:
                    save_progress(done)
                    speed = len(done) / max(1, time.time() - t0) * 3600
                    print(f"[{len(done)}/{len(codes)}] {code} OK {rows}行 | 速率≈{speed:.0f}只/时")
            else:
                failed.append((code, msg))
                print(f"[FAIL] {code}: {msg}")
            time.sleep(0.15)  # 温和限速
    except KeyboardInterrupt:
        print("\n中断,进度已保存")
    finally:
        save_progress(done)
        src.close()

    print(f"\n完成 {len(done)}/{len(codes)},失败 {len(failed)}")
    if failed:
        (Path(__file__).parent / "_reseed_failed.json").write_text(
            json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8")
        print("失败清单 → scripts/_reseed_failed.json(可单独 --codes 重跑)")
    if len(done) == len(codes):
        PROGRESS_FILE.unlink(missing_ok=True)  # 全部完成清除断点文件
        print("全部完成,断点文件已清除")


if __name__ == "__main__":
    main()
