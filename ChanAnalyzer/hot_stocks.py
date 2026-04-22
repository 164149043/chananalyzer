"""
热门股票模块

支持6种排名类型：
- top_gainers:  涨幅前N（按涨跌幅降序）
- top_losers:   跌幅前N（按涨跌幅升序）
- top_volume:   成交量前N（按成交量降序）
- top_amount:   成交额前N（按成交额降序）
- top_turnover: 换手率前N（需要 daily_basic 接口）
- dragon_tiger: 龙虎榜（使用 top_list 接口）
"""
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional


RANK_TYPES = ['top_gainers', 'top_losers', 'top_volume', 'top_amount', 'top_turnover', 'dragon_tiger']


def get_hot_stocks(
    rank_type: str = 'top_gainers',
    top_n: int = 100,
    trade_date: str = None,
) -> List[Dict[str, Any]]:
    """
    获取热门股票

    Args:
        rank_type: 排名类型，见 RANK_TYPES
        top_n: 返回数量（默认100）
        trade_date: 交易日期 YYYYMMDD（默认最近交易日）

    Returns:
        股票列表，每项包含 code 和排名指标
    """
    import tushare as ts

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise ValueError("请设置 TUSHARE_TOKEN 环境变量")

    ts.set_token(token)
    pro = ts.pro_api()

    if trade_date is None:
        trade_date = _find_latest_trade_date(pro)

    if rank_type == 'dragon_tiger':
        return _get_dragon_tiger(pro, trade_date, top_n)
    elif rank_type == 'top_turnover':
        return _get_top_turnover(pro, trade_date, top_n)
    else:
        return _get_from_daily(pro, trade_date, rank_type, top_n)


def _get_from_daily(pro, trade_date: str, rank_type: str, top_n: int) -> List[Dict]:
    """从 pro.daily() 获取：涨幅/跌幅/成交量排名"""
    df = pro.daily(trade_date=trade_date)
    if df is None or df.empty:
        return []

    # 只保留A股
    df = df[df['ts_code'].str.endswith(('.SZ', '.SH'))]

    # 排序
    if rank_type == 'top_gainers':
        df = df.sort_values('pct_chg', ascending=False)
    elif rank_type == 'top_losers':
        df = df.sort_values('pct_chg', ascending=True)
    elif rank_type == 'top_volume':
        df = df.sort_values('vol', ascending=False)
    elif rank_type == 'top_amount':
        df = df.sort_values('amount', ascending=False)

    df = df.head(top_n)

    results = []
    for _, row in df.iterrows():
        results.append({
            'code': row['ts_code'][:6],
            'ts_code': row['ts_code'],
            'name': '',
            'open': _safe_float(row, 'open'),
            'high': _safe_float(row, 'high'),
            'low': _safe_float(row, 'low'),
            'close': _safe_float(row, 'close'),
            'pre_close': _safe_float(row, 'pre_close'),
            'change': _safe_float(row, 'change'),
            'pct_chg': _safe_float(row, 'pct_chg'),
            'vol': _safe_float(row, 'vol'),
            'amount': _safe_float(row, 'amount'),
            'trade_date': trade_date,
        })

    _fill_stock_names(results)
    return results


def _get_top_turnover(pro, trade_date: str, top_n: int) -> List[Dict]:
    """获取换手率排名（需要 daily_basic 接口）"""
    df = pro.daily_basic(trade_date=trade_date, fields='ts_code,turnover_rate,close,volume,amount')
    if df is None or df.empty:
        return []

    df = df[df['ts_code'].str.endswith(('.SZ', '.SH'))]
    df = df.sort_values('turnover_rate', ascending=False).head(top_n)

    results = []
    for _, row in df.iterrows():
        results.append({
            'code': row['ts_code'][:6],
            'ts_code': row['ts_code'],
            'name': '',
            'close': _safe_float(row, 'close'),
            'vol': _safe_float(row, 'volume'),
            'amount': _safe_float(row, 'amount'),
            'turnover_rate': _safe_float(row, 'turnover_rate'),
            'trade_date': trade_date,
        })

    _fill_stock_names(results)
    return results


def _get_dragon_tiger(pro, trade_date: str, top_n: int) -> List[Dict]:
    """获取龙虎榜股票"""
    df = pro.top_list(trade_date=trade_date)
    if df is None or df.empty:
        return []

    df = df[df['ts_code'].str.endswith(('.SZ', '.SH'))]
    # 去重（同一股票可能有多条记录）
    df = df.drop_duplicates(subset='ts_code').head(top_n)

    results = []
    for _, row in df.iterrows():
        results.append({
            'code': row['ts_code'][:6],
            'ts_code': row['ts_code'],
            'name': str(row.get('name', '')),
            'close': _safe_float(row, 'close'),
            'pct_chg': _safe_float(row, 'pct_change'),
            'reason': str(row.get('exalter', '')),
            'buy_amount': _safe_float(row, 'buy_amount'),
            'sell_amount': _safe_float(row, 'sell_amount'),
            'net_amount': _safe_float(row, 'net_amount'),
            'trade_date': trade_date,
        })

    return results


def _find_latest_trade_date(pro) -> str:
    """探测最近有数据的交易日"""
    today = datetime.now()

    for i in range(6):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        trade_date = d.strftime('%Y%m%d')
        df = pro.daily(trade_date=trade_date)
        if df is not None and not df.empty:
            return trade_date

    # 兜底：用上周五
    return (today - timedelta(days=today.weekday() + 3)).strftime('%Y%m%d')


def _safe_float(row, key: str, default: float = 0.0) -> float:
    """安全获取 float 值，处理 NaN"""
    import pandas as pd
    val = row.get(key, default)
    if pd.isna(val):
        return default
    return float(val)


def _fill_stock_names(stocks: List[Dict[str, Any]]):
    """从 StockPool 填充股票名称"""
    try:
        from ChanAnalyzer.stock_pool import StockPool
        pool = StockPool()
        for s in stocks:
            if not s.get('name'):
                info = pool.get_stock_info(s['code'])
                if info:
                    s['name'] = info['name']
    except Exception:
        pass
