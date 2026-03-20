"""
Tushare 数据源接口

使用 Tushare Pro API 获取 A 股历史 K 线数据。

依赖:
    tushare>=1.2.60

环境变量:
    TUSHARE_TOKEN: Tushare Pro API Token (必填)

使用方法:
    export TUSHARE_TOKEN=your_token_here
    或者手动设置: ts.set_token('your_token')
"""
import os
from typing import Iterable

import pandas as pd
import tushare as ts

# 修复权限问题：Monkey patch tushare，强制使用 /tmp/tk.csv
# tushare 原始代码会写入 ~/tk.csv，在云环境中可能没有权限

# Patch 1: set_token - 写入 /tmp/tk.csv
_original_set_token = ts.set_token
def _patched_set_token(token):
    """修复后的 set_token 函数，使用 /tmp 目录"""
    import pandas as pd
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
ts.set_token = _patched_set_token

# Patch 2: pro_api - 从 /tmp/tk.csv 读取 token
_original_pro_api = ts.pro_api
def _patched_pro_api(token=None):
    """修复后的 pro_api 函数，从 /tmp 读取 token"""
    import pandas as pd
    import os
    # 如果传入了 token，直接使用
    if token:
        return _original_pro_api(token=token)
    # 否则尝试从 /tmp/tk.csv 读取
    fp = '/tmp/tk.csv'
    if os.path.exists(fp):
        df = pd.read_csv(fp)
        token = df['token'][0]
        return _original_pro_api(token=token)
    else:
        # 回退到原始行为（会抛出异常）
        return _original_pro_api()
ts.pro_api = _patched_pro_api

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi


def _ensure_token():
    """确保 Tushare Token 已设置"""
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise ValueError(
            "请设置 TUSHARE_TOKEN 环境变量。\n"
            "获取 token: https://tushare.pro/user/token"
        )
    # 调用我们 patch 过的 set_token，会写入 /tmp/tk.csv
    ts.set_token(token)


def _create_item_dict(row: pd.Series, autype: AUTYPE) -> dict:
    """将 Tushare DataFrame 行转换为 K 线单元所需的字典格式

    Args:
        row: Tushare 返回的 DataFrame 一行数据
        autype: 复权类型

    Returns:
        dict: CKLine_Unit 所需的数据字典
    """
    # Tushare 返回的日期格式:
    # - 日线/周线/月线: trade_date = 20210101
    # - 分钟线: trade_time = 20210101 09:30:00
    time_col = 'trade_time' if 'trade_time' in row.index else 'trade_date'
    time_str = str(row[time_col])

    # 处理时间格式
    if ' ' in time_str:  # 分钟级数据: "20210101 09:30:00"
        date_part, time_part = time_str.split(' ')
        year = int(date_part[:4])
        month = int(date_part[4:6])
        day = int(date_part[6:8])
        hour = int(time_part.split(':')[0])
        minute = int(time_part.split(':')[1])
    else:  # 日线/周线/月线数据: "20210101"
        year = int(time_str[:4])
        month = int(time_str[4:6])
        day = int(time_str[6:8])
        hour = 0
        minute = 0

    item = {
        DATA_FIELD.FIELD_TIME: CTime(year, month, day, hour, minute),
        DATA_FIELD.FIELD_OPEN: float(row['open']),
        DATA_FIELD.FIELD_HIGH: float(row['high']),
        DATA_FIELD.FIELD_LOW: float(row['low']),
        DATA_FIELD.FIELD_CLOSE: float(row['close']),
        DATA_FIELD.FIELD_VOLUME: float(row['vol']),
        DATA_FIELD.FIELD_TURNOVER: float(row.get('amount', 0)),  # 成交额(千元)
    }

    # 换手率 - daily_basic 接口才有
    if 'turnover_rate' in row:
        item[DATA_FIELD.FIELD_TURNRATE] = float(row['turnover_rate'])

    return item


class CTushareAPI(CCommonStockApi):
    """使用 Tushare Pro API 获取 A 股数据

    支持:
        - 日线、周线、月线数据
        - 前复权、后复权、不复权
        - 个股和指数数据

    示例:
        >>> import os
        >>> os.environ['TUSHARE_TOKEN'] = 'your_token'
        >>> api = CTushareAPI('000001', KL_TYPE.K_DAY, '2020-01-01', '2021-12-31')
        >>> for kline in api.get_kl_data():
        ...     print(kline)
    """

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        """
        初始化 Tushare 数据接口

        Args:
            code: 股票代码，支持以下格式:
                - 000001 (平安银行)
                - sz000001 / sh600000
            k_type: K线周期类型
            begin_date: 开始日期 (YYYY-MM-DD 或 YYYYMMDD)
            end_date: 结束日期 (YYYY-MM-DD 或 YYYYMMDD)
            autype: 复权类型
        """
        _ensure_token()
        super(CTushareAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        self.pro = ts.pro_api()

    def get_kl_data(self) -> Iterable[CKLine_Unit]:
        """获取 K 线数据

        Yields:
            CKLine_Unit: K线单元对象
        """
        # 转换股票代码格式: 000001 -> 000001.SZ
        ts_code = self._convert_code_format()

        # 格式化日期
        start_date = self._format_date(self.begin_date) if self.begin_date else "20000101"
        end_date = self._format_date(self.end_date) if self.end_date else "21000101"

        # 选择 API 接口
        if self.is_stock:
            df = self._get_stock_data(ts_code, start_date, end_date)
        else:
            df = self._get_index_data(ts_code, start_date, end_date)

        if df is None or df.empty:
            return

        # 按日期/时间排序 (分钟数据使用 trade_time，日线/周线/月线使用 trade_date)
        sort_col = 'trade_time' if 'trade_time' in df.columns else 'trade_date'
        df = df.sort_values(sort_col)

        # 遍历每一行生成 K 线单元
        for _, row in df.iterrows():
            yield CKLine_Unit(_create_item_dict(row, self.autype))

    def _get_stock_data(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取个股数据"""
        # 周期映射
        ts_freq = self._convert_freq()

        try:
            if ts_freq == 'D':
                # 日线数据
                df = self.pro.daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date
                )
            elif ts_freq == 'W':
                # 周线数据
                df = self.pro.weekly(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date
                )
            elif ts_freq == 'M':
                # 月线数据
                df = self.pro.monthly(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date
                )
            elif 'min' in ts_freq:
                # 分钟级数据使用 stk_mins 接口
                # 注意：stk_mins 不支持复权，且数据格式可能不同
                df = self.pro.stk_mins(
                    ts_code=ts_code,
                    freq=ts_freq,
                    start_date=start_date,
                    end_date=end_date
                )
            else:
                raise ValueError(f"不支持的周期: {ts_freq}")

            return df

        except Exception as e:
            print(f"[Tushare] 获取 {ts_code} 数据失败: {e}")
            return pd.DataFrame()

    def _get_index_data(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取指数数据"""
        try:
            # 指数数据不支持复权
            df = self.pro.index_daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )

            if df is None or df.empty:
                return pd.DataFrame()

            # 重命名列以统一格式
            df = df.rename(columns={
                'cal_date': 'trade_date'
            })

            return df

        except Exception as e:
            print(f"[Tushare] 获取指数 {ts_code} 数据失败: {e}")
            return pd.DataFrame()

    def SetBasciInfo(self):
        """设置基本信息: 判断是否为股票/指数"""
        self.name = self.code

        # 判断是否为指数
        if self.code.startswith('sh') or self.code.startswith('sz'):
            code_num = self.code[2:]
            # 指数代码: 000001(上证), 399001(深证成指) 等
            if code_num.startswith('000') or code_num.startswith('399'):
                self.is_stock = False
            else:
                self.is_stock = True
        else:
            # 纯数字代码默认为股票
            self.is_stock = True

    @classmethod
    def do_init(cls):
        """初始化 Tushare (设置 token)"""
        _ensure_token()

    @classmethod
    def do_close(cls):
        """关闭连接 (Tushare 无需显式关闭)"""
        pass

    def _convert_code_format(self) -> str:
        """转换股票代码为 Tushare 格式

        Examples:
            000001 -> 000001.SZ
            600000 -> 600000.SH
            sh000001 -> 000001.SH (指数)
            sz399001 -> 399001.SZ (指数)
        """
        code = self.code.lower().replace('.', '')

        # 如果已经有前缀
        if code.startswith('sh') or code.startswith('sz'):
            code_num = code[2:]
            suffix = code[:2].upper()
            return f"{code_num}.{suffix}"

        # 纯数字，判断市场
        # 6xxxxx -> 上海, 0xxxxx/3xxxxx -> 深圳
        if code.startswith('6'):
            return f"{code}.SH"
        else:
            return f"{code}.SZ"

    def _format_date(self, date_str: str) -> str:
        """格式化日期为 YYYYMMDD 格式"""
        date_str = date_str.replace('-', '')
        return date_str

    def _convert_freq(self) -> str:
        """转换 K 线周期为 Tushare 频率格式"""
        freq_map = {
            KL_TYPE.K_1M: '1min',
            KL_TYPE.K_5M: '5min',
            KL_TYPE.K_15M: '15min',
            KL_TYPE.K_30M: '30min',
            KL_TYPE.K_60M: '60min',
            KL_TYPE.K_DAY: 'D',
            KL_TYPE.K_WEEK: 'W',
            KL_TYPE.K_MON: 'M',
        }

        if self.k_type not in freq_map:
            raise ValueError(f"Tushare 不支持 {self.k_type} 级别的 K 线数据")

        return freq_map[self.k_type]


# 向后兼容的别名
TushareAPI = CTushareAPI
