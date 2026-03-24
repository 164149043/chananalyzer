"""
K线数据管理器

负责 K 线数据的缓存、增量更新和合并。
"""
import os
from datetime import datetime, timedelta
from typing import Iterable, Optional, List
import logging

from sqlalchemy.orm import Session

from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from ChanAnalyzer.database import (
    KLineData, get_db, init_db,
    get_kl_type_str, parse_kl_type_str
)

logger = logging.getLogger(__name__)


class DataManager:
    """
    K线数据管理器

    功能：
    1. 从 SQLite 缓存读取历史数据
    2. 判断数据是否新鲜
    3. 增量获取新数据
    4. 合并并存储
    """

    def __init__(self, db_url: Optional[str] = None):
        """
        初始化数据管理器

        Args:
            db_url: 数据库连接字符串，默认从环境变量读取
        """
        # 确保数据库已初始化
        init_db()

        # 数据新鲜度配置
        self.fresh_threshold_hours = 2  # 交易时间内，2小时内的数据视为新鲜

    def get_kl_data(
        self,
        code: str,
        kl_type: KL_TYPE,
        begin_date: str,
        end_date: str,
        data_src_fetcher: callable = None
    ) -> Iterable[CKLine_Unit]:
        """
        获取 K 线数据（优先从缓存）

        Args:
            code: 股票代码
            kl_type: 周期类型
            begin_date: 开始日期
            end_date: 结束日期
            data_src_fetcher: 数据源获取函数，签名为 f(code, kl_type, begin, end) -> Iterable[CKLine_Unit]

        Returns:
            K线单元的迭代器
        """
        if data_src_fetcher is None:
            # 如果没有提供数据源，直接返回空（需要由调用者提供）
            logger.warning("未提供数据源，无法获取数据")
            return []

        kl_type_str = get_kl_type_str(kl_type)

        # 1. 尝试从缓存获取
        cached_data = self._get_from_cache(code, kl_type_str, begin_date, end_date)

        # 2. 判断是否需要更新
        if cached_data and self._is_fresh(cached_data, end_date):
            logger.info(f"[{code} {kl_type_str}] 使用缓存数据")
            return self._to_klu_list(cached_data)

        # 3. 获取增量数据
        last_date = self._get_last_date(cached_data)
        fetch_start = last_date if last_date else begin_date

        logger.info(f"[{code} {kl_type_str}] 从 API 获取数据: {fetch_start} ~ {end_date}")
        new_data_list = list(data_src_fetcher(code, kl_type, fetch_start, end_date))

        if not new_data_list:
            # API 没有返回数据，使用缓存
            if cached_data:
                logger.warning(f"[{code} {kl_type_str}] API 无数据，使用缓存")
                return self._to_klu_list(cached_data)
            return []

        # 4. 合并数据
        new_cached_data = self._merge_and_save(
            code, kl_type_str,
            cached_data, new_data_list,
            begin_date, end_date
        )

        return self._to_klu_list(new_cached_data)

    def _get_from_cache(
        self,
        code: str,
        kl_type_str: str,
        begin_date: str,
        end_date: str
    ) -> List[KLineData]:
        """从缓存获取数据"""
        with get_db() as db:
            query = db.query(KLineData).filter(
                KLineData.code == code,
                KLineData.kl_type == kl_type_str,
            )

            # 添加日期范围过滤
            if begin_date:
                begin_dt = datetime.fromisoformat(begin_date.replace('-', '').replace(
                    lambda x: x[0]+'-'+x[1:3]+'-'+x[3:5] if len(x) == 8 else x
                ) if '-' not in begin_date else begin_date)
                # 简化处理：这里假设输入是 YYYY-MM-DD 或 YYYYMMDD 格式
                # 实际使用时可以优化
            if end_date:
                # 同样简化
                pass

            # 按时间排序
            query = query.order_by(KLineData.timestamp)

            results = query.all()

            # 在内存中过滤日期范围（因为 date 字段格式复杂）
            if begin_date or end_date:
                filtered = []
                for row in results:
                    # 简化：直接返回所有，后续在应用层过滤
                    filtered.append(row)
                results = filtered

            return results

    def _is_fresh(self, cached_data: List[KLineData], request_end_date: str) -> bool:
        """判断缓存数据是否新鲜"""
        if not cached_data:
            return False

        last_row = cached_data[-1]
        last_date = last_row.timestamp.date()
        today = datetime.now().date()

        # 如果缓存最新数据是今天
        if last_date == today:
            # 交易时间内（9:30-15:00），需要检查时间
            now = datetime.now()
            if now.hour < 15:
                # 15:00 之前，检查数据时间是否在阈值内
                time_diff = now - last_row.timestamp
                if time_diff.total_seconds() < self.fresh_threshold_hours * 3600:
                    return True
                return False
            else:
                # 15:00 之后，认为数据是完整的
                return True

        # 如果缓存最新数据不是今天，总是尝试更新
        # 让 API 去判断是否有新的交易日数据
        return False

    def _get_last_date(self, cached_data: List[KLineData]) -> Optional[str]:
        """获取缓存中最新数据的日期"""
        if not cached_data:
            return None
        last_row = cached_data[-1]
        # 返回下一天的日期作为增量获取的起点
        next_day = last_row.timestamp + timedelta(days=1)
        return next_day.strftime("%Y-%m-%d")

    def _merge_and_save(
        self,
        code: str,
        kl_type_str: str,
        cached_data: List[KLineData],
        new_klu_list: List[CKLine_Unit],
        begin_date: str,
        end_date: str
    ) -> List[KLineData]:
        """
        合并数据并保存到缓存

        策略：
        1. 将新的 KLU 列表转换为 KLineData
        2. 删除缓存中与新增数据日期重叠的部分
        3. 合并并保存
        """
        with get_db() as db:
            # 转换新数据
            new_rows = []
            new_dates = set()

            for klu in new_klu_list:
                row = KLineData.from_klu(klu, code, parse_kl_type_str(kl_type_str))
                new_rows.append(row)
                new_dates.add(row.date)

            # 删除重叠数据
            if new_dates:
                db.query(KLineData).filter(
                    KLineData.code == code,
                    KLineData.kl_type == kl_type_str,
                    KLineData.date.in_(new_dates)
                ).delete(synchronize_session=False)

            # 批量插入
            db.bulk_save_objects(new_rows)
            db.commit()

            logger.info(f"[{code} {kl_type_str}] 缓存更新: 新增 {len(new_rows)} 条")

            # 返回合并后的数据
            return db.query(KLineData).filter(
                KLineData.code == code,
                KLineData.kl_type == kl_type_str,
            ).order_by(KLineData.timestamp).all()

    def _to_klu_list(self, kline_data_list: List[KLineData]) -> Iterable[CKLine_Unit]:
        """将 KLineData 列表转换为 CKLine_Unit 迭代器"""
        for row in kline_data_list:
            klu_dict = {
                DATA_FIELD.FIELD_TIME: CTime(
                    row.timestamp.year,
                    row.timestamp.month,
                    row.timestamp.day,
                    row.timestamp.hour,
                    row.timestamp.minute
                ),
                DATA_FIELD.FIELD_OPEN: row.open,
                DATA_FIELD.FIELD_HIGH: row.high,
                DATA_FIELD.FIELD_LOW: row.low,
                DATA_FIELD.FIELD_CLOSE: row.close,
                DATA_FIELD.FIELD_VOLUME: row.volume,
            }

            # 可选字段
            if row.amount is not None:
                klu_dict[DATA_FIELD.FIELD_TURNOVER] = row.amount
            if row.turnover_rate is not None:
                klu_dict[DATA_FIELD.FIELD_TURNRATE] = row.turnover_rate

            yield CKLine_Unit(klu_dict)

    def get_cache_info(self, code: str, kl_type: KL_TYPE) -> dict:
        """获取缓存信息"""
        kl_type_str = get_kl_type_str(kl_type)
        with get_db() as db:
            count = db.query(KLineData).filter(
                KLineData.code == code,
                KLineData.kl_type == kl_type_str
            ).count()

            if count == 0:
                return {"exists": False}

            first = db.query(KLineData).filter(
                KLineData.code == code,
                KLineData.kl_type == kl_type_str
            ).order_by(KLineData.timestamp).first()

            last = db.query(KLineData).filter(
                KLineData.code == code,
                KLineData.kl_type == kl_type_str
            ).order_by(KLineData.timestamp.desc()).first()

            return {
                "exists": True,
                "count": count,
                "first_date": first.date if first else None,
                "last_date": last.date if last else None,
            }

    def clear_cache(self, code: Optional[str] = None, kl_type: Optional[KL_TYPE] = None):
        """清除缓存"""
        with get_db() as db:
            query = db.query(KLineData)

            if code:
                query = query.filter(KLineData.code == code)

            if kl_type:
                query = query.filter(KLineData.kl_type == get_kl_type_str(kl_type))

            count = query.count()
            query.delete(synchronize_session=False)
            db.commit()

            logger.info(f"清除缓存: {count} 条记录")


# 全局单例
_data_manager: Optional[DataManager] = None


def get_data_manager() -> DataManager:
    """获取全局数据管理器实例"""
    global _data_manager
    if _data_manager is None:
        _data_manager = DataManager()
    return _data_manager


# 导出便捷访问
data_manager = get_data_manager()
