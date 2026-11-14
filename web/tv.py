"""
TradingView UDF datafeed 后端 — 供 charting_library 的 datafeeds/udf 魔改版调用

端点(与 chanlun-pro 的 /tv 协议兼容,前端三件套可无缝对接):
    GET /tv/config    UDF 配置
    GET /tv/symbols   商品解析 (symbol="a:000001")
    GET /tv/search    商品检索 (代码/名称模糊)
    GET /tv/history   K线柱 + 缠论扩展字段(fxs/bis/xds/zsds/bi_zss/xd_zss/zsd_zss/bcs/mmds/update)

认证: UDF 请求由 charting_library 发起,不带 Authorization 头,
     走 httpOnly cookie `tv_token`(登录端点下发,同 JWT)。

数据: K线从 KLineData 表读取(DAY/WEEK);缠论由 CChan 计算(日线直连/周线级联)。
     缠论结果按 (code, kl_type, 库内最后K线日期) 进程内缓存——库内数据只在日更后变化,
     盘中轮询(firstDataRequest=false)全命中缓存,无重算开销。

周期: 阶段B 仅日线("1D")与周线("1W");分钟线待阶段C后接入。
"""
import time as time_mod
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ChanAnalyzer.database import get_db, KLineData

router = APIRouter(prefix="/tv", tags=["tv"])

# ---- 限流(学 chanlun-pro: 非首次请求 5 秒内同 symbol+resolution 超 5 次返回 no_data) ----
_history_req_counter: dict = {}

# ---- 缠论计算缓存: (code, kl_type) -> (last_kline_date_str, chart_data_dict) ----
_cl_cache: dict = {}


# ==================== 工具 ====================

def _to_unix(date_str: str) -> int:
    """'YYYY/MM/DD[ HH:MM:SS]' -> 本地时区 unix 秒"""
    s = str(date_str)[:19]
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).timestamp())
        except ValueError:
            continue
    return 0


def _resolve_symbol(symbol: str):
    """'a:000001' -> ('000001', 'a'); 兼容裸代码 '000001'"""
    parts = symbol.split(":")
    if len(parts) == 2:
        return parts[1].strip(), parts[0].strip().lower()
    return parts[0].strip(), "a"


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

def _build_cl_chart_data(code: str, kl_type: str) -> Optional[dict]:
    """
    计算缠论并转换为 TV 画图坐标数据(带缓存)。
    返回 {bis, xds, zsds, bi_zss, xd_zss, zsd_zss, bcs, mmds} 或 None。
    """
    # 缓存命中判定: 库内最后K线日期不变则直接复用
    with get_db() as db:
        last = (
            db.query(KLineData.date)
            .filter(KLineData.code == code, KLineData.kl_type == kl_type)
            .order_by(KLineData.timestamp.desc())
            .first()
        )
    if last is None:
        return None
    last_date = last[0]
    cached = _cl_cache.get((code, kl_type))
    if cached and cached[0] == last_date:
        return cached[1]

    # 计算: 周线走级联(lv_list 从大到小: [K_WEEK, K_DAY],level 0 即周线),日线走默认
    import importlib
    ChanAnalyzer = importlib.import_module("ChanAnalyzer.analyzer").ChanAnalyzer
    if kl_type == "WEEK":
        from Common.CEnum import KL_TYPE
        analyzer = ChanAnalyzer(code=code, levels=[KL_TYPE.K_WEEK, KL_TYPE.K_DAY])
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

    # 买卖点: 1buy->1B / 2sell->2S / l3buy->L3B ...
    _mm_short = {"l2buy": "L2B", "l3buy": "L3B", "l2sell": "L2S", "l3sell": "L3S"}

    def _mm_label(t_raw, t_str):
        # t_raw 可能是 list(CChan 一个买卖点可属多个类型)
        try:
            if isinstance(t_raw, (list, tuple)):
                t_raw = t_raw[0] if len(t_raw) == 1 else ",".join(str(x) for x in t_raw)
            if isinstance(t_raw, (int, str)) and str(t_raw) in _mm_short:
                return _mm_short[str(t_raw)]
        except Exception:
            pass
        s = str(t_str).replace("买", "B").replace("卖", "S").replace(" ", "")
        return s if s else str(t_str)

    mmds = []
    for sig in analysis.get("buy_signals", []) + analysis.get("sell_signals", []):
        mmds.append({
            "points": {"time": _to_unix(sig["date"]), "price": sig["price"]},
            "text": _mm_label(sig.get("type_raw"), sig.get("type", "")),
        })

    data = {
        "fxs": [],        # 分型: 阶段B暂不输出(笔端点已含分型信息)
        "bis": bis,
        "xds": xds,
        "zsds": [],       # 走势段: CChan 引擎无该级别
        "bi_zss": bi_zss,
        "xd_zss": [],     # 线段中枢: 引擎当前仅输出笔中枢
        "zsd_zss": [],
        "bcs": [],        # 背驰标记: 阶段B暂不输出
        "mmds": mmds,
    }
    _cl_cache[(code, kl_type)] = (last_date, data)
    return data


# ==================== 端点 ====================

@router.get("/config")
async def tv_config(request: Request):
    if await _tv_user(request) is None:
        return _unauthorized()
    return {
        "supports_search": True,
        "supports_group_request": False,
        "supported_resolutions": ["1D", "1W"],
        "supports_marks": False,
        "supports_timescale_marks": False,
        "supports_time": True,
        "exchanges": [{"value": "a", "name": "沪深", "desc": "沪深A股"}],
    }


@router.get("/symbols")
async def tv_symbols(request: Request, symbol: str = ""):
    if await _tv_user(request) is None:
        return _unauthorized()
    code, market = _resolve_symbol(symbol)
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
        "has_intraday": False,      # 分钟线阶段C后接入
        "has_daily": True,
        "has_weekly_and_monthly": True,
        "supported_resolutions": ["1D", "1W"],
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
                "supported_resolutions": ["1D", "1W"],
            })
    return out


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

    code, _market = _resolve_symbol(symbol)
    kl_type = "WEEK" if resolution in ("1W", "W", "WEEK") else "DAY"

    now = time_mod.time()
    status = "ok"
    if firstDataRequest == "false":
        # 限流: 5 秒内同 symbol+resolution 超过 5 次返回 no_data
        key = f"{code}_{resolution}"
        cnt = _history_req_counter.get(key)
        if cnt and cnt["counter"] >= 5 and now - cnt["tm"] <= 5:
            _history_req_counter[key] = {"counter": 0, "tm": now}
            status = "no_data"
        elif cnt and now - cnt["tm"] <= 5:
            _history_req_counter[key] = {"counter": cnt["counter"] + 1, "tm": cnt["tm"]}
        else:
            _history_req_counter[key] = {"counter": 0, "tm": now}

    # K线(从 KLineData 读,不经过引擎内部K线,保证完整 OHLCV)
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

    def _tail(seq, n):
        return seq if firstDataRequest == "true" else seq[-n:]

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
        "update": firstDataRequest != "true",  # 后续轮询数据标志
    }


@router.get("/time")
async def tv_time(request: Request):
    if await _tv_user(request) is None:
        return _unauthorized()
    return int(time_mod.time())
