"""
股票池管理模块

支持按行业/地区筛选，提供链式调用接口
"""
import os
import json
from typing import List, Dict, Optional, Callable, Union
from datetime import datetime, timedelta
from pathlib import Path

# 缓存目录和文件
CACHE_DIR = Path.home() / ".chan" / "cache"
STOCK_INFO_CACHE = CACHE_DIR / "stock_info.json"

# 全局单例缓存
_stock_cache_singleton = None


class StockPool:
    """
    股票池管理类

    负责股票列表获取、缓存和筛选，支持链式调用。

    Examples:
        >>> pool = StockPool()
        >>> # 查看摘要
        >>> pool.print_summary()
        >>>
        >>> # 筛选电子行业股票
        >>> tech_stocks = pool.filter_by_industry('电子')
        >>> print(f"电子行业: {len(tech_stocks.get_stock_list())} 只")
        >>>
        >>> # 复合筛选
        >>> filtered = (pool
        ...     .filter_by_industry(['电子', '计算机'])
        ...     .filter_by_area('深圳')
        ...     .exclude_st()
        ...     .get_stock_list())
    """

    def __init__(self, force_refresh: bool = False):
        """
        初始化股票池

        Args:
            force_refresh: 是否强制刷新缓存
        """
        global _stock_cache_singleton

        # 使用单例模式，避免重复加载
        if not force_refresh and _stock_cache_singleton is not None:
            self._stocks = _stock_cache_singleton
            self._filtered_codes = None
            return

        self._stocks = {}  # {code: {info}}
        self._filtered_codes = None  # 筛选后的代码列表
        self._load_stock_info(force_refresh)

        # 更新单例缓存
        _stock_cache_singleton = self._stocks

    def _load_stock_info(self, force_refresh: bool = False):
        """加载股票基本信息"""
        # 检查缓存
        if not force_refresh and STOCK_INFO_CACHE.exists():
            try:
                with open(STOCK_INFO_CACHE, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                # 检查缓存是否过期（7天）
                cache_time = datetime.fromisoformat(cache['time'])
                if datetime.now() - cache_time < timedelta(days=7):
                    self._stocks = cache['stocks']
                    # 只在首次加载时打印
                    if _stock_cache_singleton is None:
                        print(f"从缓存加载股票信息: {len(self._stocks)} 只")
                    return
            except Exception as e:
                print(f"缓存加载失败: {e}")

        # 从 API 获取
        self._fetch_from_api()

    def _fetch_from_api(self):
        """从 Tushare API 获取股票信息"""
        import tushare as ts

        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise ValueError("请设置 TUSHARE_TOKEN 环境变量")

        ts.set_token(token)
        pro = ts.pro_api()

        try:
            df = pro.stock_basic(
                exchange='',
                list_status='L',
                fields='ts_code,symbol,name,area,industry,market,list_date'
            )

            # 只保留 A 股
            df = df[(df['ts_code'].str.endswith('.SZ')) | (df['ts_code'].str.endswith('.SH'))]

            # 构建股票信息字典
            for _, row in df.iterrows():
                self._stocks[row['symbol']] = {
                    'code': row['symbol'],
                    'name': row['name'],
                    'industry': row.get('industry', '未分类'),
                    'area': row.get('area', '未知'),
                    'market': row.get('market', ''),
                    'list_date': str(row.get('list_date', '')),
                }

            # 保存缓存
            self._save_cache()
            print(f"从 API 加载股票信息: {len(self._stocks)} 只")

        except Exception as e:
            raise RuntimeError(f"获取股票信息失败: {e}")

    def _save_cache(self):
        """保存缓存到文件"""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache = {
            'time': datetime.now().isoformat(),
            'stocks': self._stocks,
        }
        with open(STOCK_INFO_CACHE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)

    # ============ 筛选方法 ============

    def filter_by_industry(self, industries: Union[str, List[str]]) -> 'StockPool':
        """
        按行业筛选

        Args:
            industries: 行业名称或列表，支持模糊匹配

        Returns:
            返回新的 StockPool 实例（链式调用）

        Examples:
            >>> pool.filter_by_industry('电子')
            >>> pool.filter_by_industry(['电子', '半导体'])
        """
        if isinstance(industries, str):
            industries = [industries]

        codes = []
        for code, info in self._get_current_stocks().items():
            industry = info['industry']
            for ind in industries:
                if ind in industry:
                    codes.append(code)
                    break

        return self._create_filtered_pool(codes)

    def filter_by_area(self, areas: Union[str, List[str]]) -> 'StockPool':
        """
        按地区筛选

        Args:
            areas: 地区名称或列表

        Returns:
            返回新的 StockPool 实例（链式调用）

        Examples:
            >>> pool.filter_by_area('深圳')
            >>> pool.filter_by_area(['深圳', '上海'])
        """
        if isinstance(areas, str):
            areas = [areas]

        codes = []
        for code, info in self._get_current_stocks().items():
            if info['area'] in areas:
                codes.append(code)

        return self._create_filtered_pool(codes)

    def exclude_st(self) -> 'StockPool':
        """
        排除 ST 股票

        Returns:
            返回新的 StockPool 实例（链式调用）
        """
        codes = []
        for code, info in self._get_current_stocks().items():
            if 'ST' not in info['name'] and 'st' not in info['name']:
                codes.append(code)

        return self._create_filtered_pool(codes)

    def filter_by_market(self, markets: Union[str, List[str]]) -> 'StockPool':
        """
        按市场筛选

        Args:
            markets: 市场类型，如 '主板', '创业板', '科创板'

        Returns:
            返回新的 StockPool 实例（链式调用）
        """
        if isinstance(markets, str):
            markets = [markets]

        codes = []
        for code, info in self._get_current_stocks().items():
            if info['market'] in markets:
                codes.append(code)

        return self._create_filtered_pool(codes)

    def random_sample(self, n: int) -> 'StockPool':
        """
        随机采样指定数量的股票

        Args:
            n: 采样数量，n <= 0 时返回全部

        Returns:
            返回新的 StockPool 实例（链式调用）
        """
        import random

        codes = self.get_stock_list()
        if n <= 0 or n >= len(codes):
            return self._create_filtered_pool(codes)

        sampled = random.sample(codes, n)
        return self._create_filtered_pool(sampled)

    def filter_by_custom(self, func: Callable[[Dict], bool]) -> 'StockPool':
        """
        自定义筛选器

        Args:
            func: 筛选函数，接收股票信息字典，返回布尔值

        Returns:
            返回新的 StockPool 实例（链式调用）

        Examples:
            >>> # 筛选2020年后上市的股票
            >>> pool.filter_by_custom(lambda x: x['list_date'] > '20200101')
        """
        codes = []
        for code, info in self._get_current_stocks().items():
            if func(info):
                codes.append(code)

        return self._create_filtered_pool(codes)

    # ============ 查询方法 ============

    def get_stock_list(self) -> List[str]:
        """
        获取当前筛选后的股票代码列表

        Returns:
            股票代码列表
        """
        if self._filtered_codes is not None:
            return self._filtered_codes
        return list(self._stocks.keys())

    def get_stock_info(self, code: str) -> Optional[Dict]:
        """
        获取单只股票信息

        Args:
            code: 股票代码

        Returns:
            股票信息字典，如果不存在返回 None
        """
        return self._stocks.get(code)

    def get_all_info(self) -> Dict[str, Dict]:
        """
        获取所有股票信息

        Returns:
            {code: {info}} 字典
        """
        return self._stocks.copy()

    def get_industries(self) -> List[str]:
        """
        获取所有行业列表

        Returns:
            排序后的行业列表
        """
        industries = set()
        for info in self._stocks.values():
            industries.add(info['industry'])
        return sorted(list(industries))

    def get_areas(self) -> List[str]:
        """
        获取所有地区列表

        Returns:
            排序后的地区列表
        """
        areas = set()
        for info in self._stocks.values():
            areas.add(info['area'])
        return sorted(list(areas))

    def get_stats(self) -> Dict:
        """
        获取统计信息

        Returns:
            包含总数、行业数、行业分布的字典
        """
        industry_stats = {}
        area_stats = {}

        for info in self._stocks.values():
            ind = info['industry']
            area = info['area']
            industry_stats[ind] = industry_stats.get(ind, 0) + 1
            area_stats[area] = area_stats.get(area, 0) + 1

        return {
            'total': len(self._stocks),
            'industries': len(industry_stats),
            'areas': len(area_stats),
            'top_industries': sorted(industry_stats.items(), key=lambda x: x[1], reverse=True)[:10],
            'top_areas': sorted(area_stats.items(), key=lambda x: x[1], reverse=True)[:10],
        }

    def print_summary(self):
        """打印股票池摘要"""
        stats = self.get_stats()
        print(f"\n股票池摘要:")
        print(f"  总数: {stats['total']} 只")
        print(f"  行业: {stats['industries']} 个")
        print(f"  地区: {stats['areas']} 个")
        print(f"\n行业分布 (前10):")
        for ind, count in stats['top_industries']:
            print(f"    {ind}: {count} 只")
        print(f"\n地区分布 (前10):")
        for area, count in stats['top_areas']:
            print(f"    {area}: {count} 只")

    def list_industries(self):
        """列出所有行业及其股票数量"""
        industry_counts = {}
        for info in self._stocks.values():
            ind = info['industry']
            industry_counts[ind] = industry_counts.get(ind, 0) + 1

        print(f"\n行业列表 (共 {len(industry_counts)} 个):")
        print("=" * 50)
        for ind, count in sorted(industry_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {ind}: {count} 只")

    # ============ 内部方法 ============

    def _get_current_stocks(self) -> Dict:
        """获取当前筛选范围内的股票"""
        if self._filtered_codes is not None:
            return {code: self._stocks[code] for code in self._filtered_codes}
        return self._stocks

    def _create_filtered_pool(self, codes: List[str]) -> 'StockPool':
        """创建筛选后的新池子"""
        new_pool = StockPool.__new__(StockPool)
        new_pool._stocks = self._stocks  # 共享底层数据
        new_pool._filtered_codes = codes
        return new_pool

    def __len__(self) -> int:
        """返回当前筛选后的股票数量"""
        return len(self.get_stock_list())

    def __repr__(self) -> str:
        """字符串表示"""
        count = len(self.get_stock_list())
        return f"StockPool({count} 只股票)"
