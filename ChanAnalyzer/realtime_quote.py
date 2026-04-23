"""
盘中实时行情获取模块

使用腾讯财经接口 (qt.gtimg.cn) 获取A股盘中实时价格。
非交易时段返回 None，获取失败静默回退。
"""
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional


# 内存缓存: {code: {'data': {...}, 'time': datetime}}
_quote_cache: Dict[str, Dict[str, Any]] = {}

# 缓存有效期（秒）
_CACHE_TTL = 60


def _is_trading_time() -> bool:
    """判断当前是否为A股交易时段（周一至周五 9:30-11:30, 13:00-15:00）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return (930 <= t <= 1130) or (1300 <= t <= 1500)


def _get_market_prefix(code: str) -> str:
    """根据代码判断市场前缀"""
    if code.startswith(('6',)):
        return 'sh'
    return 'sz'


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

    try:
        prefix = _get_market_prefix(code)
        url = f'https://qt.gtimg.cn/q={prefix}{code}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        })
        resp = urllib.request.urlopen(req, timeout=5)
        raw = resp.read().decode('gbk')

        # 解析: v_sh600487="1~亨通光电~600487~68.87~..."
        content = raw.split('"')[1]
        if not content:
            return None
        fields = content.split('~')

        # 腾讯接口字段映射:
        # [1]名称 [2]代码 [3]当前价 [4]昨收 [5]今开
        # [6]成交量(手) [31]涨跌额 [32]涨跌幅
        # [33]最高 [34]最低 [37]成交额(万) [30]时间
        price = float(fields[3])
        prev_close = float(fields[4])

        result = {
            'price': price,
            'open': float(fields[5]),
            'high': float(fields[33]),
            'low': float(fields[34]),
            'volume': float(fields[6]),
            'amount': float(fields[37]) * 10000,  # 万 → 元
            'prev_close': prev_close,
            'change_pct': float(fields[32]),
            'is_trading': True,
            'update_time': fields[30],
            'source': 'tencent',
        }

        # 更新缓存
        _quote_cache[code] = {'data': result, 'time': now}
        return result

    except Exception as e:
        print(f"[realtime_quote] 获取 {code} 实时行情失败: {e}")
        return None
