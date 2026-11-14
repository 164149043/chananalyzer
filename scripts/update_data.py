"""
K线数据日更脚本(tdx版) — 每日收盘后更新本地 K 线缓存

用法:
    python -m scripts.update_data --codes 000001 000002   # 更新指定股票
    python -m scripts.update_data --all                    # 更新库内全部股票(约40分钟)
    python -m scripts.update_data --all --skip-week        # 只更日线

行为(2026-11 从 Tushare 增量模式切换为 tdx 全量重算式):
- DAY : tdx 拉前复权日线(含自愈复权) → 删旧插新(全量重算)。
        QFQ 复权是全量重算式——当日有除权事件时全历史因子变化,增量拼接会产生
        拼接断裂(Tushare 时代 44/50 抽样股假跳空的根因),故每日全量重算,永不拼接。
- WEEK: 从复权后的 DAY 按周聚合合成(首开/末收/最高/最低/量额求和),
        复权一致性由 DAY 保证,不独立拉取(tdx 周线的除权事件对齐有坑)。
- 新股票(库内无 DAY 数据)全量插入,不做深度对齐截断。
- 断点续跑: 进度存 scripts/_update_progress.json。
- 运行时机: 交易日 15:10 之后(tdx 收盘后日线完整);盘中运行会拿到当日实时未收盘K线。

注意: 旧 Tushare 版已废弃,不要再用旧逻辑向库内写 K线(会污染 tdx 复权数据)。
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows 控制台/重定向默认 GBK,强制 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ChanAnalyzer.database import get_db, KLineData
from ChanAnalyzer.tdx_source import TdxSource

PROGRESS_FILE = Path(__file__).parent / "_update_progress.json"

DATE_FMT_DAY = "%Y/%m/%d %H:%M:%S"    # DAY 行 date 格式(与重播种一致,15:00 时间戳)
DATE_FMT_WEEK = "%Y/%m/%d"            # WEEK 行 date 格式(与库内历史 WEEK 一致)


def load_progress() -> set:
    if PROGRESS_FILE.exists():
        try:
            return set(json.loads(PROGRESS_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_progress(done: set):
    PROGRESS_FILE.write_text(json.dumps(sorted(done)), encoding="utf-8")


def build_week_from_day(day_df):
    """从复权日线合成周线:ISO周聚合,date=该周最后交易日"""
    df = day_df.reset_index(drop=True)
    rows = []
    for _key, g in _group_weeks(df):
        last = g.iloc[-1]
        dt = last["date"]
        rows.append({
            "date_str": dt.strftime(DATE_FMT_WEEK),
            "timestamp": dt.replace(hour=0, minute=0, second=0, microsecond=0),
            "open": float(g.iloc[0]["open"]),
            "close": float(last["close"]),
            "high": float(g["high"].max()),
            "low": float(g["low"].min()),
            "volume": float(g["volume"].sum()),
            "amount": round(float(g["amount"].sum()), 2) if "amount" in g else None,
        })
    return rows


def _group_weeks(df):
    """按 (ISO年, ISO周) 分组迭代器"""
    iso = df["date"].dt.isocalendar()
    keys = list(zip(iso["year"].astype(int), iso["week"].astype(int)))
    groups = {}
    order = []
    for i, k in enumerate(keys):
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(i)
    for k in order:
        yield k, df.iloc[groups[k]]


def update_one(src: TdxSource, code: str, with_week: bool = True) -> tuple:
    """更新单只股票。返回 (code, ok, day_rows, week_rows, msg)"""
    with get_db() as db:
        first = (
            db.query(KLineData)
            .filter(KLineData.code == code, KLineData.kl_type == "DAY")
            .order_by(KLineData.timestamp.asc())
            .first()
        )
    min_date = first.timestamp if first else None  # None=新股票,全量插入

    qfq = src.get_daily_qfq(code, pages=3)  # 2100根 ≈ 8.5年,覆盖库内深度并留余量
    if qfq is None or len(qfq) == 0:
        return code, False, 0, 0, "tdx 拉取失败"
    if min_date is not None:
        qfq = qfq[qfq["date"] >= pd_ts(min_date)]  # 深度对齐,计算负载不变
        if len(qfq) == 0:
            return code, False, 0, 0, "tdx 数据均早于库内起点"

    day_rows = []
    for _, r in qfq.iterrows():
        dt = r["date"].to_pydatetime().replace(hour=15, minute=0, second=0, microsecond=0)
        day_rows.append(KLineData(
            code=code, kl_type="DAY",
            date=dt.strftime(DATE_FMT_DAY),
            timestamp=dt,
            open=float(r["open"]), high=float(r["high"]),
            low=float(r["low"]), close=float(r["close"]),
            volume=float(r["volume"]) if r["volume"] else 0,
            amount=round(float(r["amount"]), 2) if r.get("amount") else None,
            turnover_rate=None,
        ))

    week_rows = []
    if with_week:
        for w in build_week_from_day(qfq):
            week_rows.append(KLineData(
                code=code, kl_type="WEEK",
                date=w["date_str"], timestamp=w["timestamp"],
                open=w["open"], high=w["high"], low=w["low"], close=w["close"],
                volume=w["volume"], amount=w["amount"], turnover_rate=None,
            ))

    with get_db() as db:
        db.query(KLineData).filter(
            KLineData.code == code, KLineData.kl_type == "DAY"
        ).delete(synchronize_session=False)
        if with_week:
            db.query(KLineData).filter(
                KLineData.code == code, KLineData.kl_type == "WEEK"
            ).delete(synchronize_session=False)
        db.add_all(day_rows)
        db.add_all(week_rows)
        db.commit()
    return code, True, len(day_rows), len(week_rows), ""


def pd_ts(dt):
    """datetime → pandas Timestamp(lazy import 避免顶层依赖)"""
    import pandas as pd
    return pd.Timestamp(dt)


def main():
    parser = argparse.ArgumentParser(description="K线日更(tdx全量重算式)")
    parser.add_argument("--all", action="store_true", help="更新库内全部股票")
    parser.add_argument("--codes", nargs="*", help="指定股票代码(可新增股票)")
    parser.add_argument("--limit", type=int, help="限制数量(试跑)")
    parser.add_argument("--skip-week", action="store_true", help="跳过周线合成")
    args = parser.parse_args()

    if args.codes:
        codes = [c.zfill(6) for c in args.codes]
    else:
        with get_db() as db:
            codes = [
                r[0] for r in db.query(KLineData.code)
                .filter(KLineData.kl_type == "DAY").distinct().all()
            ]
        if not args.all and not args.limit:
            print("未指定 --all 或 --codes。试跑加 --limit 10,全量加 --all")
            return
        if args.limit:
            codes = codes[:args.limit]

    done = load_progress()
    print(f"目标 {len(codes)} 只,已完成 {len(done & set(codes))} 只(断点跳过),周线{'跳过' if args.skip_week else '合成'}")

    src = TdxSource()
    failed, t0 = [], time.time()
    try:
        for code in codes:
            if code in done:
                continue
            try:
                _, ok, nd, nw, msg = update_one(src, code, with_week=not args.skip_week)
            except Exception as e:
                ok, nd, nw, msg = False, 0, 0, f"{type(e).__name__}: {str(e)[:60]}"
            if ok:
                done.add(code)
                if len(done) % 100 == 0:
                    save_progress(done)
                    speed = len(done) / max(1, time.time() - t0) * 3600
                    print(f"[{len(done)}/{len(codes)}] {code} OK DAY{nd} WEEK{nw} | 速率≈{speed:.0f}只/时")
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
        (Path(__file__).parent / "_update_failed.json").write_text(
            json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8")
        print("失败清单 → scripts/_update_failed.json")
    if len(done) == len(codes):
        PROGRESS_FILE.unlink(missing_ok=True)
        print("全部完成,断点文件已清除")


if __name__ == "__main__":
    main()
