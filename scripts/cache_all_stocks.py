"""
批量缓存所有 A 股 K 线数据

用法:
    # 缓存指定股票
    python -m scripts.cache_all_stocks --codes 000001 000002

    # 缓存所有 A 股
    python -m scripts.cache_all_stocks --all

    # 限制数量（测试用）
    python -m scripts.cache_all_stocks --all --limit 100
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from typing import List

# ==================== 修复 tushare 权限问题 ====================
os.environ['TUSHARE_PATH'] = '/tmp'

import pandas as pd
import tushare as ts

_original_set_token = ts.set_token
_original_pro_api = ts.pro_api

def _patched_set_token(token):
    fp = '/tmp/tk.csv'
    if os.path.exists(fp):
        try:
            os.remove(fp)
        except:
            pass
    df = pd.DataFrame({'token': [token]})
    df.to_csv(fp, index=False)
    ts._Tushare__token = token

def _patched_pro_api(token=None):
    if token:
        return _original_pro_api(token=token)
    fp = '/tmp/tk.csv'
    if os.path.exists(fp):
        df = pd.read_csv(fp)
        token = df['token'][0]
        return _original_pro_api(token=token)
    return _original_pro_api()

ts.set_token = _patched_set_token
ts.pro_api = _patched_pro_api
# ==================== 修复结束 ====================

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = lambda x, **kwargs: x

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Common.CEnum import KL_TYPE
from ChanAnalyzer.database import init_db
from ChanAnalyzer.data_manager import data_manager
from DataAPI.TushareAPI import CTushareAPI


def cache_stock(code: str, kl_types: List[KL_TYPE], begin_date: str, end_date: str) -> bool:
    """缓存单只股票数据"""
    success = True
    for kl_type in kl_types:
        try:
            def fetcher(code, kl_type, begin, end):
                api = CTushareAPI(
                    code=code,
                    k_type=kl_type,
                    begin_date=begin,
                    end_date=end,
                    autype=None
                )
                return api.get_kl_data()

            list(data_manager.get_kl_data(
                code=code,
                kl_type=kl_type,
                begin_date=begin_date,
                end_date=end_date,
                data_src_fetcher=fetcher
            ))
        except Exception as e:
            print(f"[失败] {code}: {e}")
            success = False
    return success


def cache_all_stocks(stock_codes: List[str], kl_types: List[KL_TYPE], begin_date: str, end_date: str, delay: float = 0):
    """批量缓存股票数据"""
    print(f"开始缓存 {len(stock_codes)} 只股票...")
    print(f"周期: {[t.name for t in kl_types]}")
    print(f"时间范围: {begin_date} ~ {end_date}")
    print()

    success_count = 0
    fail_count = 0

    iterator = stock_codes
    if HAS_TQDM:
        iterator = tqdm(stock_codes, desc="缓存进度", unit="股")

    for code in iterator:
        if cache_stock(code, kl_types, begin_date, end_date):
            success_count += 1
        else:
            fail_count += 1
        # 延迟以避免触发 API 频次限制
        if delay > 0:
            time.sleep(delay)

    print(f"\n缓存完成: 成功 {success_count}, 失败 {fail_count}")


def get_all_stock_codes() -> List[str]:
    """获取所有 A 股代码"""
    import tushare as ts
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise ValueError("请设置 TUSHARE_TOKEN 环境变量")
    ts.set_token(token)
    pro = ts.pro_api()

    df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
    df = df[(df['ts_code'].str.endswith('.SZ')) | (df['ts_code'].str.endswith('.SH'))]
    df = df[~df['name'].str.contains('ST')]

    return df['symbol'].tolist()


def main():
    parser = argparse.ArgumentParser(description='批量缓存 A 股 K 线数据')
    parser.add_argument('--codes', nargs='+', help='指定股票代码')
    parser.add_argument('--all', action='store_true', help='缓存所有 A 股')
    parser.add_argument('--limit', type=int, help='限制数量')
    parser.add_argument('--begin', default='2023-01-01', help='开始日期')
    parser.add_argument('--end', default=None, help='结束日期（默认今天）')
    parser.add_argument('--delay', type=float, default=0.3, help='每只股票之间的延迟秒数（默认0.3秒，避免触发频次限制）')
    parser.add_argument('--kl-types', nargs='+', default=['DAY', 'WEEK'],
                       choices=['DAY', 'WEEK', 'MON'],
                       help='K线周期类型 (默认: DAY WEEK，只选日线请用 --kl-types DAY)')

    args = parser.parse_args()

    # 初始化数据库
    init_db()

    # 解析周期类型
    kl_type_map = {
        'DAY': KL_TYPE.K_DAY,
        'WEEK': KL_TYPE.K_WEEK,
        'MON': KL_TYPE.K_MON,
    }
    kl_types = [kl_type_map[t] for t in args.kl_types]

    # 结束日期
    end_date = args.end or datetime.now().strftime("%Y-%m-%d")

    # 获取股票列表
    if args.codes:
        stock_codes = args.codes
    elif args.all:
        print("正在获取 A 股列表...")
        stock_codes = get_all_stock_codes()
        print(f"共 {len(stock_codes)} 只股票")
    else:
        parser.print_help()
        return

    # 限制数量
    if args.limit:
        stock_codes = stock_codes[:args.limit]
        print(f"限制数量: {len(stock_codes)}")

    # 开始缓存
    if args.delay > 0:
        print(f"请求延迟: {args.delay} 秒/股")
    cache_all_stocks(stock_codes, kl_types, args.begin, end_date, args.delay)


if __name__ == "__main__":
    main()
