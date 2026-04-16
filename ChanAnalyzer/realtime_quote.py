"""
盘中实时行情获取模块

使用 ts.get_realtime_quotes() 获取A股盘中实时价格。
非交易时段返回 None，获取失败静默回退。
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


# 内存缓存: {code: {'data': {...}, 'time': datetime}}
_quote_cache: Dict[str, Dict[str, Any]] = {}

# 缓存有效期（秒）
_CACHE_TTL = 60


def _is_trading_time() -> bool:
    """判断当前是否为A股交易时段（周一至周五 9:30-11:30, 13:00-15:00）"""
    now = datetime.now()
    if now.weekday() >= 5:  # 周六日
        return False
    t = now.hour * 100 + now.minute
    return (930 <= t <= 1130) or (1300 <= t <= 1500)


def get_realtime_quote(code: str) -> Optional[Dict[str, Any]]:
    """
    获取个股盘中实时行情

    Args:
        code: 股票代码 (如 "000001", "600519")

    Returns:
        盘中实时行情字典，非交易时段或获取失败返回 None
    """
    if not _is_trading_time():
        return None

    # 检查缓存
    now = datetime.now()
    if code in _quote_cache:
        cached = _quote_cache[code]
        if (now - cached['time']).total_seconds() < _CACHE_TTL:
            return cached['data']

    # 调用 tushare 旧版实时行情接口
    try:
        import tushare as ts
        df = ts.get_realtime_quotes(code)
        if df is None or df.empty:
            return None

        row = df.iloc[0]
        price = float(row['price'])
        prev_close = float(row['pre_close'])
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

        result = {
            'price': price,
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'volume': float(row['volume']),
            'amount': float(row['amount']),
            'prev_close': prev_close,
            'change_pct': round(change_pct, 2),
            'is_trading': True,
            'update_time': f"{row['date']} {row['time']}",
            'source': 'tushare_rt',
        }

        # 更新缓存
        _quote_cache[code] = {'data': result, 'time': now}
        return result

    except Exception as e:
        print(f"[realtime_quote] 获取 {code} 实时行情失败: {e}")
        return None
