"""
TradingView UDF datafeed 后端 — 供 charting_library 的 datafeeds/udf 魔改版调用

端点(与 chanlun-pro 的 /tv 协议兼容,前端三件套可无缝对接):
    GET /tv/config    UDF 配置
    GET /tv/symbols   商品解析 (symbol="a:000001")
    GET /tv/search    商品检索 (代码/名称模糊)
    GET /tv/history   K线柱 + 缠论扩展字段(fxs/bis/xds/zsds/bi_zss/xd_zss/zsd_zss/bcs/mmds/update)

认证: UDF 请求由 charting_library 发起,不带 Authorization 头,
     走 httpOnly cookie `tv_token`(登录端点下发,同 JWT)。

数据: K线从 KLineData 表读取(DAY/WEEK/分钟);缠论由 CChan 计算(日线直连/周线级联/分钟单级别)。
     缠论结果按 (code, kl_type, 库内最后K线日期) 进程内缓存——库内数据只在日更后变化,
     盘中轮询(firstDataRequest=false)全命中缓存,无重算开销。

周期: 日线("1D")/周线("1W") 全量缓存;分钟(5/15/30/60)按需缓存——
     首次请求某只股票的分钟周期时从 tdx 拉取入缓存(ChanAnalyzer.intraday_cache,
     带并发防重,拉取需数秒),之后走库;日更只刷新已缓存组合。
"""
import time as time_mod
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ChanAnalyzer.database import get_db, KLineData
from ChanAnalyzer.intraday_cache import (
    INTRADAY_KL_TYPES, ensure_intraday, ensure_intraday_fresh, ensure_day_fresh,
)
from ChanAnalyzer.okx_cache import ensure_okx, ensure_okx_fresh, OKX_MARKET

router = APIRouter(prefix="/tv", tags=["tv"])

# ---- 限流(学 chanlun-pro: 非首次请求 5 秒内同 symbol+resolution 超 5 次返回 no_data) ----
_history_req_counter: dict = {}

# ---- 缠论计算缓存: (code, kl_type) -> (last_kline_date_str, chart_data_dict) ----
_cl_cache: dict = {}


# ==================== 工具 ====================

def _to_unix(date_str: str) -> int:
    """'YYYY/MM/DD[ HH:MM[:SS]]' -> 本地时区 unix 秒"""
    s = str(date_str)[:19]
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).timestamp())
        except ValueError:
            continue
    return 0


# TV resolution -> KLineData.kl_type(分钟周期对应按需缓存)
_RESOLUTION_KL = {
    "1": "1M", "5": "5M", "15": "15M", "30": "30M", "60": "60M", "240": "4H",
    "1D": "DAY", "D": "DAY", "DAY": "DAY",
    "1W": "WEEK", "W": "WEEK", "WEEK": "WEEK",
}


def _resolve_symbol(symbol: str):
    """'a:000001' -> ('000001', 'a'); 'okx:BTC-USDT' -> ('BTC-USDT', 'okx'); 兼容裸代码 '000001'"""
    parts = symbol.split(":")
    if len(parts) == 2:
        return parts[1].strip(), parts[0].strip().lower()
    return parts[0].strip(), "a"


def _okx_inst_name(inst_id: str) -> str:
    """'BTC-USDT' -> 'BTC'(白名单现货,展示用简名)"""
    return inst_id.split("-")[0]


def _okx_pricescale(last_close: Optional[float]) -> int:
    """按价格量级动态精度(BTC 6万 vs SHIB 0.00001)"""
    if not last_close or last_close <= 0:
        return 100
    if last_close >= 1:
        return 100
    if last_close >= 0.01:
        return 10000
    return 100000000


def _get_stock_name(code: str) -> str:
    try:
        from sqlalchemy import text
        with get_db() as db:
            row = db.execute(
                text("SELECT name FROM stock_info WHERE code=:c LIMIT 1"), {"c": code}
            ).first()
            return row[0] if row else code
    except Exception:
        return code


# ==================== 认证 ====================

async def _tv_user(request: Request) -> Optional[int]:
    """cookie 通道认证: tv_token(JWT) -> user_id;失败返回 None(端点回 401)"""
    token = request.cookies.get("tv_token")
    if not token:
        return None
    from web.auth import verify_token
    with get_db() as db:
        return verify_token(token, db)


def _unauthorized():
    return JSONResponse({"s": "error", "errmsg": "unauthorized"}, status_code=401)


# ==================== 缠论 -> TV 坐标 ====================

def _build_cl_chart_data(code: str, kl_type: str, market: str = "a") -> Optional[dict]:
    """
    计算缠论并转换为 TV 画图坐标数据(带缓存)。
    返回 {bis, xds, zsds, bi_zss, xd_zss, zsd_zss, bcs, mmds} 或 None。
    """
    # 缓存命中判定: 库内最后K线日期不变则直接复用
    with get_db() as db:
        last = (
            db.query(KLineData.date)
            .filter(KLineData.market == market, KLineData.code == code, KLineData.kl_type == kl_type)
            .order_by(KLineData.timestamp.desc())
            .first()
        )
    if last is None:
        return None
    last_date = last[0]
    cached = _cl_cache.get((market, code, kl_type))
    if cached and cached[0] == last_date:
        return cached[1]

    # 计算: A股周线走级联([K_WEEK,K_DAY],复权一致性);
    # 币周线单级别(无复权,直接读OKX官方1W,不依赖日线已缓存);
    # 分钟线单级别;日线走默认
    import importlib
    ChanAnalyzer = importlib.import_module("ChanAnalyzer.analyzer").ChanAnalyzer
    from Common.CEnum import KL_TYPE
    _KL_TYPE_ENUM = {"1M": KL_TYPE.K_1M, "5M": KL_TYPE.K_5M, "15M": KL_TYPE.K_15M,
                     "30M": KL_TYPE.K_30M, "60M": KL_TYPE.K_60M, "4H": KL_TYPE.K_4H}
    if kl_type == "WEEK":
        levels = [KL_TYPE.K_WEEK] if market == OKX_MARKET else [KL_TYPE.K_WEEK, KL_TYPE.K_DAY]
        analyzer = ChanAnalyzer(code=code, levels=levels)
        analysis = analyzer.get_analysis()
    elif kl_type in _KL_TYPE_ENUM:
        analyzer = ChanAnalyzer(code=code, levels=[_KL_TYPE_ENUM[kl_type]])
        analysis = analyzer.get_analysis()
    else:
        analyzer = ChanAnalyzer(code=code)
        analysis = analyzer.get_analysis()

    if "error" in analysis:
        return None

    bis = []
    for bi in analysis.get("bi_list", []):
        bis.append({
            "points": [
                {"time": _to_unix(bi["start_date"]), "price": bi["start_price"]},
                {"time": _to_unix(bi["end_date"]), "price": bi["end_price"]},
            ],
            "linestyle": "0" if bi.get("is_sure", True) else "1",
        })

    xds = []
    for seg in analysis.get("seg_list", []):
        xds.append({
            "points": [
                {"time": _to_unix(seg["start_date"]), "price": seg["start_price"]},
                {"time": _to_unix(seg["end_date"]), "price": seg["end_price"]},
            ],
            "linestyle": "0" if seg.get("is_sure", True) else "1",
        })

    bi_zss = []
    for zs in analysis.get("zs_list", []):
        bi_zss.append({
            "points": [
                {"time": _to_unix(zs["start_date"]), "price": zs["high"]},
                {"time": _to_unix(zs["end_date"]), "price": zs["low"]},
            ],
            "linestyle": "0",
        })

    # 分型: text="ding"顶(红)/"di"底(蓝),与 chanlun-pro 前端约定一致。
    # 只保留构成笔端点的分型(全量识别分型数量是笔的~4倍,视觉噪音大)
    bi_times = set()
    for bi in bis:
        bi_times.add(bi["points"][0]["time"])
        bi_times.add(bi["points"][1]["time"])
    fxs = []
    for fx in analysis.get("fx_list", []):
        t = _to_unix(fx["date"])
        if t in bi_times:
            fxs.append({
                "points": [
                    {"time": t, "price": fx["price"]},
                    {"time": t, "price": fx["price"]},
                ],
                "text": fx["type"],
            })

    # 买卖点: CChan 类型值(1/1p/2/2s/3a/3b) + 买B/卖S方向后缀,如 "2B" "2sS"
    mmds = []
    for sig in analysis.get("buy_signals", []) + analysis.get("sell_signals", []):
        t = str(sig.get("type") or "?").strip().strip(",")
        text = f"{t}{'B' if sig.get('is_buy', True) else 'S'}"
        mmds.append({
            "points": {"time": _to_unix(sig["date"]), "price": sig["price"]},
            "text": text,
        })

    data = {
        "fxs": fxs,
        "bis": bis,
        "xds": xds,
        "zsds": [],       # 走势段: CChan 引擎无该级别
        "bi_zss": bi_zss,
        "xd_zss": [],     # 线段中枢: CChan 引擎无线段级中枢(多级别靠周期切换)
        "zsd_zss": [],
        "bcs": [],        # 背驰标记: CChan 不单独输出(买卖点即背驰应用)
        "mmds": mmds,
    }
    _cl_cache[(market, code, kl_type)] = (last_date, data)
    return data


# ==================== 端点 ====================

@router.get("/config")
async def tv_config(request: Request):
    if await _tv_user(request) is None:
        return _unauthorized()
    return {
        "supports_search": True,
        "supports_group_request": False,
        "supported_resolutions": ["1", "5", "15", "30", "60", "240", "1D", "1W"],
        "supports_marks": False,
        "supports_timescale_marks": False,
        "supports_time": True,
        "exchanges": [
            {"value": "a", "name": "沪深", "desc": "沪深A股"},
            {"value": "okx", "name": "OKX", "desc": "OKX加密货币(现货)"},
        ],
    }


@router.get("/symbols")
async def tv_symbols(request: Request, symbol: str = ""):
    if await _tv_user(request) is None:
        return _unauthorized()
    code, market = _resolve_symbol(symbol)
    if market == OKX_MARKET:
        # OKX 现货: 7x24,精度按价格动态
        from ChanAnalyzer.okx_cache import _whitelist
        if code not in _whitelist():
            return JSONResponse({"s": "error", "errmsg": f"not in OKX whitelist: {code}"}, status_code=400)
        last_close = None
        with get_db() as db:
            row = (
                db.query(KLineData.close)
                .filter(KLineData.market == OKX_MARKET, KLineData.code == code,
                        KLineData.kl_type == "DAY")
                .order_by(KLineData.timestamp.desc())
                .first()
            )
            last_close = row[0] if row else None
        return {
            "name": code,
            "ticker": f"{market}:{code}",
            "full_name": f"{market}:{code}",
            "description": _okx_inst_name(code),
            "exchange": market,
            "type": "crypto",
            "session": "24x7",
            "timezone": "Asia/Shanghai",
            "pricescale": _okx_pricescale(last_close),
            "minmov": 1,
            "has_intraday": True,
            "intraday_multipliers": ["1", "5", "15", "30", "60", "240"],
            "has_daily": True,
            "has_weekly_and_monthly": True,
            "supported_resolutions": ["1", "5", "15", "30", "60", "240", "1D", "1W"],
            "visible_plots_set": "ohlcv",
        }
    if len(code) != 6 or not code.isdigit():
        return JSONResponse({"s": "error", "errmsg": f"invalid symbol: {symbol}"}, status_code=400)
    return {
        "name": code,
        "ticker": f"{market}:{code}",
        "full_name": f"{market}:{code}",
        "description": _get_stock_name(code),
        "exchange": market,
        "type": "stock",
        "session": "0930-1130,1300-1500",
        "timezone": "Asia/Shanghai",
        "pricescale": 100,
        "minmov": 1,
        "has_intraday": True,
        "intraday_multipliers": ["5", "15", "30", "60"],  # 分钟线按需缓存,首次拉取需数秒(tdx仅此四档)
        "has_daily": True,
        "has_weekly_and_monthly": True,
        "supported_resolutions": ["5", "15", "30", "60", "1D", "1W"],
        "visible_plots_set": "ohlcv",
    }


@router.get("/search")
async def tv_search(
    request: Request,
    query: str = "",
    type: str = "",
    exchange: str = "a",
    limit: int = 30,
):
    if await _tv_user(request) is None:
        return _unauthorized()
    q = query.strip().lower()
    out = []
    if q:
        from sqlalchemy import text
        with get_db() as db:
            if q.isdigit():
                rows = db.execute(
                    text("SELECT code, name FROM stock_info WHERE code LIKE :q ORDER BY code LIMIT :n"),
                    {"q": f"{q}%", "n": limit},
                ).fetchall()
            else:
                rows = db.execute(
                    text("SELECT code, name FROM stock_info WHERE lower(name) LIKE :q ORDER BY code LIMIT :n"),
                    {"q": f"%{q}%", "n": limit},
                ).fetchall()
        for code, name in rows:
            out.append({
                "symbol": code,
                "name": code,
                "full_name": f"a:{code}",
                "description": name,
                "exchange": "a",
                "ticker": f"a:{code}",
                "type": type or "stock",
                "session": "0930-1130,1300-1500",
                "timezone": "Asia/Shanghai",
                "supported_resolutions": ["5", "15", "30", "60", "1D", "1W"],
            })
        # OKX 白名单币(代码或简名前缀匹配,如输入 btc)
        if exchange in ("a", "", "all") or exchange == "okx":
            from ChanAnalyzer.okx_cache import _whitelist
            for inst in sorted(_whitelist()):
                base = inst.split("-")[0].lower()
                if q in base or inst.lower().startswith(q):
                    out.append({
                        "symbol": inst,
                        "name": inst,
                        "full_name": f"okx:{inst}",
                        "description": inst.split("-")[0],
                        "exchange": "okx",
                        "ticker": f"okx:{inst}",
                        "type": "crypto",
                        "session": "24x7",
                        "timezone": "Asia/Shanghai",
                        "supported_resolutions": ["1", "5", "15", "30", "60", "240", "1D", "1W"],
                    })
    return out


def _history_response(rows, cl, status: str, first_data_request: str) -> dict:
    """/tv/history 响应组装(A股/OKX 共用): 尾部切片 + 缠论扩展字段"""
    def _tail(seq, n):
        return seq if first_data_request == "true" else seq[-n:]

    return {
        "s": status,
        "t": _tail([_to_unix(r.date) for r in rows], 10),
        "o": _tail([r.open for r in rows], 10),
        "h": _tail([r.high for r in rows], 10),
        "l": _tail([r.low for r in rows], 10),
        "c": _tail([r.close for r in rows], 10),
        "v": _tail([r.volume or 0 for r in rows], 10),
        "fxs": _tail(cl["fxs"], 5),
        "bis": _tail(cl["bis"], 5),
        "xds": _tail(cl["xds"], 5),
        "zsds": _tail(cl["zsds"], 5),
        "bi_zss": _tail(cl["bi_zss"], 5),
        "xd_zss": _tail(cl["xd_zss"], 5),
        "zsd_zss": _tail(cl["zsd_zss"], 5),
        "bcs": _tail(cl["bcs"], 5),
        "mmds": _tail(cl["mmds"], 5),
        "update": first_data_request != "true",  # 后续轮询数据标志
    }


async def _tv_history_okx(code: str, kl_type: str, to, first_data_request: str, status: str) -> dict:
    """OKX 币的 history: market 过滤查询 + 按需缓存(首拉含load_markets可能30s+) + 7x24兜底"""
    from starlette.concurrency import run_in_threadpool

    def _query():
        with get_db() as db:
            return (
                db.query(KLineData)
                .filter(KLineData.market == OKX_MARKET, KLineData.code == code,
                        KLineData.kl_type == kl_type)
                .order_by(KLineData.timestamp.asc())
                .all()
            )

    rows = await run_in_threadpool(_query)
    if not rows:
        await run_in_threadpool(ensure_okx, code, kl_type)
        rows = await run_in_threadpool(_query)
    else:
        refreshed = await run_in_threadpool(ensure_okx_fresh, code, kl_type, rows[-1].timestamp)
        if refreshed:
            rows = await run_in_threadpool(_query)
    if not rows:
        return {"s": "no_data"}
    if to is not None and to < _to_unix(rows[0].date):
        return {"s": "no_data"}

    cl = _build_cl_chart_data(code, kl_type, market=OKX_MARKET) or {
        "fxs": [], "bis": [], "xds": [], "zsds": [],
        "bi_zss": [], "xd_zss": [], "zsd_zss": [], "bcs": [], "mmds": [],
    }
    return _history_response(rows, cl, status, first_data_request)


@router.get("/refresh")
async def tv_refresh(request: Request, code: str = "", resolution: str = "1D"):
    """用户点击"刷新数据"按钮: 对币强制绕过冷却增量刷新当前周期缓存。

    A股不走此端点(resetData 后 history 兜底已有盘中逻辑),无缓存币种返回提示。
    """
    if await _tv_user(request) is None:
        return _unauthorized()
    code = code.strip().upper()
    if not code:
        return {"ok": False, "msg": "缺少 code"}
    kl_type = _RESOLUTION_KL.get(resolution, "DAY")
    from starlette.concurrency import run_in_threadpool

    def _do_refresh():
        from ChanAnalyzer.okx_cache import ensure_okx, ensure_okx_fresh
        from ChanAnalyzer.database import KLineData
        with get_db() as db:
            last = (
                db.query(KLineData.timestamp)
                .filter(KLineData.market == OKX_MARKET, KLineData.code == code,
                        KLineData.kl_type == kl_type)
                .order_by(KLineData.timestamp.desc())
                .first()
            )
        if not last or not last[0]:
            rows = ensure_okx(code, kl_type)
            return {"ok": rows != 0, "msg": "已按需拉取" if rows else "拉取失败或不在白名单"}
        ensure_okx(code, kl_type)  # 顺带补全(数量不足时)
        ensure_okx_fresh(code, kl_type, last[0], force=True)
        return {"ok": True, "msg": "已刷新"}

    try:
        return await run_in_threadpool(_do_refresh)
    except Exception as e:
        return {"ok": False, "msg": f"刷新失败: {e}"}


@router.get("/history")
async def tv_history(
    request: Request,
    symbol: str = "",
    resolution: str = "1D",
    from_: Optional[int] = Query(None, alias="from"),
    to: Optional[int] = None,
    firstDataRequest: str = "false",
):
    if await _tv_user(request) is None:
        return _unauthorized()

    code, market = _resolve_symbol(symbol)
    kl_type = _RESOLUTION_KL.get(resolution, "DAY")

    now = time_mod.time()
    status = "ok"
    if firstDataRequest == "false":
        # 限流: 5 秒内同 symbol+resolution 超过 5 次返回 no_data
        key = f"{market}_{code}_{resolution}"
        cnt = _history_req_counter.get(key)
        if cnt and cnt["counter"] >= 5 and now - cnt["tm"] <= 5:
            _history_req_counter[key] = {"counter": 0, "tm": now}
            status = "no_data"
        elif cnt and now - cnt["tm"] <= 5:
            _history_req_counter[key] = {"counter": cnt["counter"] + 1, "tm": cnt["tm"]}
        else:
            _history_req_counter[key] = {"counter": 0, "tm": now}

    if market == OKX_MARKET:
        return await _tv_history_okx(code, kl_type, to, firstDataRequest, status)

    # K线(从 KLineData 读,不经过引擎内部K线,保证完整 OHLCV)
    with get_db() as db:
        rows = (
            db.query(KLineData)
            .filter(KLineData.market == "a", KLineData.code == code, KLineData.kl_type == kl_type)
            .order_by(KLineData.timestamp.asc())
            .all()
        )

    # 分钟周期按需缓存: 库内无数据时首次从 tdx 拉取入缓存(阻塞数秒,丢线程池避免卡事件循环)
    if not rows and kl_type in INTRADAY_KL_TYPES:
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(ensure_intraday, code, kl_type)
        with get_db() as db:
            rows = (
                db.query(KLineData)
                .filter(KLineData.code == code, KLineData.kl_type == kl_type)
                .order_by(KLineData.timestamp.asc())
                .all()
            )
    elif rows and kl_type in INTRADAY_KL_TYPES:
        # 盘中/日更前兜底刷新: 内部轻量判断,数据过期才真正增量拉取(冷却=周期与10分钟较大值)
        from starlette.concurrency import run_in_threadpool
        refreshed = await run_in_threadpool(ensure_intraday_fresh, code, kl_type, rows[-1].timestamp)
        if refreshed:
            with get_db() as db:
                rows = (
                    db.query(KLineData)
                    .filter(KLineData.code == code, KLineData.kl_type == kl_type)
                    .order_by(KLineData.timestamp.asc())
                    .all()
                )
    elif rows and kl_type == "DAY":
        # 日线兜底刷新: 盘中追当日实时bar(未收盘,缠论现虚线笔),收盘后30分钟补最终收盘价
        from starlette.concurrency import run_in_threadpool
        refreshed = await run_in_threadpool(ensure_day_fresh, code, rows[-1].timestamp)
        if refreshed:
            with get_db() as db:
                rows = (
                    db.query(KLineData)
                    .filter(KLineData.code == code, KLineData.kl_type == kl_type)
                    .order_by(KLineData.timestamp.asc())
                    .all()
                )
    if not rows:
        return {"s": "no_data"}

    # 图表请求窗口早于数据起点 -> no_data
    if to is not None and to < _to_unix(rows[0].date):
        return {"s": "no_data"}

    cl = _build_cl_chart_data(code, kl_type) or {
        "fxs": [], "bis": [], "xds": [], "zsds": [],
        "bi_zss": [], "xd_zss": [], "zsd_zss": [], "bcs": [], "mmds": [],
    }
    return _history_response(rows, cl, status, firstDataRequest)


@router.get("/time")
async def tv_time(request: Request):
    if await _tv_user(request) is None:
        return _unauthorized()
    return int(time_mod.time())


# ==================== 图表布局云同步(TV save_load,按登录用户隔离) ====================

_Kind = str  # 'chart' | 'template'


def _chart_not_found():
    return JSONResponse({"status": "error", "message": "chart not found"}, status_code=404)


async def _charts_storage(
    request: Request,
    version: str,
    kind: _Kind,
):
    """
    TV charting_library save_load 存储协议(与 chanlun-pro 同形状):
        GET    /tv/{version}/charts?client&user[&chart]      列表 / 单取
        POST   /tv/{version}/charts?client&user[&chart]      新建 / 更新(form: name,content,symbol,resolution)
        DELETE /tv/{version}/charts?client&user&chart        删除
    user 归属以 tv_token 认证为准(不信任 query 的 user 参数,多用户隔离)。
    """
    user_id = await _tv_user(request)
    if user_id is None:
        return _unauthorized()
    client = request.query_params.get("client", "")
    chart_param = request.query_params.get("chart") or request.query_params.get("template")

    from ChanAnalyzer.database import TvChart
    with get_db() as db:
        if request.method == "GET":
            if chart_param is None:
                items = (
                    db.query(TvChart)
                    .filter(TvChart.user_id == user_id, TvChart.kind == kind, TvChart.client == client)
                    .order_by(TvChart.ts.desc())
                    .all()
                )
                return {"status": "ok", "data": [
                    {"id": c.id, "name": c.name, "symbol": c.symbol,
                     "resolution": c.resolution, "timestamp": c.ts}
                    for c in items
                ]}
            c = db.query(TvChart).filter(
                TvChart.id == int(chart_param), TvChart.user_id == user_id, TvChart.kind == kind
            ).first()
            if not c:
                return _chart_not_found()
            return {"status": "ok", "data": {
                "id": c.id, "name": c.name, "content": c.content, "timestamp": c.ts,
            }}

        if request.method == "DELETE":
            if chart_param is None:
                return _chart_not_found()
            db.query(TvChart).filter(
                TvChart.id == int(chart_param), TvChart.user_id == user_id, TvChart.kind == kind
            ).delete(synchronize_session=False)
            db.commit()
            return {"status": "ok"}

        # POST: 新建或更新
        form = await request.form()
        name = str(form.get("name") or "").strip() or "未命名"
        content = str(form.get("content") or "")
        symbol = str(form.get("symbol") or "")
        resolution = str(form.get("resolution") or "")
        now = int(time_mod.time())
        if chart_param is None:
            c = TvChart(user_id=user_id, kind=kind, client=client, name=name,
                        content=content, symbol=symbol, resolution=resolution, ts=now)
            db.add(c)
            db.commit()
            return {"status": "ok", "id": c.id}
        c = db.query(TvChart).filter(
            TvChart.id == int(chart_param), TvChart.user_id == user_id, TvChart.kind == kind
        ).first()
        if not c:
            return _chart_not_found()
        c.name, c.content, c.symbol, c.resolution, c.ts = name, content, symbol, resolution, now
        db.commit()
        return {"status": "ok"}


@router.get("/{version}/charts")
@router.post("/{version}/charts")
@router.delete("/{version}/charts")
async def tv_charts(request: Request, version: str):
    return await _charts_storage(request, version, kind="chart")


@router.get("/{version}/study_templates")
@router.post("/{version}/study_templates")
@router.delete("/{version}/study_templates")
async def tv_study_templates(request: Request, version: str):
    return await _charts_storage(request, version, kind="template")
