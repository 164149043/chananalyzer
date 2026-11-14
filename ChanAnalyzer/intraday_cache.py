"""
分钟线按需缓存 — TV 图表多周期接入的存储层

策略(不预存全市场):
    全市场预存 = 5000只 × 4周期 × 每只数千根 = 千万行,SQLite 扛不住也无意义。
    改为按需缓存: 用户在 TV 切到某只股票的分钟周期 → 后端首次从 tdx 拉取入缓存
    → 日更(scripts/update_data.py)只刷新已缓存的 (code, kl_type) 组合。

盘中兜底刷新(ensure_intraday_fresh):
    请求触发式,无定时任务。库内最后K线落后"期望时间"超过阈值(取周期与10分钟的
    较大值)时,增量拉最新一页(700根)合并。合并前做复权口径校验——重叠时间戳的
    收盘价不一致说明窗口外发生了除权(全历史因子已变),此时回退全量重算,
    不违背"QFQ 永不增量拼接"的原则。冷却时间=阈值,防止对 tdx 高频拉取。

复权: 与日线同口径 — qfq_adjust 全量重算式(分钟时间在 qfq_adjust 内部归一化到
    日粒度,除权事件对齐天然覆盖),永不增量拼接。除权日 09:35 首根的 preclose
    取"昨日最后一根分钟线 close"即昨收,因子公式在分钟粒度下依然成立。

时间口径: 存 bar 开始时刻(tdx 返回结束时刻,tdx_source 已减去周期分钟),
    date 字段 "YYYY/MM/DD HH:MM:SS",timestamp 同步。

用法(web/tv.py 首次请求/盘中轮询, scripts/update_data.py 日更):
    from ChanAnalyzer.intraday_cache import (
        ensure_intraday, ensure_intraday_fresh, upsert_intraday, cached_intraday_combos)
"""
import threading
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from ChanAnalyzer.database import get_db, KLineData
from ChanAnalyzer.tdx_source import TdxSource, INTRADAY_PERIOD_MIN

INTRADAY_KL_TYPES = ("5M", "15M", "30M", "60M")

DATE_FMT = "%Y/%m/%d %H:%M:%S"

# 并发防重: 同一 (code, kl_type) 拉取进行中时,后续请求直接返回(等下次轮询拿数据)
_ensure_lock = threading.Lock()
_inflight: set = set()

# 盘中兜底刷新冷却: (code, kl_type) -> 上次刷新时间
_refresh_at: dict = {}


def _rows_from_df(code: str, kl_type: str, df) -> list:
    """复权后的 DataFrame -> KLineData 行列表(bar开始时刻,秒归零)"""
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
    return rows


def upsert_intraday(src: TdxSource, code: str, kl_type: str) -> int:
    """
    拉取+复权+全量重算入库(删旧插新)。返回入库行数;失败返回 0。
    供日更循环复用(外部管理 TdxSource 连接)。
    """
    df = src.get_intraday_qfq(code, kl_type)
    if df is None or len(df) == 0:
        return 0

    rows = _rows_from_df(code, kl_type, df)
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


# ==================== 盘中兜底刷新 ====================

def _expected_last_bar_dt() -> datetime:
    """
    期望的库内最后K线时间:
    - 交易日盘中(含午休) → 现在-5分钟(实时行情容忍度)
    - 交易日15:00后     → 今天 15:00
    - 交易日开盘前/周末 → 最近一个工作日 15:00
    节假日无法精确判断,误触发刷新无害(拉一页无新数据,进冷却)。
    """
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now.weekday() < 5:
        if now >= today.replace(hour=15, minute=0):
            return today.replace(hour=15, minute=0)
        if now > today.replace(hour=9, minute=30):
            return now - timedelta(minutes=5)
    d = today - timedelta(days=1)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d.replace(hour=15, minute=0)


def ensure_intraday_fresh(code: str, kl_type: str, last_ts: datetime) -> bool:
    """
    盘中/日更前兜底刷新(tv_history 每次请求调用,轻量判断,过期才真正拉取)。

    Args:
        last_ts: 库内该 (code, kl_type) 最后K线时间(调用方已查出)

    Returns:
        True = 本次执行了刷新(调用方需重读库); False = 无需/冷却中/进行中/失败
    """
    if kl_type not in INTRADAY_KL_TYPES:
        return False
    cooldown = timedelta(minutes=max(10, INTRADAY_PERIOD_MIN[kl_type]))
    now = datetime.now()
    key = (code, kl_type)
    if now - _refresh_at.get(key, datetime.min) < cooldown:
        return False
    # 数据足够新: 最后K线 + 冷却时长仍在期望时间内
    if last_ts + cooldown >= _expected_last_bar_dt():
        return False

    with _ensure_lock:
        if key in _inflight:
            return False
        _inflight.add(key)
        _refresh_at[key] = now  # 立即占冷却位,拉取期间的并发请求不再进
    try:
        src = TdxSource()
        try:
            return _refresh_tail(src, code, kl_type) > 0
        finally:
            src.close()
    except Exception:
        return False
    finally:
        with _ensure_lock:
            _inflight.discard(key)


def _refresh_tail(src: TdxSource, code: str, kl_type: str) -> int:
    """
    增量刷新: 拉最新一页(700根)复权后与库内合并。
    合并前校验复权口径——重叠时间戳收盘价相对差超0.1%说明窗口外有除权事件
    (全历史因子已变) → 回退全量重算,避免拼接断裂。
    """
    df = src.get_intraday_qfq(code, kl_type, pages=1)
    if df is None or len(df) == 0:
        return 0
    win_start = df["date"].iloc[0].to_pydatetime().replace(second=0, microsecond=0)

    with get_db() as db:
        # 复权口径校验(取窗口最早3根与库内同时间戳比对)
        ok = True
        for i in range(min(3, len(df))):
            ts = df["date"].iloc[i].to_pydatetime().replace(second=0, microsecond=0)
            old = (
                db.query(KLineData.close)
                .filter(KLineData.code == code, KLineData.kl_type == kl_type,
                        KLineData.timestamp == ts)
                .first()
            )
            if old and abs(old[0] - float(df["close"].iloc[i])) / max(abs(old[0]), 1e-9) > 0.001:
                ok = False
                break

    if not ok:
        return upsert_intraday(src, code, kl_type)  # 除权 → 全量重算

    rows = _rows_from_df(code, kl_type, df)
    with get_db() as db:
        db.query(KLineData).filter(
            KLineData.code == code, KLineData.kl_type == kl_type,
            KLineData.timestamp >= win_start,
        ).delete(synchronize_session=False)
        db.add_all(rows)
        db.commit()
    return len(rows)


# ==================== 日线/周线盘中兜底刷新 ====================

DAY_COOLDOWN = timedelta(minutes=30)


def ensure_day_fresh(code: str, last_ts: datetime) -> bool:
    """
    日线兜底刷新(tv_history 请求触发,机制同分钟版):
    - 盘中: 库内停在昨日 → 拉含当日实时未收盘K线(缠论会出现虚线笔,实时行情正常表现)
    - 收盘后~日更前: 收盘后30分钟冷却期过会再拉一次,补到最终收盘价
    刷新成功后顺带重合成尾部周线。
    """
    now = datetime.now()
    key = (code, "DAY")
    if now - _refresh_at.get(key, datetime.min) < DAY_COOLDOWN:
        return False
    if last_ts + DAY_COOLDOWN >= _expected_last_bar_dt():
        return False

    with _ensure_lock:
        if key in _inflight:
            return False
        _inflight.add(key)
        _refresh_at[key] = now
    try:
        src = TdxSource()
        try:
            return _refresh_day_tail(src, code) > 0
        finally:
            src.close()
    except Exception:
        return False
    finally:
        with _ensure_lock:
            _inflight.discard(key)


def _refresh_day_tail(src: TdxSource, code: str) -> int:
    """日线尾部增量: 拉前2页(≈1400根,覆盖库内深度),口径校验后尾部替换。
    日线行时间口径统一 15:00(与 update_data 日更一致,避免同日双行)。"""
    df = src.get_daily_qfq(code, pages=2)
    if df is None or len(df) == 0:
        return 0

    def _day_ts(dt_like) -> datetime:
        return dt_like.to_pydatetime().replace(hour=15, minute=0, second=0, microsecond=0)

    win_start = _day_ts(df["date"].iloc[0])

    with get_db() as db:
        ok = True
        for i in range(min(3, len(df))):
            old = (
                db.query(KLineData.close)
                .filter(KLineData.code == code, KLineData.kl_type == "DAY",
                        KLineData.timestamp == _day_ts(df["date"].iloc[i]))
                .first()
            )
            if old and abs(old[0] - float(df["close"].iloc[i])) / max(abs(old[0]), 1e-9) > 0.001:
                ok = False
                break

    rows = []
    for _, r in df.iterrows():
        dt = _day_ts(r["date"])
        rows.append(KLineData(
            code=code, kl_type="DAY",
            date=dt.strftime("%Y/%m/%d 15:00:00"),
            timestamp=dt,
            open=float(r["open"]), high=float(r["high"]),
            low=float(r["low"]), close=float(r["close"]),
            volume=float(r["volume"]) if r["volume"] else 0,
            amount=round(float(r["amount"]), 2) if r.get("amount") else None,
            turnover_rate=None,
        ))

    with get_db() as db:
        if not ok:
            # 除权 → 全历史因子已变,尾部替换会断裂;保守起见只保留已有数据,
            # 交给当晚日更全量重算(日线不像分钟有 upsert_intraday 全量入口)
            return 0
        db.query(KLineData).filter(
            KLineData.code == code, KLineData.kl_type == "DAY",
            KLineData.timestamp >= win_start,
        ).delete(synchronize_session=False)
        db.add_all(rows)
        db.commit()

    _rebuild_week_tail(code)
    return len(rows)


def _rebuild_week_tail(code: str):
    """从库内全量 DAY 重合成尾部周线(日线刷新后最后一根周bar随之变化)。
    周行口径与日更一致: date "YYYY/MM/DD",timestamp 00:00。"""
    with get_db() as db:
        days = (
            db.query(KLineData)
            .filter(KLineData.code == code, KLineData.kl_type == "DAY")
            .order_by(KLineData.timestamp.asc())
            .all()
        )
        if not days:
            return
        # 只需尾部几周,聚合全部但只写最后2个ISO周
        groups: list = []  # [(iso_key, [day_rows])]
        for d in days:
            iso = d.timestamp.isocalendar()
            k = (iso[0], iso[1])
            if not groups or groups[-1][0] != k:
                groups.append((k, []))
            groups[-1][1].append(d)
        tail = groups[-2:] if len(groups) >= 2 else groups[:]
        week_start_ts = tail[0][1][0].timestamp.replace(hour=0, minute=0, second=0, microsecond=0)

        week_rows = []
        for _k, g in tail:
            last = g[-1]
            week_rows.append(KLineData(
                code=code, kl_type="WEEK",
                date=last.timestamp.strftime("%Y/%m/%d"),
                timestamp=last.timestamp.replace(hour=0, minute=0, second=0, microsecond=0),
                open=g[0].open, high=max(x.high for x in g), low=min(x.low for x in g),
                close=last.close, volume=sum(x.volume or 0 for x in g),
                amount=sum(x.amount or 0 for x in g) or None, turnover_rate=None,
            ))
        db.query(KLineData).filter(
            KLineData.code == code, KLineData.kl_type == "WEEK",
            KLineData.timestamp >= week_start_ts,
        ).delete(synchronize_session=False)
        db.add_all(week_rows)
        db.commit()
