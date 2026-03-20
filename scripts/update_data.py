"""
K线数据更新脚本

用于定时更新本地缓存的 K 线数据。

使用方法:
    # 更新指定股票
    python -m scripts.update_data --codes 000001 000002

    # 更新所有已缓存的股票
    python -m scripts.update_data --all

    # 更新特定周期
    python -m scripts.update_data --codes 000001 --kl-types DAY WEEK

    # 清除缓存后重新获取
    python -m scripts.update_data --codes 000001 --refresh
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import List

# ==================== 修复 tushare 权限问题 ====================
# 强制使用 /tmp 目录存储 token，避免云服务器权限问题
os.environ['TUSHARE_PATH'] = '/tmp'

# Monkey patch tushare，在导入时立即生效
import pandas as pd
import tushare as ts

# 保存原始函数
_original_set_token = ts.set_token
_original_pro_api = ts.pro_api

def _patched_set_token(token):
    """修复后的 set_token，使用 /tmp 目录"""
    fp = '/tmp/tk.csv'
    # 先删除旧文件避免权限冲突
    if os.path.exists(fp):
        try:
            os.remove(fp)
        except:
            pass
    df = pd.DataFrame({'token': [token]})
    df.to_csv(fp, index=False)
    ts._Tushare__token = token

def _patched_pro_api(token=None):
    """修复后的 pro_api，从 /tmp 读取 token"""
    if token:
        return _original_pro_api(token=token)
    fp = '/tmp/tk.csv'
    if os.path.exists(fp):
        df = pd.read_csv(fp)
        token = df['token'][0]
        return _original_pro_api(token=token)
    return _original_pro_api()

# 应用 patch
ts.set_token = _patched_set_token
ts.pro_api = _patched_pro_api
# ==================== 修复结束 ====================

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = lambda x, **kwargs: x

import time

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Common.CEnum import KL_TYPE
from ChanAnalyzer.database import get_db, init_db, KLineData, get_kl_type_str
from ChanAnalyzer.data_manager import DataManager
from DataAPI.TushareAPI import CTushareAPI

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _log(msg):
    """日志输出（兼容 tqdm）"""
    if HAS_TQDM:
        tqdm.write(msg)
    else:
        logger.info(msg)


def update_stock(
    code: str,
    kl_types: List[KL_TYPE],
    data_manager: DataManager,
    refresh: bool = False,
    verbose: bool = False
) -> dict:
    """
    更新单只股票的数据

    Returns:
        更新结果统计
    """
    result = {
        "code": code,
        "success": True,
        "kl_types": {},
        "error": None
    }

    for kl_type in kl_types:
        kl_type_str = get_kl_type_str(kl_type)

        try:
            # 清除缓存（如果需要）
            if refresh and verbose:
                _log(f"[{code} {kl_type_str}] 清除旧缓存...")
                data_manager.clear_cache(code, kl_type)
            elif refresh:
                data_manager.clear_cache(code, kl_type)

            # 获取昨天到今天的数据（增量更新）
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

            # 创建数据源获取函数
            def fetcher(code, kl_type, begin, end):
                api = CTushareAPI(
                    code=code,
                    k_type=kl_type,
                    begin_date=begin,
                    end_date=end,
                    autype=None  # 不复权
                )
                return api.get_kl_data()

            if verbose:
                _log(f"[{code} {kl_type_str}] 开始更新...")

            data_manager.get_kl_data(
                code=code,
                kl_type=kl_type,
                begin_date=start_date,
                end_date=end_date,
                data_src_fetcher=fetcher
            )

            # 获取缓存信息
            info = data_manager.get_cache_info(code, kl_type)
            result["kl_types"][kl_type_str] = {
                "count": info.get("count", 0),
                "first_date": info.get("first_date"),
                "last_date": info.get("last_date"),
            }
            logger.info(f"[{code} {kl_type_str}] 更新成功: {info.get('count', 0)} 条")

        except Exception as e:
            logger.error(f"[{code} {kl_type_str}] 更新失败: {e}")
            result["kl_types"][kl_type_str] = {"error": str(e)}
            result["success"] = False

    return result


def get_all_cached_stocks() -> List[str]:
    """获取所有已缓存的股票代码"""
    with get_db() as db:
        codes = db.query(KLineData.code).distinct().all()
        return [c[0] for c in codes]


def update_all_stocks(
    kl_types: List[KL_TYPE],
    data_manager: DataManager,
    refresh: bool = False
):
    """更新所有已缓存的股票"""
    codes = get_all_cached_stocks()

    if not codes:
        logger.warning("没有已缓存的股票，请先使用 --codes 指定股票代码")
        return

    logger.info(f"开始更新 {len(codes)} 只股票...")

    success_count = 0
    fail_count = 0

    # 使用进度条
    iterator = codes
    if HAS_TQDM:
        iterator = tqdm(codes, desc="更新进度", unit="股")

    for code in iterator:
        result = update_stock(code, kl_types, data_manager, refresh)

        if result["success"]:
            success_count += 1
        else:
            fail_count += 1

        # API 频率限制：每只股票之间延迟 0.2 秒
        # 这样每分钟最多约 300 次请求，低于 Tushare 的 500 次限制
        time.sleep(0.2)

    logger.info(f"\n更新完成: 成功 {success_count}, 失败 {fail_count}")


def main():
    parser = argparse.ArgumentParser(description="K线数据更新脚本")

    parser.add_argument(
        '--codes',
        nargs='+',
        help='指定股票代码，如: 000001 000002'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='更新所有已缓存的股票'
    )
    parser.add_argument(
        '--kl-types',
        nargs='+',
        default=['DAY', 'WEEK'],
        choices=['DAY', 'WEEK', 'MON', '30M', '15M', '5M', '1M'],
        help='K线周期类型 (默认: DAY WEEK)'
    )
    parser.add_argument(
        '--refresh',
        action='store_true',
        help='清除缓存后重新获取'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='显示详细日志'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 初始化数据库
    init_db()

    # 创建 DataManager 实例
    data_manager = DataManager()

    # 解析周期类型
    kl_type_map = {
        '1M': KL_TYPE.K_1M,
        '5M': KL_TYPE.K_5M,
        '15M': KL_TYPE.K_15M,
        '30M': KL_TYPE.K_30M,
        'DAY': KL_TYPE.K_DAY,
        'WEEK': KL_TYPE.K_WEEK,
        'MON': KL_TYPE.K_MON,
    }
    kl_types = [kl_type_map[t] for t in args.kl_types]

    # 执行更新
    if args.all:
        update_all_stocks(kl_types, data_manager, args.refresh)
    elif args.codes:
        for code in args.codes:
            result = update_stock(code, kl_types, data_manager, args.refresh)
            print(f"\n{code} 更新结果:")
            for kl_type_str, info in result["kl_types"].items():
                if "error" in info:
                    print(f"  {kl_type_str}: 失败 - {info['error']}")
                else:
                    print(f"  {kl_type_str}: {info['count']} 条 ({info['first_date']} ~ {info['last_date']})")
    else:
        parser.print_help()
        print("\n提示: 使用 --codes 指定股票，或 --all 更新所有已缓存股票")


if __name__ == "__main__":
    main()
