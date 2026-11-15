"""
OKX 币K线按需缓存 — 与 intraday_cache 平行的币侧存储层(market='okx')

- 按需缓存(同A股分钟策略): 用户首次请求某币某周期才拉取入缓存
- 7x24 兜底刷新(ensure_okx_fresh): 期望时间 = now - 2×周期,无收盘概念,
  与A股的 _expected_last_bar_dt(15:00收盘)完全不同
- 白名单: 只允许 .env OKX_SYMBOLS 配置的产品入库(默认前20主流),
  防止任意币码打库;未配置时用内置默认清单
"""
import threading
from datetime import datetime, timedelta
from typing import Optional

from ChanAnalyzer.database import get_db, KLineData
from ChanAnalyzer.okx_source import OkxSource

OKX_MARKET = "okx"
DATE_FMT_INTRADAY = "%Y/%m/%d %H:%M:%S"
DATE_FMT_DAY = "%Y/%m/%d"  # 日/周线 00:00 口径,纯日期

# 默认白名单(.env OKX_SYMBOLS 可覆盖,逗号分隔)
DEFAULT_OKX_SYMBOLS = (
    "BTC-USDT,ETH-USDT,SOL-USDT,BNB-USDT,XRP-USDT,DOGE-USDT,"
    "ADA-USDT,AVAX-USDT,LINK-USDT,TON-USDT,TRX-USDT,DOT-USDT,"
    "MATIC-USDT,LTC-USDT,BCH-USDT,NEAR-USDT,APT-USDT,ARB-USDT,"
    "OP-USDT,SUI-USDT"
)

_ensure_lock = threading.Lock()
_inflight: set = set()
_refresh_at: dict = {}
_depth_capped: set = set()  # (inst, kl) 已到数据源深度上限,不再尝试补全


def _whitelist() -> set:
    from pathlib import Path
    env = Path(__file__).parent.parent / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('OKX_SYMBOLS=') and len(line) > len('OKX_SYMBOLS='):
                items = [x.strip().upper() for x in line.split('=', 1)[1].split(',') if x.strip()]
                if items:
                    return set(items)
    return set(x.strip() for x in DEFAULT_OKX_SYMBOLS.split(',') if x.strip())


def _fmt(kl_type: str) -> str:
    return DATE_FMT_INTRADAY if kl_type in ("1M", "5M", "15M", "30M", "60M", "4H") else DATE_FMT_DAY


def upsert_okx(src: OkxSource, inst_id: str, kl_type: str, total: int) -> int:
    """拉取+入库(删旧插新)。返回入库行数;失败 0。"""
    df = src.get_klines(inst_id, kl_type, total=total)
    if df is None or len(df) == 0:
        return 0
    fmt = _fmt(kl_type)
    rows = []
    for _, r in df.iterrows():
        dt = r["date"].to_pydatetime()
        rows.append(KLineData(
            market=OKX_MARKET, code=inst_id, kl_type=kl_type,
            date=dt.strftime(fmt), timestamp=dt,
            open=float(r["open"]), high=float(r["high"]),
            low=float(r["low"]), close=float(r["close"]),
            volume=float(r["volume"]) if r["volume"] else 0,
            amount=None, turnover_rate=None,
        ))
    with get_db() as db:
        db.query(KLineData).filter(
            KLineData.market == OKX_MARKET, KLineData.code == inst_id,
            KLineData.kl_type == kl_type,
        ).delete(synchronize_session=False)
        db.add_all(rows)
        db.commit()
    return len(rows)


def ensure_okx(inst_id: str, kl_type: str, total: int = 1000) -> int:
    """按需缓存入口(带并发防重)。

    库内已有 total 根才视为缓存完成;不足则重拉补全(删旧插新)——修复历史
    只拉到部分(如 15M 仅百来根)导致 TV 图/AI 分析数据残缺的情况。
    数据源深度不足(如周线 OKX 只有 475 根)时标记上限,不再反复重拉。
    Returns: -1=已缓存 / 0=失败或进行中 / >0=本次入库行数
    """
    if inst_id not in _whitelist():
        return 0
    key = (inst_id, kl_type)
    with get_db() as db:
        cnt = (
            db.query(KLineData.id)
            .filter(KLineData.market == OKX_MARKET, KLineData.code == inst_id,
                    KLineData.kl_type == kl_type)
            .count()
        )
    if cnt >= total or key in _depth_capped:
        return -1 if cnt else 0
    with _ensure_lock:
        if key in _inflight:
            return 0
        _inflight.add(key)
    try:
        src = OkxSource()
        try:
            rows = upsert_okx(src, inst_id, kl_type, total)
            if 0 < rows < total:
                _depth_capped.add(key)
            return rows
        finally:
            src.close()
    except Exception as e:
        import traceback
        print(f"[okx_cache] ensure_okx {inst_id} {kl_type} 失败: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return 0
    finally:
        with _ensure_lock:
            _inflight.discard(key)


def _period_minutes(kl_type: str) -> int:
    return {"1M": 1, "5M": 5, "15M": 15, "30M": 30, "60M": 60, "4H": 240,
            "DAY": 24 * 60, "WEEK": 7 * 24 * 60}[kl_type]


def ensure_okx_fresh(inst_id: str, kl_type: str, last_ts: datetime, force: bool = False) -> bool:
    """7x24 兜底刷新(tv_history 每次请求调用)。

    - 期望最后bar = now - 2×周期(容忍进行中bar);冷却 = 2×周期与10分钟较大值
    - 进行中bar(未走完,币 7x24 常态)按短冷却(10分钟)更新其快照——否则日线/4H
      的最后一根bar会永远停在首次拉取时刻的OHLC
    - force=True 跳过冷却与期望检查(用户点"刷新数据"按钮时),仍带并发防重
    """
    if inst_id not in _whitelist():
        return False
    period = _period_minutes(kl_type)
    cooldown = timedelta(minutes=max(10, period * 2))
    now = datetime.now()
    key = (inst_id, kl_type)
    last_refresh = now - _refresh_at.get(key, datetime.min)
    if not force:
        # 进行中bar(币7x24常态)按10分钟短冷却更新快照;已走完的bar按长冷却等新bar
        in_progress = last_ts + timedelta(minutes=period) > now
        limit = timedelta(minutes=10) if in_progress else cooldown
        if last_refresh < limit:
            return False
        if not in_progress and last_ts >= now - timedelta(minutes=period * 2):
            return False
    with _ensure_lock:
        if key in _inflight:
            return False
        _inflight.add(key)
        _refresh_at[key] = now
    try:
        src = OkxSource()
        try:
            # 尾部增量: 只拉足够覆盖缺口的量,删旧插新(币无复权,无口径断裂风险)
            gap_min = max(60.0, (now - last_ts).total_seconds() / 60)
            total = int(gap_min / period) + 100  # 覆盖缺口+余量
            total = min(total, 1000)
            return upsert_okx(src, inst_id, kl_type, total) > 0
        finally:
            src.close()
    except Exception:
        return False
    finally:
        with _ensure_lock:
            _inflight.discard(key)
