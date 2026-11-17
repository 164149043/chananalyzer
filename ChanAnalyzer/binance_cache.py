"""
币K线按需缓存 — 与 intraday_cache 平行的币侧存储层(market='binance')

- 数据源可切换(.env CRYPTO_SOURCE): binance(默认,公开镜像大陆可直连免代理) /
  okx(需代理,见 OKX_PROXY)。两源接口与库内时间口径完全一致,切换零迁移,
  已有缓存直接续接增量
- market 键为 'binance'(与默认数据源同名,直白易读);当前实际源仍由
  CRYPTO_SOURCE 决定(binance/okx 两源库内口径一致);TV 符号前缀/前端联动同用此键,历史 'okx' 前缀仅作输入兼容
- 按需缓存(同A股分钟策略): 用户首次请求某币某周期才拉取入缓存
- 7x24 兜底刷新(ensure_binance_fresh): 期望时间 = now - 2×周期,无收盘概念,
  与A股的 _expected_last_bar_dt(15:00收盘)完全不同
- 白名单: 只允许 .env OKX_SYMBOLS 配置的产品入库(默认前20主流),
  防止任意币码打库;未配置时用内置默认清单
"""
import threading
from datetime import datetime, timedelta
from typing import Optional

from ChanAnalyzer.database import get_db, KLineData
from ChanAnalyzer.okx_source import OkxSource

BINANCE_MARKET = "binance"
DATE_FMT_INTRADAY = "%Y/%m/%d %H:%M:%S"
DATE_FMT_DAY = "%Y/%m/%d"  # 日/周线 00:00 口径,纯日期

# 默认白名单(.env BINANCE_SYMBOLS 可覆盖,逗号分隔;MATIC 已完成向 POL 的迁移置换)
DEFAULT_BINANCE_SYMBOLS = (
    "BTC-USDT,ETH-USDT,SOL-USDT,BNB-USDT,XRP-USDT,DOGE-USDT,"
    "ADA-USDT,AVAX-USDT,LINK-USDT,TON-USDT,TRX-USDT,DOT-USDT,"
    "POL-USDT,LTC-USDT,BCH-USDT,NEAR-USDT,APT-USDT,ARB-USDT,"
    "OP-USDT,SUI-USDT"
)

_ensure_lock = threading.Lock()
_inflight: set = set()
_refresh_at: dict = {}
# (source, inst, kl) 已到数据源深度上限,不再尝试补全。
# key 带源名: 切换数据源后上限标记自动失效,新源会重新探测深度(如周线 OKX
# 只有475根,Binance 可拉满 1000+)
_depth_capped: set = set()


def _source_name() -> str:
    """.env CRYPTO_SOURCE: 'okx' 用 OKX 源;未配置/其他值默认 'binance'(镜像直连)"""
    return "okx" if _env_value("CRYPTO_SOURCE").strip().lower() == "okx" else "binance"


def _crypto_source():
    """按 CRYPTO_SOURCE 构造币K线源(两源接口一致: get_klines/close)"""
    if _source_name() == "okx":
        return OkxSource()
    from ChanAnalyzer.binance_source import BinanceSource
    return BinanceSource()


def crypto_source_label() -> str:
    """币数据源显示名(前端 banner/交易所下拉用)"""
    return "OKX" if _source_name() == "okx" else "Binance"


def _env_value(key: str) -> str:
    """读取项目根 .env 中 key 的值(未配置返回空串)。每次读文件,量级可接受。"""
    from pathlib import Path
    env = Path(__file__).parent.parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key + "=") and len(line) > len(key) + 1:
                return line.split("=", 1)[1].strip()
    return ""


def crypto_enabled_for_role(role: str) -> bool:
    """ENABLE_CRYPTO 总开关: =1 对所有用户开放;未配置/其他值仅 admin 可用。
    默认保守(关),由管理员在 .env 显式开启。"""
    if role == "admin":
        return True
    return _env_value("ENABLE_CRYPTO") == "1"


def _whitelist() -> set:
    # 新名 BINANCE_SYMBOLS 优先;历史 OKX_SYMBOLS 仍生效(兼容旧部署)
    raw = _env_value("BINANCE_SYMBOLS") or _env_value("OKX_SYMBOLS")
    if raw:
        items = [x.strip().upper() for x in raw.split(",") if x.strip()]
        if items:
            return set(items)
    return set(x.strip() for x in DEFAULT_BINANCE_SYMBOLS.split(",") if x.strip())


def _fmt(kl_type: str) -> str:
    return DATE_FMT_INTRADAY if kl_type in ("1M", "5M", "15M", "30M", "60M", "4H") else DATE_FMT_DAY


def upsert_binance(src, inst_id: str, kl_type: str, total: int, tail_only: bool = False) -> int:
    """拉取+入库。返回入库行数;失败 0。

    tail_only=False: 删该币该周期全部再插入(全量替换,拉满时用)
    tail_only=True:  只删除与新数据重叠的尾部区间再插入,保留更早历史(增量刷新用)
    """
    df = src.get_klines(inst_id, kl_type, total=total)
    if df is None or len(df) == 0:
        return 0
    fmt = _fmt(kl_type)
    rows = []
    for _, r in df.iterrows():
        dt = r["date"].to_pydatetime()
        rows.append(KLineData(
            market=BINANCE_MARKET, code=inst_id, kl_type=kl_type,
            date=dt.strftime(fmt), timestamp=dt,
            open=float(r["open"]), high=float(r["high"]),
            low=float(r["low"]), close=float(r["close"]),
            volume=float(r["volume"]) if r["volume"] else 0,
            amount=None, turnover_rate=None,
        ))
    with get_db() as db:
        q = db.query(KLineData).filter(
            KLineData.market == BINANCE_MARKET, KLineData.code == inst_id,
            KLineData.kl_type == kl_type,
        )
        if tail_only and rows:
            # 尾部增量: 只删除与新数据重叠的区间,保留更早历史——
            # 否则增量刷新(仅拉尾部百来根)会把库里千根历史砍到只剩尾部
            q = q.filter(KLineData.timestamp >= rows[0].timestamp)
        q.delete(synchronize_session=False)
        db.add_all(rows)
        db.commit()
    return len(rows)


def ensure_binance(inst_id: str, kl_type: str, total: int = 1000) -> int:
    """按需缓存入口(带并发防重)。

    库内已有 total 根才视为缓存完成;不足则重拉补全(删旧插新)——修复历史
    只拉到部分(如 15M 仅百来根)导致 TV 图/AI 分析数据残缺的情况。
    数据源深度不足(如周线 OKX 只有 475 根)时标记上限,不再反复重拉。
    Returns: -1=已缓存 / 0=失败或进行中 / >0=本次入库行数
    """
    if inst_id not in _whitelist():
        return 0
    key = (inst_id, kl_type)
    cap_key = (_source_name(), inst_id, kl_type)
    with get_db() as db:
        cnt = (
            db.query(KLineData.id)
            .filter(KLineData.market == BINANCE_MARKET, KLineData.code == inst_id,
                    KLineData.kl_type == kl_type)
            .count()
        )
    if cnt >= total or cap_key in _depth_capped:
        return -1 if cnt else 0
    with _ensure_lock:
        if key in _inflight:
            return 0
        _inflight.add(key)
    try:
        src = _crypto_source()
        try:
            rows = upsert_binance(src, inst_id, kl_type, total)
            if 0 < rows < total:
                _depth_capped.add(cap_key)
            return rows
        finally:
            src.close()
    except Exception as e:
        import traceback
        print(f"[binance_cache] ensure_binance {inst_id} {kl_type} 失败: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return 0
    finally:
        with _ensure_lock:
            _inflight.discard(key)


def _period_minutes(kl_type: str) -> int:
    return {"1M": 1, "5M": 5, "15M": 15, "30M": 30, "60M": 60, "4H": 240,
            "DAY": 24 * 60, "WEEK": 7 * 24 * 60}[kl_type]


def ensure_binance_fresh(inst_id: str, kl_type: str, last_ts: datetime, force: bool = False) -> bool:
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
        src = _crypto_source()
        try:
            # 尾部增量: 只拉足够覆盖缺口的量,仅替换尾部重叠区间(tail_only),
            # 保留更早历史——否则每次增量刷新都会把千根历史砍到只剩尾部百来根
            gap_min = max(60.0, (now - last_ts).total_seconds() / 60)
            total = int(gap_min / period) + 100  # 覆盖缺口+余量
            total = min(total, 1000)
            return upsert_binance(src, inst_id, kl_type, total, tail_only=True) > 0
        finally:
            src.close()
    except Exception:
        return False
    finally:
        with _ensure_lock:
            _inflight.discard(key)
