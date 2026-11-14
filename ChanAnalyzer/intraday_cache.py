"""
分钟线按需缓存 — TV 图表多周期接入的存储层

策略(不预存全市场):
    全市场预存 = 5000只 × 4周期 × 每只数千根 = 千万行,SQLite 扛不住也无意义。
    改为按需缓存: 用户在 TV 切到某只股票的分钟周期 → 后端首次从 tdx 拉取入缓存
    → 日更(scripts/update_data.py)只刷新已缓存的 (code, kl_type) 组合。

复权: 与日线同口径 — qfq_adjust 全量重算式(分钟时间在 qfq_adjust 内部归一化到
    日粒度,除权事件对齐天然覆盖),永不增量拼接。除权日 09:35 首根的 preclose
    取"昨日最后一根分钟线 close"即昨收,因子公式在分钟粒度下依然成立。

时间口径: 存 bar 开始时刻(tdx 返回结束时刻,tdx_source 已减去周期分钟),
    date 字段 "YYYY/MM/DD HH:MM:SS",timestamp 同步。

用法(web/tv.py 首次请求 / scripts/update_data.py 日更):
    from ChanAnalyzer.intraday_cache import ensure_intraday, upsert_intraday, cached_intraday_combos
"""
import threading
from typing import List, Optional, Tuple

from ChanAnalyzer.database import get_db, KLineData
from ChanAnalyzer.tdx_source import TdxSource

INTRADAY_KL_TYPES = ("5M", "15M", "30M", "60M")

DATE_FMT = "%Y/%m/%d %H:%M:%S"

# 并发防重: 同一 (code, kl_type) 拉取进行中时,后续请求直接返回(等下次轮询拿数据)
_ensure_lock = threading.Lock()
_inflight: set = set()


def upsert_intraday(src: TdxSource, code: str, kl_type: str) -> int:
    """
    拉取+复权+全量重算入库(删旧插新)。返回入库行数;失败返回 0。
    供日更循环复用(外部管理 TdxSource 连接)。
    """
    df = src.get_intraday_qfq(code, kl_type)
    if df is None or len(df) == 0:
        return 0

    rows = []
    for _, r in df.iterrows():
        dt = r["date"].to_pydatetime().replace(second=0, microsecond=0)
        rows.append(KLineData(
            code=code, kl_type=kl_type,
            date=dt.strftime(DATE_FMT),
            timestamp=dt,
            open=float(r["open"]), high=float(r["high"]),
            low=float(r["low"]), close=float(r["close"]),
            volume=float(r["volume"]) if r["volume"] else 0,
            amount=round(float(r["amount"]), 2) if r.get("amount") else None,
            turnover_rate=None,
        ))

    with get_db() as db:
        db.query(KLineData).filter(
            KLineData.code == code, KLineData.kl_type == kl_type
        ).delete(synchronize_session=False)
        db.add_all(rows)
        db.commit()
    return len(rows)


def ensure_intraday(code: str, kl_type: str) -> int:
    """
    按需缓存入口(库内已有数据则不重复拉取)。

    Returns:
        -1 = 已缓存,无需拉取
         0 = 拉取失败(或同组合正在拉取中,客户端下次轮询再取)
        >0 = 本次拉取入库行数
    """
    with get_db() as db:
        exists = (
            db.query(KLineData.id)
            .filter(KLineData.code == code, KLineData.kl_type == kl_type)
            .first()
        )
    if exists:
        return -1

    key = (code, kl_type)
    with _ensure_lock:
        if key in _inflight:
            return 0
        _inflight.add(key)
    try:
        src = TdxSource()
        try:
            return upsert_intraday(src, code, kl_type)
        finally:
            src.close()
    except Exception:
        return 0
    finally:
        with _ensure_lock:
            _inflight.discard(key)


def cached_intraday_combos() -> List[Tuple[str, str]]:
    """库内已缓存的分钟 (code, kl_type) 组合,供日更增量刷新"""
    with get_db() as db:
        return (
            db.query(KLineData.code, KLineData.kl_type)
            .filter(KLineData.kl_type.in_(INTRADAY_KL_TYPES))
            .distinct()
            .all()
        )
