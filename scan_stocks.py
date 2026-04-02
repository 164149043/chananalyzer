"""
缠论买点扫描器

批量扫描股票，筛选出有特定买卖点信号的股票
"""
import os
import sys
import json
import time
from typing import List, Dict, Any
from datetime import datetime, timedelta

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = lambda x, **kwargs: x  # 降级为无操作

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from ChanAnalyzer import ChanAnalyzer
from ChanAnalyzer.stock_info import group_by_field
from ChanAnalyzer.stock_pool import StockPool
from ChanAnalyzer.sector_flow import print_sector_flow, get_stock_money_flow, filter_stocks_by_money_flow
from Common.CEnum import KL_TYPE

# 股票列表缓存文件
STOCK_LIST_CACHE = "stock_list_cache.json"
# 缓存有效期（天）
CACHE_EXPIRE_DAYS = 7


def get_stock_list(force_refresh: bool = False) -> List[str]:
    """
    获取A股代码列表（支持本地缓存）

    Args:
        force_refresh: 是否强制刷新缓存

    Returns:
        股票代码列表
    """
    # 检查缓存
    if not force_refresh and os.path.exists(STOCK_LIST_CACHE):
        try:
            with open(STOCK_LIST_CACHE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # 检查缓存是否过期
            cache_time = datetime.fromisoformat(cache_data.get('time', ''))
            if datetime.now() - cache_time < timedelta(days=CACHE_EXPIRE_DAYS):
                print(f"从缓存读取股票列表 (缓存时间: {cache_data['time']})")
                return cache_data.get('stocks', [])
        except Exception as e:
            print(f"读取缓存失败: {e}，将重新获取")

    # 从 API 获取
    print("正在从 Tushare 获取 A 股列表...")
    import tushare as ts

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise ValueError("请设置 TUSHARE_TOKEN 环境变量")

    ts.set_token(token)
    pro = ts.pro_api()

    try:
        # 获取股票列表
        df = pro.stock_basic(
            exchange='',
            list_status='L',  # L=上市
            fields='ts_code,symbol,name'
        )

        # 只保留A股
        df = df[(df['ts_code'].str.endswith('.SZ')) | (df['ts_code'].str.endswith('.SH'))]
        df = df[~df['name'].str.contains('ST')]  # 排除ST股票

        stock_list = df['symbol'].tolist()

        # 保存到缓存
        cache_data = {
            'time': datetime.now().isoformat(),
            'stocks': stock_list,
            'count': len(stock_list)
        }
        with open(STOCK_LIST_CACHE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)

        print(f"已缓存股票列表到 {STOCK_LIST_CACHE} (7天内有效)")
        return stock_list

    except Exception as e:
        if "每小时最多访问该接口1次" in str(e):
            # 如果 API 限流，尝试使用旧缓存
            if os.path.exists(STOCK_LIST_CACHE):
                print("API 访问受限，使用旧缓存数据...")
                with open(STOCK_LIST_CACHE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                return cache_data.get('stocks', [])
            else:
                raise ValueError(
                    "API 访问受限且无可用缓存。请稍后再试，或使用 --codes 参数指定股票代码。\n"
                    "示例: python scan_stocks.py --codes 000001 000002 600000"
                )
        raise


def scan_stocks(
    stock_codes: List[str],
    buy_types: List[str] = None,
    sell_types: List[str] = None,
    begin_date: str = None,
    verbose: bool = True,
    delay: float = 0,
    show_money_flow: bool = False,
    sort_by_money_flow: bool = False,
    min_money_flow: float = 0,
) -> List[Dict[str, Any]]:
    """
    扫描股票列表，筛选出有特定买卖点的股票

    Args:
        stock_codes: 股票代码列表
        buy_types: 要筛选的买入类型，如 ['2', '3a', '3b']
        sell_types: 要筛选的卖出类型
        begin_date: 开始日期
        verbose: 是否打印进度

    Returns:
        匹配的股票列表，每只股票包含代码、价格、信号列表
    """
    if buy_types is None:
        buy_types = ['2', '3a', '3b']  # 默认二买、三买
    if sell_types is None:
        sell_types = ['2s', '3a', '3b']  # 默认二卖、三卖

    results = []
    total = len(stock_codes)

    # 创建进度条
    iterator = enumerate(stock_codes)
    if verbose:
        iterator = tqdm(enumerate(stock_codes), total=total, desc="扫描进度", unit="股")

    for i, code in iterator:
        try:
            analyzer = ChanAnalyzer(code=code, begin_date=begin_date)

            analysis = analyzer.get_analysis()

            # 检查是否有匹配的买卖点
            matched_signals = check_signals(analysis, buy_types, sell_types)

            if matched_signals:
                result = {
                    'code': code,
                    'signals': matched_signals,
                    'current_price': analysis.get('current_price', 0),
                }

                # 获取资金流向
                if show_money_flow or sort_by_money_flow or min_money_flow > 0:
                    flow = get_stock_money_flow(code)
                    result['money_flow'] = flow

                results.append(result)
                if verbose and HAS_TQDM:
                    # 在进度条后显示找到的股票
                    iterator.set_postfix_str(f"找到: {len(results)}")

        except Exception as e:
            if verbose and "加载" in str(e):
                if HAS_TQDM:
                    iterator.write(f"  [跳过 {code}] 数据加载失败")
                else:
                    print(f"  [跳过 {code}] 数据加载失败")
            # 延迟以避免触发 API 频次限制
            if delay > 0:
                time.sleep(delay)
            continue

    # 按资金流向筛选
    if min_money_flow > 0:
        results = [
            r for r in results
            if r.get('money_flow') and r['money_flow'].get('net_main_amount', 0) >= min_money_flow
        ]

    # 按资金流向排序
    if sort_by_money_flow:
        results.sort(
            key=lambda x: x.get('money_flow', {}).get('net_main_amount', 0),
            reverse=True
        )

    return results


def check_signals(
    analysis: Dict[str, Any],
    buy_types: List[str],
    sell_types: List[str]
) -> List[Dict[str, Any]]:
    """检查分析结果中是否有匹配的买卖点"""
    matched = []

    levels = [analysis]

    for level in levels:
        kl_type = level.get('kl_type', '')

        # 检查买入信号
        for signal in level.get('buy_signals', []):
            signal_type = signal.get('type', '').split(',')[0]
            if signal_type in buy_types:
                matched.append({
                    'type': signal_type,
                    'direction': '买入',
                    'date': signal['date'],
                    'price': signal['price'],
                    'period': kl_type,
                })

        # 检查卖出信号
        for signal in level.get('sell_signals', []):
            signal_type = signal.get('type', '').split(',')[0]
            if signal_type in sell_types:
                matched.append({
                    'type': signal_type,
                    'direction': '卖出',
                    'date': signal['date'],
                    'price': signal['price'],
                    'period': kl_type,
                })

    return matched


def print_results(results: List[Dict[str, Any]], group_by: str = 'none'):
    """打印扫描结果

    Args:
        results: 扫描结果列表
        group_by: 分组方式 ('industry', 'area', 'none')
    """
    if not results:
        print("\n未找到符合条件的股票")
        return

    if group_by == 'none':
        _print_list_view(results)
    else:
        _print_grouped_view(results, group_by)


def _print_list_view(results: List[Dict[str, Any]]):
    """列表视图打印"""
    from ChanAnalyzer.stock_pool import StockPool

    # 获取股票名称
    pool = StockPool()

    print(f"\n找到 {len(results)} 只符合条件的股票:")
    print("=" * 70)

    for stock in results:
        code = stock['code']
        info = pool.get_stock_info(code)
        name = info['name'] if info else ''
        print(f"\n股票: {code} {name}")
        if stock.get('current_price'):
            print(f"  当前价格: {stock['current_price']:.2f}")

        # 显示资金流向
        if stock.get('money_flow'):
            flow = stock['money_flow']
            if 'error' not in flow:
                net_main = flow.get('net_main_amount', 0)
                emoji = "📈" if net_main > 0 else "📉" if net_main < 0 else "➡"
                print(f"  主力资金: {net_main:+.2f} 万元 {emoji}")

        print("  买卖点信号:")
        for sig in stock['signals']:
            print(f"    - {sig['period']} {sig['direction']} {sig['type']}类: {sig['date']} @ {sig['price']:.2f}")


def _print_grouped_view(results: List[Dict[str, Any]], group_by: str):
    """分组视图打印"""
    from ChanAnalyzer.stock_pool import StockPool

    # 中文映射
    field_name_map = {'industry': '行业', 'area': '地区'}

    # 分组
    grouped = group_by_field(results, group_by)

    # 获取股票名称
    pool = StockPool()

    print(f"\n找到 {len(results)} 只符合条件的股票，按{field_name_map.get(group_by, group_by)}分组:")
    print("=" * 70)

    # 按每组股票数量排序
    sorted_groups = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)

    for group_name, stocks in sorted_groups:
        print(f"\n【{group_name}】({len(stocks)} 只)")
        print("-" * 50)
        for stock in stocks[:10]:  # 每组最多显示10只
            code = stock['code']
            info = pool.get_stock_info(code)
            name = info['name'] if info else ''
            signals_str = ", ".join([f"{s['type']}类" for s in stock['signals']])
            print(f"  {code} {name}: {signals_str}")
        if len(stocks) > 10:
            print(f"  ... 还有 {len(stocks) - 10} 只")

    # 打印统计摘要
    _print_group_summary(grouped, group_by)


def _print_group_summary(grouped: Dict[str, List[Dict]], group_by: str):
    """打印分组统计摘要"""
    from collections import Counter

    print(f"\n{'行业' if group_by == 'industry' else '地区'}信号统计:")
    print("-" * 50)

    summary = []
    for group_name, stocks in grouped.items():
        buy_signals = []
        sell_signals = []
        for stock in stocks:
            for sig in stock['signals']:
                if sig['direction'] == '买入':
                    buy_signals.append(sig['type'])
                else:
                    sell_signals.append(sig['type'])

        summary.append({
            'name': group_name,
            'buy_count': len(buy_signals),
            'sell_count': len(sell_signals),
            'stock_count': len(stocks)
        })

    # 按买入信号数量排序
    summary.sort(key=lambda x: x['buy_count'], reverse=True)

    for item in summary[:15]:  # 最多显示15个
        print(f"  {item['name']}: 买入 {item['buy_count']} 次, 卖出 {item['sell_count']} 次 ({item['stock_count']} 只)")


def save_results(results: List[Dict[str, Any]], filename: str = "scan_results.txt", group_by: str = 'none'):
    """保存扫描结果到文件

    Args:
        results: 扫描结果列表
        filename: 输出文件名
        group_by: 分组方式 ('industry', 'area', 'none')
    """
    from ChanAnalyzer.stock_pool import StockPool

    pool = StockPool()

    with open(filename, 'w', encoding='utf-8') as f:
        field_name_map = {'industry': '行业', 'area': '地区'}

        if group_by == 'none':
            f.write(f"缠论买卖点扫描结果 - 共 {len(results)} 只股票\n")
        else:
            f.write(f"缠论买卖点扫描结果 - 共 {len(results)} 只股票 (按{field_name_map.get(group_by, group_by)}分组)\n")
        f.write("=" * 70 + "\n\n")

        if group_by == 'none':
            # 列表格式保存
            for stock in results:
                code = stock['code']
                info = pool.get_stock_info(code)
                name = info['name'] if info else ''
                f.write(f"股票: {code} {name}\n")
                if stock.get('current_price'):
                    f.write(f"当前价格: {stock['current_price']:.2f}\n")
                f.write("买卖点信号:\n")
                for sig in stock['signals']:
                    f.write(f"  - {sig['period']} {sig['direction']} {sig['type']}类: {sig['date']} @ {sig['price']:.2f}\n")
                f.write("\n")
        else:
            # 分组格式保存
            grouped = group_by_field(results, group_by)
            sorted_groups = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)

            for group_name, stocks in sorted_groups:
                f.write(f"【{group_name}】({len(stocks)} 只)\n")
                f.write("-" * 50 + "\n")
                for stock in stocks:
                    code = stock['code']
                    info = pool.get_stock_info(code)
                    name = info['name'] if info else ''
                    signals_str = ", ".join([f"{s['type']}类" for s in stock['signals']])
                    f.write(f"  {code} {name}: {signals_str}\n")
                f.write("\n")

    print(f"结果已保存到: {filename}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='缠论买卖点扫描器')
    parser.add_argument('--codes', nargs='+', help='指定股票代码，如: 000001 000002')
    parser.add_argument('--buy', nargs='+', default=['2', '3a', '3b'],
                       help='筛选买入类型 (默认: 2 3a 3b)')
    parser.add_argument('--sell', nargs='+', default=['2s', '3a', '3b'],
                       help='筛选卖出类型 (默认: 2s 3a 3b)')
    parser.add_argument('--begin', help='开始日期，如: 2024-01-01')
    parser.add_argument('--limit', type=int, help='限制扫描数量')
    parser.add_argument('--output', help='保存结果到文件')
    parser.add_argument('--refresh', action='store_true', help='强制刷新股票列表缓存')
    parser.add_argument('--delay', type=float, default=0,
                       help='每只股票之间的延迟秒数（默认0，有缓存时无需延迟；首次扫描建议0.3）')
    parser.add_argument('--group-by', choices=['industry', 'area', 'none'], default='none',
                       help='按行业/地区分组显示结果 (默认: none)')

    # 股票池筛选参数
    parser.add_argument('--industry', nargs='+', help='按行业筛选，如: 电子 半导体')
    parser.add_argument('--area', nargs='+', help='按地区筛选，如: 深圳 上海')
    parser.add_argument('--exclude-st', action='store_true', help='排除ST股票')
    parser.add_argument('--market', nargs='+', help='按市场筛选，如: 主板 创业板 科创板')
    parser.add_argument('--list-industries', action='store_true', help='列出所有行业及其股票数量')
    parser.add_argument('--show-flow', action='store_true', help='显示板块资金流向')
    parser.add_argument('--show-money-flow', action='store_true', help='显示个股资金流向')
    parser.add_argument('--sort-by-money-flow', action='store_true', help='按主力净流入排序结果')
    parser.add_argument('--min-money-flow', type=float, default=0, help='最小主力净流入金额（万元）')

    args = parser.parse_args()

    # 处理 --list-industries 参数
    if args.list_industries:
        pool = StockPool(force_refresh=args.refresh)
        pool.list_industries()
        return

    # 处理 --show-flow 参数
    if args.show_flow:
        print_sector_flow(days=5, top_n=15)
        return

    # 获取股票列表
    if args.codes:
        # 直接指定股票代码
        stock_codes = args.codes
        print(f"指定股票: {len(stock_codes)} 只")
    else:
        # 使用 StockPool 筛选
        pool = StockPool(force_refresh=args.refresh)

        # 应用筛选条件
        if args.industry:
            print(f"筛选行业: {', '.join(args.industry)}")
            pool = pool.filter_by_industry(args.industry)

        if args.area:
            print(f"筛选地区: {', '.join(args.area)}")
            pool = pool.filter_by_area(args.area)

        if args.exclude_st:
            print("排除ST股票")
            pool = pool.exclude_st()

        if args.market:
            print(f"筛选市场: {', '.join(args.market)}")
            pool = pool.filter_by_market(args.market)

        stock_codes = pool.get_stock_list()
        print(f"筛选后股票: {len(stock_codes)} 只")

        # 如果有 --limit 参数，限制数量
        if args.limit:
            stock_codes = stock_codes[:args.limit]
            print(f"限制扫描数量: {len(stock_codes)}")

    # 单独处理 --limit（当使用 --codes 时）
    if args.codes and args.limit:
        stock_codes = stock_codes[:args.limit]
        print(f"限制扫描数量: {len(stock_codes)}")

    # 开始扫描
    print(f"\n开始扫描...")
    print(f"筛选买入类型: {args.buy}")
    print(f"筛选卖出类型: {args.sell}")

    results = scan_stocks(
        stock_codes=stock_codes,
        buy_types=args.buy,
        sell_types=args.sell,
        begin_date=args.begin,
        delay=args.delay,
        show_money_flow=args.show_money_flow,
        sort_by_money_flow=args.sort_by_money_flow,
        min_money_flow=args.min_money_flow,
    )

    # 打印结果
    print_results(results, group_by=args.group_by)

    # 保存结果
    if args.output or results:
        output_file = args.output or "scan_results.txt"
        save_results(results, output_file, group_by=args.group_by)


if __name__ == "__main__":
    main()
