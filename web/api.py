"""
ChanAnalyzer FastAPI 后端服务 - 真实数据版

提供仪表板数据接口，支持缠论买卖点扫描、市场概况等功能

使用 importlib 直接导入子模块，避免触发 ChanAnalyzer/__init__.py 的阻塞导入

多用户支持：
- 使用进程池绕过GIL，支持真正并发的扫描任务
- 用户会话隔离，每个用户的扫描结果独立存储
"""
import os
import sys

import json
import asyncio
import importlib
import multiprocessing
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from functools import lru_cache
from collections import defaultdict
import pandas as pd

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# 导入用户认证模块
from web.auth import (
    get_or_create_user,
    verify_token,
    create_session_token,
    get_user_cache_file,
    get_user_status_file,
    get_current_user,
    verify_credentials
)

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env 文件
env_path = PROJECT_ROOT / '.env'
load_dotenv(dotenv_path=env_path)

# ============ 延迟导入辅助函数 ============
# 使用 importlib 直接导入子模块，绕过包的 __init__.py

def import_stock_pool():
    """导入 StockPool 类（绕过 ChanAnalyzer/__init__.py）"""
    return importlib.import_module('ChanAnalyzer.stock_pool').StockPool

def import_chan_analyzer():
    """导入 ChanAnalyzer 类（绕过 ChanAnalyzer/__init__.py）"""
    return importlib.import_module('ChanAnalyzer.analyzer').ChanAnalyzer


def import_multi_ai_analyzer():
    """导入 MultiAIAnalyzer 类（绕过 ChanAnalyzer/__init__.py）"""
    return importlib.import_module('ChanAnalyzer.multi_ai_analyzer').MultiAIAnalyzer


def import_sector_flow():
    """导入 sector_flow 模块（绕过 ChanAnalyzer/__init__.py）"""
    return importlib.import_module('ChanAnalyzer.sector_flow')



# 导入扫描模块（复用已有逻辑）
import scan_stocks_cache

# ============ 应用初始化 ============
app = FastAPI(
    title="ChanAnalyzer API",
    description="A股缠论分析系统 - 后端接口",
    version="1.0.0"
)

# CORS 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    from fastapi.responses import FileResponse
    from fastapi.responses import RedirectResponse

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def login_page():
        """登录页面"""
        login_file = static_dir / "login.html"
        if login_file.exists():
            return FileResponse(login_file)
        return RedirectResponse(url="/static/index.html", status_code=302)

    @app.get("/app")
    async def app_page():
        """应用主页面"""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return RedirectResponse(url="/static/index.html", status_code=302)


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "time": datetime.now().isoformat(),
        "message": "API is running",
        "max_concurrent_scans": MAX_CONCURRENT_SCANS,
        "max_workers": MAX_SCAN_WORKERS
    }


@app.get("/api/ping")
async def ping():
    """简单的 ping 测试"""
    return {"pong": True}


# ============ 用户认证 API ============

@app.get("/api/auth/session")
async def get_session(authorization: str = Header(None)):
    """
    获取或创建用户会话

    返回用户的token和user_id
    """
    token = authorization.replace("Bearer ", "") if authorization and authorization.startswith("Bearer ") else authorization
    token, user_id = get_or_create_user(token)

    return {
        "token": token,
        "user_id": user_id,
        "expire_hours": 24
    }


@app.post("/api/auth/refresh")
async def refresh_session(authorization: str = Header(None)):
    """
    刷新用户会话
    """
    token = authorization.replace("Bearer ", "") if authorization and authorization.startswith("Bearer ") else authorization
    user_id = verify_token(token)

    if not user_id:
        # Token无效，创建新会话
        token, user_id = get_or_create_user(None)
    else:
        # Token有效，刷新它
        token, user_id = create_session_token(user_id)

    return {
        "token": token,
        "user_id": user_id,
        "expire_hours": 24
    }


@app.post("/api/auth/login")
async def login(request: Request):
    """
    用户登录验证

    请求体:
        username: 用户名
        password: 密码

    返回:
        token: 会话令牌
        user_id: 用户ID
        expire_hours: 过期时间（小时）
    """
    data = await request.json()
    username = data.get('username', '')
    password = data.get('password', '')

    if not verify_credentials(username, password):
        raise HTTPException(status_code=401, detail="账号或密码错误")

    # 验证成功，创建会话
    token, user_id = create_session_token(None)

    return {
        "token": token,
        "user_id": user_id,
        "expire_hours": 24
    }


# ============ 数据缓存管理 ============
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

SCAN_RESULTS_CACHE = CACHE_DIR / "scan_results.json"
SCAN_STATUS_FILE = CACHE_DIR / "scan_status.json"
STOCK_LIST_CACHE_FILE = CACHE_DIR / "stock_list_cache.json"
BUY_SCAN_RESULTS_CACHE = CACHE_DIR / "buy_scan_results.json"
SELL_SCAN_RESULTS_CACHE = CACHE_DIR / "sell_scan_results.json"

# 扫描状态（内存中）
scan_status = {
    "scanning": False,
    "progress": 0,
    "total": 0,
    "found": 0,
    "start_time": None,
    "message": "未开始",
    "last_scan_time": None
}


def load_scan_results():
    """加载扫描结果缓存"""
    if SCAN_RESULTS_CACHE.exists():
        try:
            with open(SCAN_RESULTS_CACHE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('stocks', [])
        except Exception as e:
            print(f"加载缓存失败: {e}")
    return []


def save_scan_results(results):
    """保存扫描结果"""
    cache_data = {
        'cache_time': datetime.now().isoformat(),
        'stocks': results
    }
    with open(SCAN_RESULTS_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)


def save_scan_status():
    """保存扫描状态"""
    with open(SCAN_STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(scan_status, f, ensure_ascii=False, indent=2)


def calculate_bs_stats(results: List[Dict]) -> Dict:
    """计算买卖点统计"""
    buy_stats = {'1': 0, '2': 0, '3a': 0, '3b': 0}
    sell_stats = {'1': 0, '2s': 0, '3a': 0, '3b': 0}

    for stock in results:
        for signal in stock.get('signals', []):
            signal_type = signal.get('type', '')
            direction = signal.get('direction', '')

            if direction == '买入':
                if signal_type in buy_stats:
                    buy_stats[signal_type] = buy_stats.get(signal_type, 0) + 1
            else:
                # 卖出类型映射
                sell_key = signal_type if signal_type.startswith('2s') or signal_type.startswith('3') else '2s'
                if sell_key in sell_stats:
                    sell_stats[sell_key] = sell_stats.get(sell_key, 0) + 1

    return {
        'buy': buy_stats,
        'sell': sell_stats,
        'heat': {
            'volume': '8,632亿',
            'limit_up': 52,
            'limit_down': 12
        }
    }


# ============ 股票列表获取（独立实现，避免导入 scan_stocks） ============

def get_stock_list_cached(force_refresh: bool = False) -> List[str]:
    """
    获取A股代码列表（独立实现，支持缓存）

    不依赖 scan_stocks 模块，避免触发 ChanAnalyzer 的阻塞导入
    """
    # 检查缓存
    if not force_refresh and STOCK_LIST_CACHE_FILE.exists():
        try:
            with open(STOCK_LIST_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            cache_time = datetime.fromisoformat(cache_data.get('time', ''))
            if datetime.now() - cache_time < timedelta(days=7):
                return cache_data.get('stocks', [])
        except Exception:
            pass

    # 从 StockPool 获取（使用延迟导入）
    try:
        StockPool = import_stock_pool()
        pool = StockPool(force_refresh=force_refresh)
        stock_list = pool.get_stock_list()

        # 保存缓存
        cache_data = {
            'time': datetime.now().isoformat(),
            'stocks': stock_list,
            'count': len(stock_list)
        }
        with open(STOCK_LIST_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)

        return stock_list
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        return []


# ============ 买卖点检查（独立实现） ============

def check_signals_in_analysis(analysis: Dict, buy_types: List[str], sell_types: List[str]) -> List[Dict]:
    """
    从分析结果中提取买卖点信号

    Args:
        analysis: ChanAnalyzer.get_analysis() 返回的结果
        buy_types: 要匹配的买点类型，如 ['1', '2', '3a', '3b']
        sell_types: 要匹配的卖点类型

    Returns:
        匹配的信号列表
    """
    signals = []

    # 检查单周期分析结果
    if not analysis.get('multi'):
        # 单周期结果，直接处理
        for signal in analysis.get('buy_signals', []):
            if signal.get('type') in buy_types:
                signals.append({
                    'type': signal.get('type'),
                    'direction': '买入',
                    'date': signal.get('date', ''),
                    'price': signal.get('price', 0)
                })

        for signal in analysis.get('sell_signals', []):
            if signal.get('type') in sell_types:
                signals.append({
                    'type': signal.get('type'),
                    'direction': '卖出',
                    'date': signal.get('date', ''),
                    'price': signal.get('price', 0)
                })

    return signals


# ============ 后台扫描任务 ============

async def background_scan_task(limit: int = 100, buy_types: List[str] = None):
    """
    后台扫描任务

    完全独立实现，不依赖 scan_stocks 模块
    """
    global scan_status

    try:
        scan_status["scanning"] = True
        scan_status["start_time"] = datetime.now().isoformat()
        scan_status["message"] = "正在获取股票列表..."
        save_scan_status()

        # 获取股票列表
        stock_codes = get_stock_list_cached()[:limit]
        if not stock_codes:
            scan_status["scanning"] = False
            scan_status["message"] = "获取股票列表失败"
            save_scan_status()
            return

        scan_status["total"] = len(stock_codes)
        scan_status["message"] = f"开始扫描 {len(stock_codes)} 只股票..."
        save_scan_status()

        results = []
        buy_types = buy_types or ['2', '3a', '3b']
        sell_types = ['1', '2s', '3a', '3b']

        # 延迟导入 StockPool（使用单例缓存）
        StockPool = import_stock_pool()
        pool = StockPool()

        for i, code in enumerate(stock_codes):
            try:
                # 延迟导入 ChanAnalyzer - 每次循环都重新导入以利用进程隔离
                # 由于是在后台任务中，这里不会阻塞 API 启动
                ChanAnalyzer = import_chan_analyzer()

                analyzer = ChanAnalyzer(code=code)
                analysis = analyzer.get_analysis()

                # 检查买卖点
                matched = check_signals_in_analysis(analysis, buy_types, sell_types)

                if matched:
                    info = pool.get_stock_info(code)

                    # 获取最新价格
                    # 多周期分析时，analyzer 会使用日线级别的 current_price
                    current_price = analysis.get('current_price', 0)

                    results.append({
                        'code': code,
                        'name': info.get('name', '') if info else '',
                        'signals': matched,
                        'current_price': current_price
                    })

                # 更新进度
                scan_status["progress"] = i + 1
                scan_status["found"] = len(results)

                # 每10只股票保存一次状态
                if (i + 1) % 10 == 0:
                    save_scan_status()

            except Exception as e:
                # 跳过有问题的股票，继续处理下一只
                pass

        # 保存结果
        save_scan_results(results)

        scan_status["scanning"] = False
        scan_status["message"] = f"扫描完成，找到 {len(results)} 只股票"
        scan_status["last_scan_time"] = datetime.now().isoformat()
        save_scan_status()

    except Exception as e:
        scan_status["scanning"] = False
        scan_status["message"] = f"扫描失败: {str(e)}"
        save_scan_status()


# ============ 买卖点扫描任务（多用户支持） ============

# 进程池配置 - 用于绕过GIL，支持真正的并发扫描
MAX_SCAN_WORKERS = max(2, multiprocessing.cpu_count() - 1)
scan_process_pool = None  # 延迟初始化

# 并发限制 - 限制同时运行的扫描任务数量
MAX_CONCURRENT_SCANS = int(os.getenv('MAX_CONCURRENT_SCANS', '5'))
active_scans_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCANS)

# 用户扫描状态 - 按用户ID隔离
# 结构: {user_id: {'buy': {...}, 'sell': {...}}}
user_scan_statuses: Dict[str, Dict[str, Dict]] = defaultdict(lambda: {
    'buy': {"scanning": False, "progress": 0, "total": 0, "found": 0,
            "start_time": None, "message": "未开始", "last_scan_time": None, "error": None},
    'sell': {"scanning": False, "progress": 0, "total": 0, "found": 0,
             "start_time": None, "message": "未开始", "last_scan_time": None, "error": None}
})
user_scan_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)

# 保留全局状态用于兼容旧代码（已废弃，使用user_scan_statuses代替）
buy_scan_status = {"scanning": False, "progress": 0, "total": 0, "found": 0,
                   "start_time": None, "message": "未开始", "last_scan_time": None, "error": None}
sell_scan_status = {"scanning": False, "progress": 0, "total": 0, "found": 0,
                    "start_time": None, "message": "未开始", "last_scan_time": None, "error": None}


def get_scan_process_pool():
    """获取扫描进程池（延迟初始化）"""
    global scan_process_pool
    if scan_process_pool is None:
        from concurrent.futures import ProcessPoolExecutor
        scan_process_pool = ProcessPoolExecutor(max_workers=MAX_SCAN_WORKERS)
    return scan_process_pool


def get_user_scan_status(user_id: str, scan_type: str) -> Dict:
    """获取用户的扫描状态"""
    return user_scan_statuses[user_id][scan_type]


def update_user_scan_status(user_id: str, scan_type: str, **kwargs):
    """更新用户的扫描状态"""
    status = user_scan_statuses[user_id][scan_type]
    status.update(kwargs)
    # 保存到文件
    status_file = get_user_status_file(user_id, scan_type)
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def save_scan_status_for_type(scan_type: str):
    """保存指定类型的扫描状态（兼容旧代码）"""
    status = buy_scan_status if scan_type == 'buy' else sell_scan_status
    status_file = CACHE_DIR / f"{scan_type}_scan_status.json"
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


# ============ 独立进程扫描函数（可在进程池中执行） ============

def _run_scan_in_process(stock_codes: List[str], buy_types: List[str],
                         sell_types: List[str], scan_type: str,
                         user_id: str, user_data_dir: str,
                         industries: List[str] = None,
                         areas: List[str] = None,
                         exclude_st: bool = True,
                         exclude_suspend: bool = True) -> Dict:
    """
    在独立进程中执行的扫描函数

    注意：这个函数必须在模块级别定义，以便能被pickle序列化

    Args:
        stock_codes: 股票代码列表
        buy_types: 买点类型列表
        sell_types: 卖点类型列表
        scan_type: 'buy' 或 'sell'
        user_id: 用户ID
        user_data_dir: 用户数据目录路径
        industries: 行业筛选列表
        areas: 地区筛选列表
        exclude_st: 是否排除ST股票
        exclude_suspend: 是否排除停牌股票

    Returns:
        扫描结果字典
    """
    import sys
    from pathlib import Path
    import json
    from datetime import datetime

    # 添加项目路径
    user_data_path = Path(user_data_dir)

    # 初始化结果
    result = {
        'success': False,
        'stocks': [],
        'error': None,
        'total': len(stock_codes),
        'found': 0
    }

    try:
        # 延迟导入 - 避免在进程池中导入父模块的问题
        sys.path.insert(0, str(Path(__file__).parent.parent))

        # 导入扫描模块
        import scan_stocks_cache

        # 创建进度回调（保存到临时文件用于主进程读取）
        status_file = user_data_path / f"{scan_type}_status_{user_id}.json"

        def progress_callback(current, total, found):
            progress_data = {
                "scanning": True,
                "progress": current,
                "total": total,
                "found": found,
                "message": f"扫描中 {current}/{total}",
                "start_time": datetime.now().isoformat()
            }
            with open(status_file, 'w', encoding='utf-8') as f:
                json.dump(progress_data, f, ensure_ascii=False, indent=2)

        # 执行扫描
        results = scan_stocks_cache.scan_stocks(
            stock_codes=stock_codes,
            buy_types=buy_types,
            sell_types=sell_types,
            verbose=False,
            progress_callback=progress_callback,
            industries=industries,
            areas=areas,
            exclude_st=exclude_st,
            exclude_suspend=exclude_suspend,
        )

        # 获取股票信息
        result_codes = [r['code'] for r in results]
        stock_info = scan_stocks_cache.get_stock_info_bulk(result_codes)

        # 组装结果
        formatted_results = []
        for r in results:
            info = stock_info.get(r['code'], {})
            signals = r.get('signals', [])
            latest_signal = None
            if signals:
                sorted_signals = sorted(signals, key=lambda x: x['date'], reverse=True)
                latest_signal = sorted_signals[0]

            formatted_results.append({
                'code': r['code'],
                'name': info.get('name', ''),
                'current_price': r.get('latest_price', 0),
                'change_pct': r.get('change_pct', 0),
                'signals': signals,
                'latest_signal': latest_signal
            })

        result['success'] = True
        result['stocks'] = formatted_results
        result['found'] = len(formatted_results)

    except Exception as e:
        import traceback
        result['error'] = str(e)
        result['traceback'] = traceback.format_exc()

    return result


# ============ 多用户后台扫描任务 ============

async def multi_user_buy_scan_task(
    user_id: str,
    types: List[str],
    limit: int,
    stock_codes: List[str] = None,
    industries: List[str] = None,
    areas: List[str] = None,
    exclude_st: bool = True,
    exclude_suspend: bool = True,
):
    """
    多用户买点扫描任务

    使用进程池在独立进程中执行扫描，绕过GIL限制

    Args:
        user_id: 用户ID
        types: 买点类型列表
        limit: 扫描数量限制
        stock_codes: 指定股票代码列表（可选）
        industries: 行业筛选（可选）
        areas: 地区筛选（可选）
        exclude_st: 是否排除ST股票
        exclude_suspend: 是否排除停牌股票
    """
    loop = asyncio.get_event_loop()
    pool = get_scan_process_pool()

    try:
        # 初始化状态
        update_user_scan_status(user_id, 'buy',
            scanning=True, error=None, progress=0,
            start_time=datetime.now().isoformat(),
            message="正在获取股票列表..."
        )

        # 获取股票列表
        try:
            # 如果指定了股票代码列表，直接使用
            if stock_codes:
                codes_to_scan = stock_codes
            else:
                all_stock_codes = scan_stocks_cache.get_stock_list_from_db()
                codes_to_scan = all_stock_codes if limit <= 0 else all_stock_codes[:limit]
        except FileNotFoundError as e:
            update_user_scan_status(user_id, 'buy',
                scanning=False, error=f"数据库文件不存在: {str(e)}",
                message="数据库文件不存在，请先创建数据库"
            )
            return

        if not codes_to_scan:
            update_user_scan_status(user_id, 'buy',
                scanning=False, error="股票列表为空",
                message="未找到可扫描的股票"
            )
            return

        update_user_scan_status(user_id, 'buy',
            total=len(codes_to_scan),
            message=f"开始扫描 {len(codes_to_scan)} 只股票..."
        )

        # 在进程池中执行扫描
        result = await loop.run_in_executor(
            pool,
            _run_scan_in_process,
            codes_to_scan, types, [], 'buy', user_id,
            str(Path(__file__).parent / 'users'),
            industries, areas, exclude_st, exclude_suspend
        )

        # 处理结果
        if result['success']:
            # 保存结果
            cache_file = get_user_cache_file(user_id, 'buy')
            save_scan_results_cache(cache_file, result['stocks'])

            update_user_scan_status(user_id, 'buy',
                scanning=False,
                progress=result['total'],
                found=result['found'],
                message=f"买点扫描完成，找到 {result['found']} 只股票",
                last_scan_time=datetime.now().isoformat()
            )
        else:
            update_user_scan_status(user_id, 'buy',
                scanning=False,
                error=result.get('error', '未知错误'),
                message=f"扫描失败: {result.get('error', '未知错误')}"
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        update_user_scan_status(user_id, 'buy',
            scanning=False,
            error=str(e),
            message=f"扫描失败: {str(e)}"
        )


async def multi_user_sell_scan_task(
    user_id: str,
    types: List[str],
    limit: int,
    stock_codes: List[str] = None,
    industries: List[str] = None,
    areas: List[str] = None,
    exclude_st: bool = True,
    exclude_suspend: bool = True,
):
    """
    多用户卖点扫描任务

    Args:
        user_id: 用户ID
        types: 卖点类型列表
        limit: 扫描数量限制
        stock_codes: 指定股票代码列表（可选）
        industries: 行业筛选（可选）
        areas: 地区筛选（可选）
        exclude_st: 是否排除ST股票
        exclude_suspend: 是否排除停牌股票
    """
    loop = asyncio.get_event_loop()
    pool = get_scan_process_pool()

    try:
        # 初始化状态
        update_user_scan_status(user_id, 'sell',
            scanning=True, error=None, progress=0,
            start_time=datetime.now().isoformat(),
            message="正在获取股票列表..."
        )

        # 获取股票列表
        try:
            # 如果指定了股票代码列表，直接使用
            if stock_codes:
                codes_to_scan = stock_codes
            else:
                all_stock_codes = scan_stocks_cache.get_stock_list_from_db()
                codes_to_scan = all_stock_codes if limit <= 0 else all_stock_codes[:limit]
        except FileNotFoundError as e:
            update_user_scan_status(user_id, 'sell',
                scanning=False, error=f"数据库文件不存在: {str(e)}",
                message="数据库文件不存在，请先创建数据库"
            )
            return

        if not codes_to_scan:
            update_user_scan_status(user_id, 'sell',
                scanning=False, error="股票列表为空",
                message="未找到可扫描的股票"
            )
            return

        update_user_scan_status(user_id, 'sell',
            total=len(codes_to_scan),
            message=f"开始扫描 {len(codes_to_scan)} 只股票..."
        )

        # 在进程池中执行扫描
        result = await loop.run_in_executor(
            pool,
            _run_scan_in_process,
            codes_to_scan, [], types, 'sell', user_id,
            str(Path(__file__).parent / 'users'),
            industries, areas, exclude_st, exclude_suspend
        )

        # 处理结果
        if result['success']:
            # 保存结果
            cache_file = get_user_cache_file(user_id, 'sell')
            save_scan_results_cache(cache_file, result['stocks'])

            update_user_scan_status(user_id, 'sell',
                scanning=False,
                progress=result['total'],
                found=result['found'],
                message=f"卖点扫描完成，找到 {result['found']} 只股票",
                last_scan_time=datetime.now().isoformat()
            )
        else:
            update_user_scan_status(user_id, 'sell',
                scanning=False,
                error=result.get('error', '未知错误'),
                message=f"扫描失败: {result.get('error', '未知错误')}"
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        update_user_scan_status(user_id, 'sell',
            scanning=False,
            error=str(e),
            message=f"扫描失败: {str(e)}"
        )


def save_scan_results_cache(cache_file: Path, results: List[Dict]):
    """保存扫描结果到指定缓存文件"""
    cache_data = {
        'cache_time': datetime.now().isoformat(),
        'stocks': results
    }
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)


def load_scan_results_cache(cache_file: Path) -> Dict:
    """从指定缓存文件加载扫描结果"""
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载缓存失败 {cache_file}: {e}")
    return {'cache_time': None, 'stocks': []}


def background_buy_scan_task(types: List[str], limit: int):
    """
    后台买点扫描任务 - 复用 scan_stocks_cache 模块

    注意：这是一个同步函数，由 FastAPI 的 BackgroundTasks 在线程池中执行

    Args:
        types: 买点类型列表，如 ['1', '2', '3a', '3b']
        limit: 扫描股票数量限制
    """
    global buy_scan_status

    try:
        buy_scan_status["scanning"] = True
        buy_scan_status["error"] = None
        buy_scan_status["progress"] = 0
        buy_scan_status["start_time"] = datetime.now().isoformat()
        buy_scan_status["message"] = "正在获取股票列表..."
        save_scan_status_for_type('buy')

        # 获取股票列表 - 添加详细错误处理
        try:
            all_stock_codes = scan_stocks_cache.get_stock_list_from_db()
            # 当 limit <= 0 时表示扫描全市场，否则取前 limit 只
            stock_codes = all_stock_codes if limit <= 0 else all_stock_codes[:limit]
        except FileNotFoundError as e:
            buy_scan_status["scanning"] = False
            buy_scan_status["error"] = f"数据库文件不存在: {str(e)}"
            buy_scan_status["message"] = "数据库文件不存在，请先创建数据库"
            save_scan_status_for_type('buy')
            return
        except RuntimeError as e:
            buy_scan_status["scanning"] = False
            buy_scan_status["error"] = f"数据库查询失败: {str(e)}"
            buy_scan_status["message"] = "从数据库获取股票列表失败"
            save_scan_status_for_type('buy')
            return
        except Exception as e:
            buy_scan_status["scanning"] = False
            buy_scan_status["error"] = f"获取股票列表异常: {str(e)}"
            buy_scan_status["message"] = "获取股票列表时发生未知错误"
            save_scan_status_for_type('buy')
            return

        if not stock_codes:
            buy_scan_status["scanning"] = False
            buy_scan_status["error"] = "股票列表为空"
            buy_scan_status["message"] = "未找到可扫描的股票"
            save_scan_status_for_type('buy')
            return

        buy_scan_status["total"] = len(stock_codes)
        buy_scan_status["message"] = f"开始扫描 {len(stock_codes)} 只股票..."
        save_scan_status_for_type('buy')

        # 定义进度回调函数
        def progress_callback(current, total, found):
            buy_scan_status["progress"] = current
            buy_scan_status["found"] = found
            buy_scan_status["message"] = f"扫描中 {current}/{total}"
            save_scan_status_for_type('buy')

        # 调用 scan_stocks_cache 的扫描函数（带进度回调）
        results = scan_stocks_cache.scan_stocks(
            stock_codes=stock_codes,
            buy_types=types,
            sell_types=[],
            verbose=False,
            progress_callback=progress_callback
        )

        # 获取股票信息（名称、行业）
        result_codes = [r['code'] for r in results]
        stock_info = scan_stocks_cache.get_stock_info_bulk(result_codes)

        # 组装结果（包含股票名称）
        formatted_results = []
        for r in results:
            info = stock_info.get(r['code'], {})
            # 找到最新的信号（按日期排序）
            signals = r.get('signals', [])
            latest_signal = None
            if signals:
                sorted_signals = sorted(signals, key=lambda x: x['date'], reverse=True)
                latest_signal = sorted_signals[0]

            formatted_results.append({
                'code': r['code'],
                'name': info.get('name', ''),
                'current_price': r.get('latest_price', 0),
                'change_pct': r.get('change_pct', 0),
                'signals': signals,
                'latest_signal': latest_signal
            })

        # 保存结果
        save_scan_results_cache(BUY_SCAN_RESULTS_CACHE, formatted_results)

        buy_scan_status["scanning"] = False
        buy_scan_status["progress"] = buy_scan_status["total"]
        buy_scan_status["found"] = len(formatted_results)
        buy_scan_status["message"] = f"买点扫描完成，找到 {len(formatted_results)} 只股票"
        buy_scan_status["last_scan_time"] = datetime.now().isoformat()
        save_scan_status_for_type('buy')

    except Exception as e:
        import traceback
        traceback.print_exc()
        buy_scan_status["scanning"] = False
        buy_scan_status["error"] = str(e)
        buy_scan_status["message"] = f"扫描失败: {str(e)}"
        save_scan_status_for_type('buy')


def background_sell_scan_task(types: List[str], limit: int):
    """
    后台卖点扫描任务 - 复用 scan_stocks_cache 模块

    注意：这是一个同步函数，由 FastAPI 的 BackgroundTasks 在线程池中执行

    Args:
        types: 卖点类型列表，如 ['1', '2s', '3a', '3b']
        limit: 扫描股票数量限制
    """
    global sell_scan_status

    try:
        sell_scan_status["scanning"] = True
        sell_scan_status["error"] = None
        sell_scan_status["progress"] = 0
        sell_scan_status["start_time"] = datetime.now().isoformat()
        sell_scan_status["message"] = "正在获取股票列表..."
        save_scan_status_for_type('sell')

        # 获取股票列表 - 添加详细错误处理
        try:
            all_stock_codes = scan_stocks_cache.get_stock_list_from_db()
            # 当 limit <= 0 时表示扫描全市场，否则取前 limit 只
            stock_codes = all_stock_codes if limit <= 0 else all_stock_codes[:limit]
        except FileNotFoundError as e:
            sell_scan_status["scanning"] = False
            sell_scan_status["error"] = f"数据库文件不存在: {str(e)}"
            sell_scan_status["message"] = "数据库文件不存在，请先创建数据库"
            save_scan_status_for_type('sell')
            return
        except RuntimeError as e:
            sell_scan_status["scanning"] = False
            sell_scan_status["error"] = f"数据库查询失败: {str(e)}"
            sell_scan_status["message"] = "从数据库获取股票列表失败"
            save_scan_status_for_type('sell')
            return
        except Exception as e:
            sell_scan_status["scanning"] = False
            sell_scan_status["error"] = f"获取股票列表异常: {str(e)}"
            sell_scan_status["message"] = "获取股票列表时发生未知错误"
            save_scan_status_for_type('sell')
            return

        if not stock_codes:
            sell_scan_status["scanning"] = False
            sell_scan_status["error"] = "股票列表为空"
            sell_scan_status["message"] = "未找到可扫描的股票"
            save_scan_status_for_type('sell')
            return

        sell_scan_status["total"] = len(stock_codes)
        sell_scan_status["message"] = f"开始扫描 {len(stock_codes)} 只股票..."
        save_scan_status_for_type('sell')

        # 定义进度回调函数
        def progress_callback(current, total, found):
            sell_scan_status["progress"] = current
            sell_scan_status["found"] = found
            sell_scan_status["message"] = f"扫描中 {current}/{total}"
            save_scan_status_for_type('sell')

        # 调用 scan_stocks_cache 的扫描函数（带进度回调）
        results = scan_stocks_cache.scan_stocks(
            stock_codes=stock_codes,
            buy_types=[],
            sell_types=types,
            verbose=False,
            progress_callback=progress_callback
        )

        # 获取股票信息（名称、行业）
        result_codes = [r['code'] for r in results]
        stock_info = scan_stocks_cache.get_stock_info_bulk(result_codes)

        # 组装结果（包含股票名称）
        formatted_results = []
        for r in results:
            info = stock_info.get(r['code'], {})
            # 找到最新的信号（按日期排序）
            signals = r.get('signals', [])
            latest_signal = None
            if signals:
                sorted_signals = sorted(signals, key=lambda x: x['date'], reverse=True)
                latest_signal = sorted_signals[0]

            formatted_results.append({
                'code': r['code'],
                'name': info.get('name', ''),
                'current_price': r.get('latest_price', 0),
                'change_pct': r.get('change_pct', 0),
                'signals': signals,
                'latest_signal': latest_signal
            })

        # 保存结果
        save_scan_results_cache(SELL_SCAN_RESULTS_CACHE, formatted_results)

        sell_scan_status["scanning"] = False
        sell_scan_status["progress"] = sell_scan_status["total"]
        sell_scan_status["found"] = len(formatted_results)
        sell_scan_status["message"] = f"卖点扫描完成，找到 {len(formatted_results)} 只股票"
        sell_scan_status["last_scan_time"] = datetime.now().isoformat()
        save_scan_status_for_type('sell')

    except Exception as e:
        import traceback
        traceback.print_exc()
        sell_scan_status["scanning"] = False
        sell_scan_status["error"] = str(e)
        sell_scan_status["message"] = f"扫描失败: {str(e)}"
        save_scan_status_for_type('sell')


def save_scan_status_for_type(scan_type: str):
    """保存指定类型的扫描状态"""
    status = buy_scan_status if scan_type == 'buy' else sell_scan_status
    status_file = CACHE_DIR / f"{scan_type}_scan_status.json"
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


# ============ API 接口 ============

class ScanRequest(BaseModel):
    """扫描请求"""
    buy_types: List[str] = ["2", "3a", "3b"]
    limit: int = 100


class BuyScanRequest(BaseModel):
    """买点扫描请求"""
    types: List[str] = ["1", "2", "3a", "3b"]  # 买点类型
    limit: int = 100
    # 新增筛选参数
    stock_codes: Optional[List[str]] = None   # 指定股票代码列表（个股模式）
    industries: Optional[List[str]] = None    # 行业筛选，如 ["电子", "计算机"]
    areas: Optional[List[str]] = None         # 地区筛选，如 ["深圳", "上海"]
    exclude_st: bool = True                   # 是否排除ST股票
    exclude_suspend: bool = True              # 是否排除停牌股票


class SellScanRequest(BaseModel):
    """卖点扫描请求"""
    types: List[str] = ["2s"]  # 卖点类型
    limit: int = 100
    # 新增筛选参数
    stock_codes: Optional[List[str]] = None   # 指定股票代码列表
    industries: Optional[List[str]] = None    # 行业筛选
    areas: Optional[List[str]] = None         # 地区筛选
    exclude_st: bool = True                   # 是否排除ST股票
    exclude_suspend: bool = True              # 是否排除停牌股票


@app.post("/api/scan/start")
async def start_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    """启动扫描任务"""
    if scan_status["scanning"]:
        return {"message": "扫描任务正在进行中", "status": "running"}

    # 在后台执行扫描
    background_tasks.add_task(background_scan_task, request.limit, request.buy_types)

    return {"message": "扫描任务已启动", "status": "started"}


@app.get("/api/scan/status")
async def get_scan_status_api():
    """获取扫描状态"""
    return scan_status


# ============ 买卖点扫描 API 端点（多用户支持） ============

@app.post("/api/scan/buy/start")
async def start_buy_scan(
    request: BuyScanRequest,
    user_id: str = Depends(get_current_user)
):
    """
    启动买点扫描任务（多用户支持）

    每个用户的扫描任务独立执行，结果隔离存储
    """
    # 检查用户是否已有正在进行的扫描
    user_status = get_user_scan_status(user_id, 'buy')
    if user_status.get('scanning', False):
        return {"message": "您有买点扫描任务正在进行中", "status": "running"}

    # 检查并发限制
    if active_scans_semaphore.locked():
        # 获取当前活跃任务数
        active_count = MAX_CONCURRENT_SCANS - active_scans_semaphore._value
        return {
            "message": f"系统繁忙，当前有 {active_count}/{MAX_CONCURRENT_SCANS} 扫描任务正在运行",
            "status": "busy"
        }

    # 启动异步任务
    asyncio.create_task(multi_user_buy_scan_task(
        user_id, request.types, request.limit,
        request.stock_codes, request.industries, request.areas,
        request.exclude_st, request.exclude_suspend
    ))

    return {"message": "买点扫描任务已启动", "status": "started", "user_id": user_id}


@app.post("/api/scan/sell/start")
async def start_sell_scan(
    request: SellScanRequest,
    user_id: str = Depends(get_current_user)
):
    """
    启动卖点扫描任务（多用户支持）
    """
    # 检查用户是否已有正在进行的扫描
    user_status = get_user_scan_status(user_id, 'sell')
    if user_status.get('scanning', False):
        return {"message": "您有卖点扫描任务正在进行中", "status": "running"}

    # 检查并发限制
    if active_scans_semaphore.locked():
        active_count = MAX_CONCURRENT_SCANS - active_scans_semaphore._value
        return {
            "message": f"系统繁忙，当前有 {active_count}/{MAX_CONCURRENT_SCANS} 扫描任务正在运行",
            "status": "busy"
        }

    # 启动异步任务
    asyncio.create_task(multi_user_sell_scan_task(
        user_id, request.types, request.limit,
        request.stock_codes, request.industries, request.areas,
        request.exclude_st, request.exclude_suspend
    ))

    return {"message": "卖点扫描任务已启动", "status": "started", "user_id": user_id}


@app.get("/api/scan/buy/results")
async def get_buy_scan_results(user_id: str = Depends(get_current_user)):
    """
    获取买点扫描结果（多用户支持）

    每个用户只看到自己的扫描结果
    """
    cache_file = get_user_cache_file(user_id, 'buy')
    data = load_scan_results_cache(cache_file)
    return data


@app.get("/api/scan/sell/results")
async def get_sell_scan_results(user_id: str = Depends(get_current_user)):
    """
    获取卖点扫描结果（多用户支持）
    """
    cache_file = get_user_cache_file(user_id, 'sell')
    data = load_scan_results_cache(cache_file)
    return data


@app.get("/api/scan/buy/status")
async def get_buy_scan_status(user_id: str = Depends(get_current_user)):
    """
    获取买点扫描状态（多用户支持）

    每个用户只看到自己的扫描状态
    """
    # 从文件读取最新状态
    status_file = get_user_status_file(user_id, 'buy')
    if status_file.exists():
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    # 返回内存中的状态
    return get_user_scan_status(user_id, 'buy')


@app.get("/api/scan/sell/status")
async def get_sell_scan_status(user_id: str = Depends(get_current_user)):
    """
    获取卖点扫描状态（多用户支持）
    """
    # 从文件读取最新状态
    status_file = get_user_status_file(user_id, 'sell')
    if status_file.exists():
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    # 返回内存中的状态
    return get_user_scan_status(user_id, 'sell')


@app.get("/api/stock/list")
async def get_stock_list_api(limit: int = 100):
    """获取股票列表"""
    try:
        StockPool = import_stock_pool()
        pool = StockPool()
        stock_list = pool.get_stock_list()[:limit]

        result = []
        for code in stock_list:
            info = pool.get_stock_info(code)
            if info:
                result.append({
                    "code": code,
                    "name": info.get("name", ""),
                    "industry": info.get("industry", ""),
                    "area": info.get("area", "")
                })

        return {"stocks": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ 筛选数据接口 ============

@app.get("/api/industries")
async def get_industries():
    """获取所有行业及其股票数量"""
    try:
        import sqlite3
        db_path = Path(__file__).parent.parent / "chan.db"
        if not db_path.exists():
            return {"industries": []}

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT industry, COUNT(*) as count
            FROM stock_info
            WHERE industry IS NOT NULL AND industry != ''
            GROUP BY industry
            ORDER BY count DESC
        """)
        industries = [{"name": row[0], "count": row[1]} for row in cursor.fetchall()]
        conn.close()

        return {"industries": industries}
    except Exception as e:
        print(f"获取行业列表失败: {e}")
        return {"industries": []}


@app.get("/api/areas")
async def get_areas():
    """获取所有地区及其股票数量"""
    try:
        import sqlite3
        db_path = Path(__file__).parent.parent / "chan.db"
        if not db_path.exists():
            return {"areas": []}

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT area, COUNT(*) as count
            FROM stock_info
            WHERE area IS NOT NULL AND area != ''
            GROUP BY area
            ORDER BY count DESC
        """)
        areas = [{"name": row[0], "count": row[1]} for row in cursor.fetchall()]
        conn.close()

        return {"areas": areas}
    except Exception as e:
        print(f"获取地区列表失败: {e}")
        return {"areas": []}


@app.get("/api/stock/{code}/signals")
async def get_stock_signals(code: str):
    """获取指定股票的买卖点摘要（使用 ChanAnalyzer 单日线分析）

    支持股票代码或名称输入（模糊匹配）
    """
    # 解析股票代码/名称
    resolved_code, resolved_name, success = resolve_stock_code(code)
    if not success:
        return {
            "code": code,
            "current_price": 0,
            "latest_buy": None,
            "latest_sell": None,
            "error": f"未找到股票: {code}"
        }

    # 使用解析后的代码
    code = resolved_code

    try:
        # 使用 ChanAnalyzer 单日线进行分析（确保买卖点检测结果一致）
        ChanAnalyzer = import_chan_analyzer()
        analyzer = ChanAnalyzer(code=code)
        analysis = analyzer.get_analysis()

        # 从分析结果中提取买卖点
        all_signals = analysis.get('buy_signals', []) + analysis.get('sell_signals', [])

        # 按日期排序
        all_signals.sort(key=lambda s: s.get('date', ''), reverse=True)

        # 找到最新的买点和卖点
        latest_buy = None
        latest_sell = None
        for signal in all_signals:
            if signal.get('is_buy') and latest_buy is None:
                latest_buy = {
                    "type": signal['type'],
                    "is_buy": True,
                    "date": signal['date'],
                    "price": signal['price']
                }
            elif not signal.get('is_buy') and latest_sell is None:
                latest_sell = {
                    "type": signal['type'],
                    "is_buy": False,
                    "date": signal['date'],
                    "price": signal['price']
                }
            if latest_buy and latest_sell:
                break

        # 获取最新价格
        current_price = analysis.get('current_price', 0)

        # 从数据库获取涨跌幅
        change_pct = None
        price_info = scan_stocks_cache.get_latest_price_from_db(code)
        if price_info:
            change_pct = price_info.get('change_pct')

        return {
            "code": code,
            "name": resolved_name,
            "current_price": current_price,
            "change_pct": change_pct,
            "latest_buy": latest_buy,
            "latest_sell": latest_sell
        }
    except Exception as e:
        import traceback
        error_detail = f"{str(e)}\n{traceback.format_exc()}"
        print(f"[get_stock_signals] {code} 分析失败: {error_detail}")
        # 返回空数据而不是抛出错误
        return {
            "code": code,
            "name": resolved_name,
            "current_price": 0,
            "change_pct": None,
            "latest_buy": None,
            "latest_sell": None,
            "error": str(e)
        }


@app.get("/api/ranking")
async def get_ranking(
    rank_type: str = "change_pct",  # change_pct(涨跌幅), amount(成交额), turnover_rate(换手率)
    top_n: int = 20,
    realtime: bool = False  # 是否使用实时数据
):
    """获取每日排行榜数据（使用tushare API）

    Args:
        rank_type: 排行类型
            - change_pct: 涨跌幅排行
            - amount: 成交额排行
            - turnover_rate: 换手率排行
        top_n: 返回前N只股票
        realtime: 是否使用实时数据（需要tushare积分>=2000）
    """
    try:
        import os
        import tushare as ts
        from datetime import datetime

        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            return {"stocks": [], "error": "未配置TUSHARE_TOKEN"}

        # 直接使用 token 初始化，避免写入缓存文件导致权限问题
        pro = ts.pro_api(token)

        # 获取股票列表（用于实时数据）
        stock_list = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
        if stock_list.empty:
            return {"stocks": [], "error": "获取股票列表失败"}

        # 过滤掉ST股票
        stock_list = stock_list[~stock_list['name'].str.contains('ST|PT|退')]

        if realtime:
            # 使用实时数据
            return await _get_realtime_ranking(pro, stock_list, rank_type, top_n)
        else:
            # 使用历史日线数据
            return await _get_daily_ranking(pro, rank_type, top_n)

    except Exception as e:
        print(f"获取排行榜失败: {e}")
        import traceback
        traceback.print_exc()
        return {"stocks": [], "error": str(e)}


async def _get_realtime_ranking(pro, stock_list, rank_type: str, top_n: int):
    """获取实时排行榜数据（使用tushare realtime_list接口）"""
    from datetime import datetime
    import tushare as ts
    import pandas as pd

    try:
        # 调用 tushare realtime_list 接口
        # src='dc' 表示从数据中心获取
        df_rt = ts.realtime_list(src='dc')

        if df_rt is None or df_rt.empty:
            return {"stocks": [], "error": "获取实时数据失败"}

        # 根据排行类型排序
        if rank_type == "change_pct":
            df_rt = df_rt.sort_values('pct_change', ascending=False)
            rank_name = "涨跌幅榜(实时)"
        elif rank_type == "amount":
            df_rt = df_rt.sort_values('amount', ascending=False)
            rank_name = "成交额榜(实时)"
        elif rank_type == "turnover_rate":
            df_rt = df_rt.sort_values('turnover_rate', ascending=False)
            rank_name = "换手率榜(实时)"
        else:
            return {"stocks": [], "error": "不支持的排行类型"}

        # 取前N名
        df_rt = df_rt.head(top_n)

        # 过滤掉ST股票
        df_rt = df_rt[~df_rt['name'].str.contains('ST|PT|退', na=False)]

        # 构建返回数据
        stocks = []
        for _, row in df_rt.iterrows():
            ts_code = row['ts_code']
            code = ts_code.split('.')[0]
            pct_change = row.get('pct_change', 0)

            stocks.append({
                "code": code,
                "name": row.get('name', ''),
                "close": row.get('price', 0),
                "change_pct": pct_change / 100 if pd.notna(pct_change) else 0,
                "turnover_rate": row.get('turnover_rate', 0),
                "volume": row.get('volume', 0),
                "amount": row.get('amount', 0)
            })

        now = datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")

        return {
            "rank_type": rank_type,
            "rank_name": rank_name,
            "date": time_str,
            "realtime": True,
            "stocks": stocks
        }

    except Exception as e:
        print(f"获取实时排行榜失败: {e}")
        import traceback
        traceback.print_exc()
        return {"stocks": [], "error": f"获取实时数据失败: {str(e)}"}


async def _get_daily_ranking(pro, rank_type: str, top_n: int):
    """获取历史日线排行榜数据"""
    from datetime import datetime
    import pandas as pd

    # 获取最新交易日
    trade_cal = pro.trade_cal(exchange='SSE', start_date='20200101', end_date=datetime.now().strftime('%Y%m%d'))
    trade_cal = trade_cal[trade_cal['is_open'] == 1]
    if trade_cal.empty:
        return {"stocks": [], "error": "无交易日数据"}

    latest_date = trade_cal['cal_date'].max()

    # 获取日线行情数据（包含涨跌幅和成交额）
    df = pro.daily(trade_date=latest_date)

    # 获取换手率数据
    df_basic = pro.daily_basic(trade_date=latest_date, fields='ts_code,turnover_rate')

    if df.empty:
        return {"stocks": [], "error": "暂无数据"}

    # 合并数据
    if not df_basic.empty:
        df = df.merge(df_basic, on='ts_code', how='left')

    # 过滤掉ST股票和退市股票
    df = df[~df['ts_code'].str.contains('ST|PT')]

    # 根据排行类型排序
    if rank_type == "change_pct":
        # 涨跌幅榜（排除涨幅为0的）
        df = df[df['pct_chg'] != 0].sort_values('pct_chg', ascending=False)
        rank_name = "涨跌幅榜"
    elif rank_type == "amount":
        # 成交额榜
        df = df.sort_values('amount', ascending=False)
        rank_name = "成交额榜"
    elif rank_type == "turnover_rate":
        # 换手率榜
        df = df.sort_values('turnover_rate', ascending=False)
        rank_name = "换手率榜"
    else:
        return {"stocks": [], "error": "不支持的排行类型"}

    # 取前N名
    df = df.head(top_n)

    # 获取股票名称
    stock_names = {}
    for ts_code in df['ts_code'].tolist():
        code = ts_code.split('.')[0]
        name = get_stock_name_by_code(code)
        stock_names[ts_code] = name

    # 构建返回数据
    stocks = []
    for _, row in df.iterrows():
        ts_code = row['ts_code']
        code = ts_code.split('.')[0]
        pct_chg = row.get('pct_chg', 0)
        turnover = row.get('turnover_rate')

        stocks.append({
            "code": code,
            "name": stock_names.get(ts_code, ''),
            "close": row['close'],
            "change_pct": pct_chg / 100 if pd.notna(pct_chg) else 0,  # 转换为小数
            "turnover_rate": turnover if pd.notna(turnover) else 0,
            "volume": row['vol'],
            "amount": row['amount']
        })

    # 格式化日期
    date_str = f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}"

    return {
        "rank_type": rank_type,
        "rank_name": rank_name,
        "date": date_str,
        "realtime": False,
        "stocks": stocks
    }


def get_stock_name_by_code(code: str) -> str:
    """根据股票代码获取股票名称"""
    try:
        import sqlite3
        db_path = Path(__file__).parent.parent / "chan.db"
        if not db_path.exists():
            return ""

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM stock_info WHERE code = ?", (code,))
        result = cursor.fetchone()
        conn.close()

        return result[0] if result else ""
    except:
        return ""


def get_stock_code_by_name(name: str) -> tuple:
    """
    根据股票名称模糊查找股票代码

    Args:
        name: 股票名称或代码（支持模糊匹配）

    Returns:
        (code, full_name) 股票代码和完整名称，未找到返回 (None, None)
    """
    try:
        import sqlite3
        db_path = Path(__file__).parent.parent / "chan.db"
        if not db_path.exists():
            return None, None

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. 先尝试精确匹配代码
        if name.isdigit():
            cursor.execute("SELECT code, name FROM stock_info WHERE code = ?", (name,))
            result = cursor.fetchone()
            if result:
                conn.close()
                return result[0], result[1]

        # 2. 模糊匹配名称
        cursor.execute(
            "SELECT code, name FROM stock_info WHERE name LIKE ? ORDER BY LENGTH(name) ASC LIMIT 1",
            (f"%{name}%",)
        )
        result = cursor.fetchone()
        conn.close()

        return (result[0], result[1]) if result else (None, None)
    except Exception as e:
        print(f"股票名称查找失败: {e}")
        return None, None


def resolve_stock_code(input_str: str) -> tuple:
    """
    解析股票输入，支持代码或名称

    Args:
        input_str: 股票代码或名称

    Returns:
        (code, name, is_resolved) 代码、名称、是否解析成功
    """
    input_str = input_str.strip()

    # 如果是纯数字，直接作为代码
    if input_str.isdigit():
        # 补全6位代码
        code = input_str.zfill(6)
        name = get_stock_name_by_code(code)
        return code, name, True

    # 否则作为名称查找
    code, name = get_stock_code_by_name(input_str)
    if code:
        return code, name, True

    return None, None, False


# ============ 个股分析接口 ============

class AnalyzeRequest(BaseModel):
    """分析请求"""
    code: str
    temperatures: Optional[Dict[str, float]] = None


async def stream_analyze_stock(code: str, temperatures: Dict[str, float] = None):
    """
    流式输出分析结果 (SSE)

    Args:
        code: 股票代码或名称（支持模糊匹配）
        temperatures: 温度配置 {analyst_a: 0.4, analyst_b: 0.7, decision_maker: 0.3}

    输出流程（顺序执行，确保用户体验）：
        1. 并行计算分析师A、B（结果缓存）
        2. 推送分析师A结果 → 等待打字机效果
        3. 推送分析师B结果 → 等待打字机效果
        4. 调用决策者 → 推送决策结果
    """
    import time

    # 打字机效果配置
    TYPEWRITER_SPEED_MS = 10  # 前端打字机速度（毫秒/字符）
    MAX_DISPLAY_WAIT = 5.0    # 单个分析师最大等待时间（秒）
    MIN_DISPLAY_WAIT = 1    # 最小等待时间（秒）

    def calculate_display_time(text: str) -> float:
        """根据文本长度计算打字机显示等待时间（秒）"""
        char_count = len(text)
        # 打字机显示时间 = 字符数 * 速度
        display_time = char_count * TYPEWRITER_SPEED_MS / 1000
        # 限制在合理范围内
        return max(MIN_DISPLAY_WAIT, min(display_time, MAX_DISPLAY_WAIT))

    try:
        # 0. 解析股票代码/名称
        resolved_code, resolved_name, success = resolve_stock_code(code)
        if not success:
            yield f"data: {json.dumps({'event': 'error', 'message': f'未找到股票: {code}'})}\n\n"
            return

        # 使用解析后的代码
        code = resolved_code
        stock_display_name = f"{resolved_name} ({code})" if resolved_name else code

        # 1. 获取缠论分析数据
        ChanAnalyzer = import_chan_analyzer()
        analyzer = ChanAnalyzer(code=code)

        analysis = analyzer.get_analysis()

        # 2. 获取资金流向
        money_flow = None
        try:
            sector_flow = import_sector_flow()
            money_flow = sector_flow.get_stock_money_flow(code, days=5)
        except Exception as e:
            print(f"资金流向获取失败: {e}")

        # 3. 创建多AI分析器
        MultiAIAnalyzer = import_multi_ai_analyzer()
        ai_analyzer = MultiAIAnalyzer()

        # 4. 格式化分析数据
        analysis_data = ai_analyzer.format_analysis_data(analysis, money_flow)

        # 5. 阶段控制：并行计算 -> 顺序推送分析师 -> 决策者
        import time
        from concurrent.futures import ThreadPoolExecutor

        # 获取温度配置
        temp_a = temperatures.get('analyst_a', 0.4) if temperatures else 0.4
        temp_b = temperatures.get('analyst_b', 0.7) if temperatures else 0.7
        temp_d = temperatures.get('decision_maker', 0.3) if temperatures else 0.3

        # 加载提示词模块
        from ChanAnalyzer.prompts.analyst import get_analyst_system_prompt, get_analyst_user_prompt
        from ChanAnalyzer.prompts.decision_maker import get_decision_maker_system_prompt, get_decision_maker_user_prompt

        # 获取分析师模型列表
        models = ai_analyzer.config['analysts']['models']

        # 定义分析师任务
        def run_analyst(analyst_id, temperature):
            system_prompt = get_analyst_system_prompt()
            user_prompt = get_analyst_user_prompt(analysis_data, analyst_id + 1)
            response = ai_analyzer.client.chat.completions.create(
                model=models[analyst_id] if analyst_id < len(models) else models[-1],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=ai_analyzer.config['analysts']['max_tokens'],
            )

            return analyst_id, response.choices[0].message.content

        # ========== 阶段1：并行计算（不推送事件） ==========
        start_time = time.time()
        results = {}

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(run_analyst, 0, temp_a)
            future_b = executor.submit(run_analyst, 1, temp_b)

            # 等待两个分析师都完成（这里只计算，不发消息）
            try:
                results[0] = future_a.result()
                results[1] = future_b.result()
            except Exception as e:
                print(f"分析师分析失败: {e}")
                yield f"data: {json.dumps({'event': 'error', 'message': f'分析师分析失败: {str(e)}'})}\n\n"
                return

        analyst_time = time.time() - start_time

        # ========== 阶段2：按顺序推送分析师（先A后B），并等待打字机效果 ==========
        analyst_opinions = []

        # 发送分析师A开始和完成
        yield f"data: {json.dumps({'event': 'analyst_start', 'analyst_id': 0, 'analyst_name': '分析师A'})}\n\n"
        a_id, a_opinion = results[0]
        analyst_opinions.append({
            'analyst_id': a_id,
            'analyst_name': '分析师A',
            'model': models[0] if len(models) > 0 else models[-1],
            'temperature': temp_a,
            'opinion': a_opinion
        })
        yield f"data: {json.dumps({'event': 'analyst_done', 'analyst_id': 0, 'analyst_name': '分析师A', 'opinion': a_opinion})}\n\n"

        # 等待分析师A的打字机效果完成
        wait_time_a = calculate_display_time(a_opinion)
        await asyncio.sleep(wait_time_a)

        # 发送分析师B开始和完成
        yield f"data: {json.dumps({'event': 'analyst_start', 'analyst_id': 1, 'analyst_name': '分析师B'})}\n\n"
        b_id, b_opinion = results[1]
        analyst_opinions.append({
            'analyst_id': b_id,
            'analyst_name': '分析师B',
            'model': models[1] if len(models) > 1 else models[-1],
            'temperature': temp_b,
            'opinion': b_opinion
        })
        yield f"data: {json.dumps({'event': 'analyst_done', 'analyst_id': 1, 'analyst_name': '分析师B', 'opinion': b_opinion})}\n\n"

        # 等待分析师B的打字机效果完成
        wait_time_b = calculate_display_time(b_opinion)
        await asyncio.sleep(wait_time_b)

        # 两个分析师都完成后，发送决策开始事件
        yield f"data: {json.dumps({'event': 'decision_start'})}\n\n"

        start_time = time.time()

        # 构造 AnalystOpinion 对象供决策者提示词使用
        from types import SimpleNamespace
        opinion_objects = [
            SimpleNamespace(
                analyst_name=op['analyst_name'],
                temperature=op['temperature'],
                opinion=op['opinion']
            )
            for op in analyst_opinions
        ]
        decision_system = get_decision_maker_system_prompt()
        decision_prompt = get_decision_maker_user_prompt(opinion_objects)

        response = ai_analyzer.client.chat.completions.create(
            model=ai_analyzer.config['decision_maker']['model'],
            messages=[
                {"role": "system", "content": decision_system},
                {"role": "user", "content": decision_prompt}
            ],
            temperature=temp_d,
            max_tokens=ai_analyzer.config['decision_maker']['max_tokens'],
        )

        decision = response.choices[0].message.content
        decision_time = time.time() - start_time

        # 7. 发送完成事件
        timing = {
            'analysts': analyst_time,
            'decision_maker': decision_time,
            'total': analyst_time + decision_time
        }

        yield f"data: {json.dumps({'event': 'decision_done', 'decision': decision, 'timing': timing})}\n\n"
        yield f"data: {json.dumps({'event': 'complete', 'status': 'done'})}\n\n"

    except Exception as e:
        import traceback
        traceback.print_exc()
        yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
        yield f"data: {json.dumps({'event': 'complete', 'status': 'error'})}\n\n"


@app.post("/api/stock/analyze")
async def analyze_stock(request: AnalyzeRequest):
    """
    个股分析接口 (SSE 流式输出)

    请求体:
    {
        "code": "000001",
        "temperatures": {
            "analyst_a": 0.4,
            "analyst_b": 0.7,
            "decision_maker": 0.3
        }
    }
    """
    return StreamingResponse(
        stream_analyze_stock(
            code=request.code,
            temperatures=request.temperatures
        ),
        media_type="text/event-stream"
    )


@app.get("/api/industries")
async def get_industries():
    """获取行业列表"""
    try:
        StockPool = import_stock_pool()
        pool = StockPool()
        industries = pool.get_industries()
        return {"industries": industries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
