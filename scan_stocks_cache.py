"""
缠论买点扫描器 - 混合数据源版

数据来源:
    - K线数据: 本地 chan.db (快速、离线)
    - 股票列表: 本地 chan.db (快速、离线)
    - 资金流向: Tushare API (可选)
    - 行业/地区: Tushare API (可选)

使用方法:
    # 扫描所有股票，筛选二买、三买
    python scan_stocks_cache.py

    # 扫描指定股票
    python scan_stocks_cache.py --codes 000001 000002 600000

    # 按行业筛选
    python scan_stocks_cache.py --industry 电子 计算机

    # 按地区筛选
    python scan_stocks_cache.py --area 深圳 上海

    # 显示资金流向
    python scan_stocks_cache.py --show-money-flow --sort-by-money-flow

    # 保存结果
    python scan_stocks_cache.py --output results.txt
"""
import os
import sys
import argparse
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = lambda x, **kwargs: x

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE


# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), "chan.db")

# 移除缓存，直接从数据库查询


def _get_tushare_token():
    """获取 Tushare Token"""
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        # 尝试从 .env 文件读取
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        if key.strip() == 'TUSHARE_TOKEN':
                            token = value.strip()
                            break
    return token


def get_stock_list_from_db(
    exclude_bj: bool = True,
    exclude_b_share: bool = True,
    exclude_cdr: bool = True,
) -> List[str]:
    """
    从本地数据库获取股票代码列表

    Args:
        exclude_bj: 是否排除北交所（8xx, 43x）
        exclude_b_share: 是否排除B股（200, 900）
        exclude_cdr: 是否排除CDR（920）

    Returns:
        股票代码列表
    """
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"数据库文件不存在: {DB_PATH}\n"
            f"请先运行数据缓存脚本创建数据库。"
        )

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 获取所有股票代码
        cursor.execute("""
            SELECT DISTINCT code
            FROM kline_data
            WHERE kl_type = 'DAY'
            ORDER BY code
        """)
        rows = cursor.fetchall()
        conn.close()

        stock_list = []
        for (code,) in rows:
            # 过滤条件
            if exclude_bj and (code.startswith('8') or code.startswith('43')):
                continue
            if exclude_b_share and (code.startswith('200') or code.startswith('900')):
                continue
            if exclude_cdr and code.startswith('920'):
                continue

            stock_list.append(code)

        return stock_list

    except Exception as e:
        raise RuntimeError(f"从数据库获取股票列表失败: {e}")


def get_stock_info_bulk(stock_codes: List[str]) -> Dict[str, Dict[str, str]]:
    """
    批量获取股票信息（名称、行业、地区）

    直接从本地数据库 stock_info 表读取。

    Args:
        stock_codes: 股票代码列表

    Returns:
        {code: {'name': xxx, 'industry': xxx, 'area': xxx}, ...}
    """
    result = {}
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 构建查询条件
        placeholders = ','.join('?' * len(stock_codes))
        query = f'''
            SELECT code, name, industry, area
            FROM stock_info
            WHERE code IN ({placeholders})
        '''
        cursor.execute(query, stock_codes)
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            result[row[0]] = {
                'name': row[1],
                'industry': row[2] if row[2] else '',
                'area': row[3] if row[3] else ''
            }

    except Exception as e:
        print(f"从数据库读取股票信息失败: {e}")

    # 对于数据库中没有的股票，使用股票代码作为默认名称
    for code in stock_codes:
        if code not in result:
            result[code] = {'name': code, 'industry': '', 'area': ''}

    return result


def get_latest_price_from_db(code: str) -> Dict[str, Any]:
    """从数据库获取股票最新价格信息"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 获取最新两根K线，用于计算涨跌幅
        cursor.execute("""
            SELECT date, close
            FROM kline_data
            WHERE code = ? AND kl_type = 'DAY'
            ORDER BY date DESC
            LIMIT 2
        """, (code,))
        rows = cursor.fetchall()
        conn.close()

        if len(rows) == 0:
            return None

        latest_close = float(rows[0][1])
        change_pct = 0.0
        if len(rows) >= 2:
            prev_close = float(rows[1][1])
            change_pct = ((latest_close - prev_close) / prev_close) * 100 if prev_close > 0 else 0

        return {
            'code': code,
            'latest_price': latest_close,
            'change_pct': change_pct,
            'latest_date': rows[0][0],
        }

    except Exception as e:
        return None


def get_stock_money_flow(code: str, days: int = 5) -> Dict[str, Any]:
    """
    获取个股资金流向

    Args:
        code: 股票代码（6位数字）
        days: 统计天数

    Returns:
        资金流向数据字典
    """
    token = _get_tushare_token()
    if not token:
        return {'error': '未设置 TUSHARE_TOKEN'}

    try:
        import tushare as ts
        # 直接传入token，避免写入缓存文件导致权限问题
        pro = ts.pro_api(token)

        # 转换代码格式
        if code.startswith('6'):
            ts_code = f"{code}.SH"
        else:
            ts_code = f"{code}.SZ"

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

        df = pro.moneyflow(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date
        )

        if df is None or df.empty:
            return {'error': '无数据'}

        # 取最近 days 天的数据汇总
        df = df.head(days)

        result = {
            'code': code,
            'days': days,
            'net_amount': df['net_mf_vol'].sum() / 10000,  # 转换为万元
            'net_main_amount': (df['buy_elg_vol'].sum() + df['buy_lg_vol'].sum() -
                                df['sell_elg_vol'].sum() - df['sell_lg_vol'].sum()) / 10000,
        }

        return result

    except Exception as e:
        return {'error': str(e)}


def filter_stocks_by_industry(stock_codes: List[str], industries: List[str]) -> List[str]:
    """按行业筛选股票"""
    stock_info = get_stock_info_bulk(stock_codes)
    if not stock_info:
        return stock_codes  # 无信息时返回全部

    result = []
    industries_lower = [ind.lower() for ind in industries]

    for code in stock_codes:
        info = stock_info.get(code, {})
        stock_industry = info.get('industry', '').lower()

        for ind in industries_lower:
            if ind in stock_industry:
                result.append(code)
                break

    return result


def filter_stocks_by_area(stock_codes: List[str], areas: List[str]) -> List[str]:
    """按地区筛选股票"""
    stock_info = get_stock_info_bulk(stock_codes)
    if not stock_info:
        return stock_codes

    result = []
    areas_lower = [area.lower() for area in areas]

    for code in stock_codes:
        info = stock_info.get(code, {})
        stock_area = info.get('area', '').lower()

        for area in areas_lower:
            if area in stock_area:
                result.append(code)
                break

    return result


def exclude_st_stocks(stock_codes: List[str]) -> List[str]:
    """排除ST股票"""
    token = _get_tushare_token()
    if not token:
        return stock_codes  # 无token时返回全部

    try:
        import tushare as ts
        # 直接传入token，避免写入缓存文件导致权限问题
        pro = ts.pro_api(token)

        # 转换代码格式
        ts_codes = []
        for code in stock_codes:
            if code.startswith('6'):
                ts_codes.append(f"{code}.SH")
            else:
                ts_codes.append(f"{code}.SZ")

        df = pro.stock_basic(
            ts_code=','.join(ts_codes),
            fields='ts_code,name'
        )

        if df is None or df.empty:
            return stock_codes

        # 过滤ST股票
        st_codes = set()
        for _, row in df.iterrows():
            if 'ST' in row['name']:
                ts_code = row['ts_code']
                orig_code = ts_code.split('.')[0]
                st_codes.add(orig_code)

        return [code for code in stock_codes if code not in st_codes]

    except Exception as e:
        print(f"排除ST股票失败: {e}")
        return stock_codes


def analyze_stock(
    code: str,
    buy_types: List[str],
    sell_types: List[str],
    begin_date: str = None,
    end_date: str = None,
    use_weekly: bool = False,
    config: CChanConfig = None,
) -> Optional[Dict[str, Any]]:
    """
    分析单只股票的买卖点

    使用本地数据库进行缠论分析
    """
    try:
        # 设置默认日期范围
        if begin_date is None:
            begin_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        # 设置K线级别
        if use_weekly:
            lv_list = [KL_TYPE.K_DAY, KL_TYPE.K_WEEK]
        else:
            lv_list = [KL_TYPE.K_DAY]

        # 创建缠论分析对象
        chan = CChan(
            code=code,
            begin_time=begin_date,
            end_time=end_date,
            data_src=DATA_SRC.CACHE_DB,
            lv_list=lv_list,
            config=config,
            autype=AUTYPE.QFQ,
        )

        # 检查是否有数据
        if len(chan[0]) == 0:
            return None

        # 获取买卖点
        bsp_list = chan.get_latest_bsp(number=0)

        # 筛选最近的买卖点（最近30天）
        cutoff_date = datetime.now() - timedelta(days=30)
        matched_signals = []

        for bsp in bsp_list:
            bsp_date = datetime(bsp.klu.time.year, bsp.klu.time.month, bsp.klu.time.day)
            if bsp_date < cutoff_date:
                continue

            bsp_type = bsp.type2str()

            # 直接根据类型判断，不依赖 is_buy 属性（因为 is_buy 有时与 type 不一致）
            # 买入类型: 1, 1p, 2, 3a, 3b
            # 卖出类型: 1s, 2s, 3a, 3b（注意：卖出也有3a/3b）
            if bsp_type in buy_types:
                matched_signals.append({
                    'type': bsp_type,
                    'direction': '买入',
                    'date': str(bsp.klu.time),
                    'price': float(bsp.klu.close),
                    'period': '周线' if use_weekly else '日线',
                })
            elif bsp_type in sell_types:
                matched_signals.append({
                    'type': bsp_type,
                    'direction': '卖出',
                    'date': str(bsp.klu.time),
                    'price': float(bsp.klu.close),
                    'period': '周线' if use_weekly else '日线',
                })

        if not matched_signals:
            return None

        # 获取最新价格信息
        price_info = get_latest_price_from_db(code)

        return {
            'code': code,
            'signals': matched_signals,
            'latest_price': price_info['latest_price'] if price_info else None,
            'change_pct': price_info['change_pct'] if price_info else None,
        }

    except Exception:
        return None


def scan_stocks(
    stock_codes: List[str],
    buy_types: List[str] = None,
    sell_types: List[str] = None,
    begin_date: str = None,
    end_date: str = None,
    use_weekly: bool = False,
    bi_strict: bool = True,
    show_money_flow: bool = False,
    sort_by_money_flow: bool = False,
    min_money_flow: float = 0,
    verbose: bool = True,
    progress_callback: callable = None,
    # 新增筛选参数
    industries: List[str] = None,
    areas: List[str] = None,
    exclude_st: bool = True,
    exclude_suspend: bool = True,
) -> List[Dict[str, Any]]:
    """
    扫描股票列表

    Args:
        stock_codes: 股票代码列表
        buy_types: 买点类型列表
        sell_types: 卖点类型列表
        begin_date: 开始日期
        end_date: 结束日期
        use_weekly: 是否使用周线
        bi_strict: 是否严格笔模式
        show_money_flow: 是否显示资金流向
        sort_by_money_flow: 是否按资金流向排序
        min_money_flow: 最小资金流向
        verbose: 是否显示进度条
        progress_callback: 进度回调函数，签名为 callback(current, total, found)
        industries: 行业筛选列表
        areas: 地区筛选列表
        exclude_st: 是否排除ST股票
        exclude_suspend: 是否排除停牌股票
    """
    if buy_types is None:
        buy_types = ['2', '3a', '3b']
    if sell_types is None:
        sell_types = []

    # 应用筛选条件
    filtered_codes = stock_codes
    if industries or areas or exclude_st or exclude_suspend:
        stock_info_dict = get_stock_info_bulk(stock_codes)

        if industries or areas or exclude_st:
            filtered_codes = []
            for code in stock_codes:
                info = stock_info_dict.get(code, {})
                # 行业筛选
                if industries and info.get('industry') not in industries:
                    continue
                # 地区筛选
                if areas and info.get('area') not in areas:
                    continue
                # 排除ST
                if exclude_st and 'ST' in info.get('name', ''):
                    continue
                filtered_codes.append(code)

        # 如果指定了 stock_codes 参数（个股模式），使用它而不是筛选后的列表
        # 这是为了支持先筛选再扫描的场景

    # 使用筛选后的股票列表
    stock_codes = filtered_codes

    # 配置缠论参数
    config = CChanConfig({
        "bi_strict": bi_strict,
        "trigger_step": False,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": "1,1p,2,2s,3a,3b",
        "print_warning": False,
        "zs_algo": "normal",
    })

    results = []
    total = len(stock_codes)

    # 创建进度条
    iterator = enumerate(stock_codes)
    if verbose and HAS_TQDM and not progress_callback:
        iterator = tqdm(enumerate(stock_codes), total=total, desc="扫描进度", unit="股")

    for i, code in iterator:
        result = analyze_stock(
            code=code,
            buy_types=buy_types,
            sell_types=sell_types,
            begin_date=begin_date,
            end_date=end_date,
            use_weekly=use_weekly,
            config=config,
        )

        if result:
            # 获取资金流向
            if show_money_flow or sort_by_money_flow or min_money_flow > 0:
                flow = get_stock_money_flow(code)
                result['money_flow'] = flow

            results.append(result)
            if verbose and HAS_TQDM:
                iterator.set_postfix_str(f"找到: {len(results)}")

        # 调用进度回调（每处理一只股票就调用）
        if progress_callback:
            progress_callback(i + 1, total, len(results))

    # 按资金流向筛选
    if min_money_flow > 0:
        results = [
            r for r in results
            if r.get('money_flow') and 'error' not in r['money_flow'] and
               r['money_flow'].get('net_main_amount', 0) >= min_money_flow
        ]

    # 按资金流向排序
    if sort_by_money_flow:
        results.sort(
            key=lambda x: x.get('money_flow', {}).get('net_main_amount', -999999),
            reverse=True
        )

    return results


def print_results(
    results: List[Dict[str, Any]],
    stock_info: Dict[str, Dict[str, str]] = None,
    group_by: str = 'none'
):
    """打印扫描结果"""
    if not results:
        print("\n未找到符合条件的股票")
        return

    if group_by == 'none':
        _print_list_view(results, stock_info)
    elif group_by == 'industry':
        _print_grouped_view(results, stock_info, 'industry')
    elif group_by == 'area':
        _print_grouped_view(results, stock_info, 'area')


def _print_list_view(results: List[Dict[str, Any]], stock_info: Dict[str, Dict[str, str]]):
    """列表视图打印"""
    print(f"\n找到 {len(results)} 只符合条件的股票:")
    print("=" * 70)

    for stock in results:
        code = stock['code']
        info = stock_info.get(code, {}) if stock_info else {}
        name = info.get('name', '')
        industry = info.get('industry', '')
        area = info.get('area', '')

        print(f"\n股票: {code} {name}", end="")
        if industry or area:
            print(f" ({industry} {area})".strip())
        else:
            print()

        if stock.get('latest_price'):
            print(f"  最新价格: {stock['latest_price']:.2f}", end="")
            if stock.get('change_pct') is not None:
                mark = "+" if stock['change_pct'] > 0 else "" if stock['change_pct'] == 0 else ""
                print(f"  ({stock['change_pct']:+.2f}%)")
            else:
                print()

        # 显示资金流向
        if stock.get('money_flow'):
            flow = stock['money_flow']
            if 'error' not in flow:
                net_main = flow.get('net_main_amount', 0)
                mark = "+" if net_main > 0 else "" if net_main == 0 else ""
                print(f"  主力资金: {net_main:+.2f} 万元")

        print("  买卖点信号:")
        for sig in stock['signals']:
            print(f"    - {sig['period']} {sig['direction']} {sig['type']}类: {sig['date']} @ {sig['price']:.2f}")


def _print_grouped_view(
    results: List[Dict[str, Any]],
    stock_info: Dict[str, Dict[str, str]],
    field: str
):
    """分组视图打印"""
    # 分组
    grouped = {}
    field_name_map = {'industry': '行业', 'area': '地区'}

    for stock in results:
        code = stock['code']
        info = stock_info.get(code, {})
        field_value = info.get(field, '未知')

        if field_value not in grouped:
            grouped[field_value] = []
        grouped[field_value].append(stock)

    # 按每组股票数量排序
    sorted_groups = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)

    print(f"\n找到 {len(results)} 只符合条件的股票，按{field_name_map.get(field, field)}分组:")
    print("=" * 70)

    for group_name, stocks in sorted_groups:
        print(f"\n【{group_name}】({len(stocks)} 只)")
        print("-" * 50)
        for stock in stocks[:10]:  # 每组最多显示10只
            code = stock['code']
            info = stock_info.get(code, {})
            name = info.get('name', '')
            signals_str = ", ".join([f"{s['type']}类" for s in stock['signals']])
            print(f"  {code} {name}: {signals_str}")
        if len(stocks) > 10:
            print(f"  ... 还有 {len(stocks) - 10} 只")


def save_results(
    results: List[Dict[str, Any]],
    filename: str = "scan_results.txt",
    stock_info: Dict[str, Dict[str, str]] = None
):
    """保存扫描结果到文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"缠论买卖点扫描结果 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"共找到 {len(results)} 只符合条件的股票\n")
        f.write("=" * 70 + "\n\n")

        for stock in results:
            code = stock['code']
            info = stock_info.get(code, {}) if stock_info else {}
            name = info.get('name', '')
            industry = info.get('industry', '')
            area = info.get('area', '')

            f.write(f"股票: {code} {name}\n")
            if industry or area:
                f.write(f"  行业/地区: {industry} {area}\n".strip() + "\n")

            if stock.get('latest_price'):
                f.write(f"  最新价格: {stock['latest_price']:.2f}")
                if stock.get('change_pct') is not None:
                    f.write(f"  ({stock['change_pct']:+.2f}%)")
                f.write("\n")

            if stock.get('money_flow'):
                flow = stock['money_flow']
                if 'error' not in flow:
                    f.write(f"  主力资金: {flow.get('net_main_amount', 0):+.2f} 万元\n")

            f.write("  买卖点信号:\n")
            for sig in stock['signals']:
                f.write(f"    - {sig['period']} {sig['direction']} {sig['type']}类: {sig['date']} @ {sig['price']:.2f}\n")
            f.write("\n")

    print(f"\n结果已保存到: {filename}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='缠论买点扫描器 - 混合数据源版',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                                    # 扫描所有股票
  %(prog)s --codes 000001 000002             # 扫描指定股票
  %(prog)s --buy 1 2 3a                      # 筛选一类、二类、三类a买点
  %(prog)s --industry 电子 计算机              # 按行业筛选
  %(prog)s --area 深圳 上海                   # 按地区筛选
  %(prog)s --show-money-flow                 # 显示资金流向
  %(prog)s --output results.txt              # 保存结果

买点类型说明:
  1    : 一类买点（底部背驰）
  1p   : 一类买点（指标背驰）
  2    : 二类买点
  2s   : 二类卖点
  3a   : 三类买点a（中枢在下）
  3b   : 三类买点b（中枢在上）
        """
    )

    # 基本参数
    parser.add_argument('--codes', nargs='+', help='指定股票代码')
    parser.add_argument('--buy', nargs='+', default=['2', '3a', '3b'],
                       help='筛选买入类型 (默认: 2 3a 3b)')
    parser.add_argument('--sell', nargs='+', default=[],
                       help='筛选卖出类型')
    parser.add_argument('--begin', help='开始日期')
    parser.add_argument('--end', help='结束日期')
    parser.add_argument('--weekly', action='store_true', help='使用周线分析')
    parser.add_argument('--no-strict', action='store_true', help='关闭笔严格模式')
    parser.add_argument('--output', help='保存结果到文件')

    # 筛选参数
    parser.add_argument('--industry', nargs='+', help='按行业筛选')
    parser.add_argument('--area', nargs='+', help='按地区筛选')
    parser.add_argument('--exclude-st', action='store_true', help='排除ST股票')
    parser.add_argument('--group-by', choices=['industry', 'area', 'none'], default='none',
                       help='分组显示结果')

    # 资金流向参数
    parser.add_argument('--show-money-flow', action='store_true',
                       help='显示个股资金流向')
    parser.add_argument('--sort-by-money-flow', action='store_true',
                       help='按主力净流入排序结果')
    parser.add_argument('--min-money-flow', type=float, default=0,
                       help='最小主力净流入金额（万元）')

    args = parser.parse_args()

    # 检查 Tushare Token
    if args.industry or args.area or args.exclude_st or args.show_money_flow:
        token = _get_tushare_token()
        if not token:
            print("警告: 未设置 TUSHARE_TOKEN，部分功能将不可用")
            print("  请设置环境变量 TUSHARE_TOKEN 或在 .env 文件中配置")
            if args.industry or args.area:
                print("  将忽略行业/地区筛选继续执行...")

    # 获取股票列表
    if args.codes:
        stock_codes = args.codes
        print(f"指定股票: {len(stock_codes)} 只")
    else:
        print("正在从数据库获取股票列表...")
        stock_codes = get_stock_list_from_db()
        print(f"获取到 {len(stock_codes)} 只股票")

    # 应用筛选条件
    if args.industry:
        print(f"筛选行业: {', '.join(args.industry)}")
        stock_codes = filter_stocks_by_industry(stock_codes, args.industry)
        print(f"筛选后: {len(stock_codes)} 只")

    if args.area:
        print(f"筛选地区: {', '.join(args.area)}")
        stock_codes = filter_stocks_by_area(stock_codes, args.area)
        print(f"筛选后: {len(stock_codes)} 只")

    if args.exclude_st:
        print("排除ST股票...")
        stock_codes = exclude_st_stocks(stock_codes)
        print(f"筛选后: {len(stock_codes)} 只")

    if len(stock_codes) == 0:
        print("\n没有可扫描的股票")
        return

    # 开始扫描
    print(f"\n开始扫描...")
    print(f"筛选买入类型: {args.buy}")
    if args.sell:
        print(f"筛选卖出类型: {args.sell}")
    print(f"周期: {'周线' if args.weekly else '日线'}")
    print(f"笔严格模式: {not args.no_strict}")

    results = scan_stocks(
        stock_codes=stock_codes,
        buy_types=args.buy,
        sell_types=args.sell,
        begin_date=args.begin,
        end_date=args.end,
        use_weekly=args.weekly,
        bi_strict=not args.no_strict,
        show_money_flow=args.show_money_flow,
        sort_by_money_flow=args.sort_by_money_flow,
        min_money_flow=args.min_money_flow,
    )

    # 获取股票信息（用于显示名称、行业、地区）
    stock_info = {}
    if results:
        result_codes = [r['code'] for r in results]
        stock_info = get_stock_info_bulk(result_codes)

    # 打印结果
    print_results(results, stock_info, args.group_by)

    # 保存结果
    if args.output or results:
        output_file = args.output or "scan_results.txt"
        save_results(results, output_file, stock_info)


if __name__ == "__main__":
    main()
