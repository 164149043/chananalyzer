"""
缓存数据库数据源接口

使用本地 SQLite 数据库 (chan.db) 获取已缓存的 K 线数据。

依赖:
    sqlite3 (Python 标准库)

数据库表结构:
    kline_data 表包含以下字段:
        - code: 股票代码
        - kl_type: K线类型 (DAY, WEEK)
        - date: 日期
        - timestamp: 时间戳
        - open, high, low, close: OHLC价格
        - volume: 成交量
        - amount: 成交额
        - turnover_rate: 换手率
"""
import os
import sqlite3
from datetime import datetime
from typing import Iterable

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi


def _get_db_path() -> str:
    """获取数据库文件路径"""
    # 默认使用项目根目录下的 chan.db
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    db_path = os.path.join(project_root, "chan.db")

    # 如果项目根目录下没有，尝试当前目录
    if not os.path.exists(db_path):
        db_path = os.path.join(os.getcwd(), "chan.db")

    return db_path


def _create_item_dict(row: tuple, autype: AUTYPE) -> dict:
    """将数据库查询结果转换为 K 线单元所需的字典格式

    Args:
        row: 数据库查询结果的一行 (code, kl_type, date, timestamp, open, high, low, close, volume, amount, turnover_rate, ...)
        autype: 复权类型 (数据库中的数据已复权)

    Returns:
        dict: CKLine_Unit 所需的数据字典
    """
    # 字段顺序: code, kl_type, date, timestamp, open, high, low, close, volume, amount, turnover_rate, created_at, updated_at
    date_str = row[3]  # timestamp 字段

    # 解析时间戳 "2024-01-02 00:00:00.000000"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")

    # 分钟线保留真实时分(bar开始时刻);日线/周线保持 0:00,
    # 使 klu.time.to_str() 维持 "YYYY/MM/DD" 纯日期格式(前端/坐标约定依赖此格式)
    if row[1] in ("5M", "15M", "30M", "60M"):
        hour, minute = dt.hour, dt.minute
    else:
        hour, minute = 0, 0

    item = {
        DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, hour, minute),
        DATA_FIELD.FIELD_OPEN: float(row[4]),   # open
        DATA_FIELD.FIELD_HIGH: float(row[5]),   # high
        DATA_FIELD.FIELD_LOW: float(row[6]),    # low
        DATA_FIELD.FIELD_CLOSE: float(row[7]),  # close
        DATA_FIELD.FIELD_VOLUME: float(row[8]), # volume
        DATA_FIELD.FIELD_TURNOVER: float(row[9]) if row[9] else 0,  # amount
    }

    # 换手率
    if row[10]:  # turnover_rate
        item[DATA_FIELD.FIELD_TURNRATE] = float(row[10])

    return item


def get_stock_list_from_db(db_path: str = None) -> list:
    """从数据库获取所有股票列表

    Args:
        db_path: 数据库路径，默认使用项目根目录下的 chan.db

    Returns:
        list: 股票代码列表，如 ['000001', '000002', ...]
    """
    if db_path is None:
        db_path = _get_db_path()

    if not os.path.exists(db_path):
        return []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT code FROM kline_data WHERE kl_type='DAY' ORDER BY code")
        codes = [row[0] for row in cursor.fetchall()]
        conn.close()
        return codes
    except Exception as e:
        print(f"[CacheDB] 获取股票列表失败: {e}")
        return []


def get_stock_info_from_db(code: str, db_path: str = None) -> dict:
    """从数据库获取单只股票的基本信息

    Args:
        code: 股票代码
        db_path: 数据库路径

    Returns:
        dict: 包含 code, name, latest_price, change 等信息
              查询失败返回 None
    """
    if db_path is None:
        db_path = _get_db_path()

    if not os.path.exists(db_path):
        return None

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 获取最新的K线数据
        cursor.execute(
            "SELECT date, close FROM kline_data WHERE code=? AND kl_type='DAY' ORDER BY date DESC LIMIT 2",
            (code,)
        )
        rows = cursor.fetchall()
        conn.close()

        if len(rows) < 1:
            return None

        latest_close = float(rows[0][1])
        change_pct = 0.0
        if len(rows) >= 2:
            prev_close = float(rows[1][1])
            change_pct = ((latest_close - prev_close) / prev_close) * 100 if prev_close > 0 else 0

        return {
            'code': code,
            'name': code,  # 数据库中没有存储名称，使用代码代替
            'latest_price': latest_close,
            'change': change_pct,
        }
    except Exception as e:
        print(f"[CacheDB] 获取股票信息失败 {code}: {e}")
        return None


class CCacheDBAPI(CCommonStockApi):
    """使用本地 SQLite 数据库获取已缓存的 K 线数据

    支持从 chan.db 数据库读取日线和周线数据。
    数据库中的数据通常是前复权数据。

    示例:
        >>> api = CCacheDBAPI('000001', KL_TYPE.K_DAY, '2020-01-01', '2021-12-31')
        >>> for kline in api.get_kl_data():
        ...     print(kline)
    """

    _conn = None  # 类级别的数据库连接
    _db_path = None

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        """
        初始化缓存数据库接口

        Args:
            code: 股票代码，如 '000001'
            k_type: K线周期类型 (目前支持日线和周线)
            begin_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            autype: 复权类型 (数据库中的数据已复权，此参数仅用于兼容)
        """
        super(CCacheDBAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        self.db_path = _get_db_path()

        if not os.path.exists(self.db_path):
            raise FileNotFoundError(
                f"数据库文件不存在: {self.db_path}\n"
                f"请先运行数据缓存脚本创建数据库。"
            )

    def get_kl_data(self) -> Iterable[CKLine_Unit]:
        """获取 K 线数据

        Yields:
            CKLine_Unit: K线单元对象
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 转换K线类型
            kl_type_str = self._convert_kl_type()

            # 格式化日期
            if self.begin_date:
                start_date = self.begin_date.replace("-", "/")
            else:
                start_date = "2000/01/01"

            if self.end_date:
                end_date = self.end_date.replace("-", "/")
            else:
                end_date = "2099/12/31"

            # 查询数据库
            query = """
                SELECT code, kl_type, date, timestamp, open, high, low, close, volume, amount, turnover_rate, created_at, updated_at
                FROM kline_data
                WHERE code = ? AND kl_type = ? AND date >= ? AND date <= ?
                ORDER BY date ASC
            """

            cursor.execute(query, (self.code, kl_type_str, start_date, end_date))

            for row in cursor.fetchall():
                yield CKLine_Unit(_create_item_dict(row, self.autype))

            conn.close()

        except Exception as e:
            print(f"[CacheDB] 获取 {self.code} 数据失败: {e}")
            return

    def SetBasciInfo(self):
        """设置基本信息"""
        self.name = self.code
        # 默认为股票 (数据库中的数据都是股票)
        self.is_stock = True

    @classmethod
    def do_init(cls):
        """初始化数据库连接 (可选)"""
        cls._db_path = _get_db_path()
        if os.path.exists(cls._db_path):
            cls._conn = sqlite3.connect(cls._db_path)

    @classmethod
    def do_close(cls):
        """关闭数据库连接"""
        if cls._conn:
            cls._conn.close()
            cls._conn = None

    def _convert_kl_type(self) -> str:
        """转换 K 线周期为数据库中的格式"""
        if self.k_type == KL_TYPE.K_DAY:
            return "DAY"
        elif self.k_type == KL_TYPE.K_WEEK:
            return "WEEK"
        elif self.k_type == KL_TYPE.K_MON:
            return "MON"
        elif self.k_type == KL_TYPE.K_5M:
            return "5M"
        elif self.k_type == KL_TYPE.K_15M:
            return "15M"
        elif self.k_type == KL_TYPE.K_30M:
            return "30M"
        elif self.k_type == KL_TYPE.K_60M:
            return "60M"
        else:
            raise ValueError(f"缓存数据库不支持 {self.k_type} 级别的 K 线数据")


# 向后兼容的别名
CacheDBAPI = CCacheDBAPI
