"""
ChanAnalyzer - 缠论分析模块

基于本地缓存数据库的缠论分析工具，输出笔、线段、中枢、买卖点等分析结果。

仅支持日线分析

使用示例:
    >>> from ChanAnalyzer import ChanAnalyzer
    >>>
    >>> analyzer = ChanAnalyzer(code="000001")
    >>> summary = analyzer.get_summary()
    >>> print(summary)
"""
from ChanAnalyzer.analyzer import ChanAnalyzer
from ChanAnalyzer.ai_analyzer import AIAnalyzer
from ChanAnalyzer.multi_ai_analyzer import MultiAIAnalyzer, analyze_with_multi_ai, AnalystOpinion, MultiAIResult
from ChanAnalyzer.database import init_db, get_db, KLineData
from ChanAnalyzer.data_manager import DataManager, get_data_manager, data_manager
from ChanAnalyzer.stock_info import get_stock_industry, get_industry_stats, get_area_stats, group_by_field
from ChanAnalyzer.stock_pool import StockPool
from ChanAnalyzer.sector_flow import (
    get_sector_flow,
)
from ChanAnalyzer.sector_flow import (
    get_hot_sectors,
    get_cold_sectors,
    filter_stocks_by_flow,
    print_sector_flow,
    get_stock_money_flow,
    print_stock_money_flow,
    filter_stocks_by_money_flow,
)

__version__ = "2.3.0"
__all__ = [
    "ChanAnalyzer",
    "AIAnalyzer",
    "MultiAIAnalyzer",
    "analyze_with_multi_ai",
    "AnalystOpinion",
    "MultiAIResult",
    "DataManager",
    "get_data_manager",
    "data_manager",
    "init_db",
    "get_db",
    "KLineData",
    "get_stock_industry",
    "get_industry_stats",
    "get_area_stats",
    "group_by_field",
    "StockPool",
    "get_sector_flow",
]
