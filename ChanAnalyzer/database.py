"""
K线数据缓存 - 数据库模型

使用 SQLite 存储历史 K 线数据，实现增量更新和本地缓存。
"""
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Index, UniqueConstraint, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from Common.CEnum import KL_TYPE, DATA_FIELD

# 数据库配置
DEFAULT_DB_URL = "sqlite:///./chan.db"
DB_URL = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)

# 创建引擎
engine = create_engine(
    DB_URL,
    echo=False,  # 设置为 True 可查看 SQL 语句
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
)

# 创建基类
Base = declarative_base()

# 创建 Session 工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db() -> Session:
    """获取数据库会话（上下文管理器）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库（建表 + 幂等迁移）"""
    Base.metadata.create_all(bind=engine)
    _migrate_users_credits()


def _migrate_users_credits():
    """幂等迁移：为已存在的 users 表补 credits 列（create_all 不会给老表加列）"""
    insp = inspect(engine)
    if not insp.has_table('users'):
        return  # 全新部署：create_all 已建含 credits 的完整表
    if 'credits' in [c['name'] for c in insp.get_columns('users')]:
        return  # 已迁移，跳过
    # SQLite ADD COLUMN 配 NOT NULL 必须带 DEFAULT，此处符合
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN credits INTEGER NOT NULL DEFAULT 0"))


class KLineData(Base):
    """K线数据表"""
    __tablename__ = "kline_data"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 股票信息
    code = Column(String(10), nullable=False, index=True)  # 股票代码，如 000001
    kl_type = Column(String(10), nullable=False, index=True)  # 周期类型: DAY, WEEK, MON 等

    # 时间
    date = Column(String(20), nullable=False)  # 日期 YYYY-MM-DD HH:MM:SS
    timestamp = Column(DateTime, nullable=False)  # 时间戳（用于排序和比较）

    # OHLCV 数据
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)  # 成交量
    amount = Column(Float, nullable=True)  # 成交额
    turnover_rate = Column(Float, nullable=True)  # 换手率

    # 元数据
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 复合唯一索引和普通索引
    __table_args__ = (
        UniqueConstraint('code', 'kl_type', 'date', name='uix_code_kltype_date'),
        Index('idx_code_kltype_timestamp', 'code', 'kl_type', 'timestamp'),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'code': self.code,
            'kl_type': self.kl_type,
            'date': self.date,
            'timestamp': self.timestamp,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'amount': self.amount or 0,
            'turnover_rate': self.turnover_rate,
        }

    @classmethod
    def from_klu(cls, klu, code: str, kl_type: KL_TYPE):
        """从 CKLine_Unit 创建实例"""
        kl_type_str = KL_TYPE_NAME.get(kl_type, str(kl_type))

        # 交易数据存储在 trade_info.metric 中
        volume = 0
        amount = None
        turnover_rate = None

        if hasattr(klu, 'trade_info') and klu.trade_info:
            volume = klu.trade_info.metric.get(DATA_FIELD.FIELD_VOLUME, 0) or 0
            amount = klu.trade_info.metric.get(DATA_FIELD.FIELD_TURNOVER)
            turnover_rate = klu.trade_info.metric.get(DATA_FIELD.FIELD_TURNRATE)

        return cls(
            code=code,
            kl_type=kl_type_str,
            date=klu.time.to_str(),
            timestamp=datetime(
                klu.time.year, klu.time.month, klu.time.day,
                klu.time.hour, klu.time.minute
            ),
            open=float(klu.open),
            high=float(klu.high),
            low=float(klu.low),
            close=float(klu.close),
            volume=float(volume) if volume else 0,
            amount=float(amount) if amount else None,
            turnover_rate=float(turnover_rate) if turnover_rate else None,
        )


# 周期类型名称映射
KL_TYPE_NAME = {
    KL_TYPE.K_1M: "1M",
    KL_TYPE.K_5M: "5M",
    KL_TYPE.K_15M: "15M",
    KL_TYPE.K_30M: "30M",
    KL_TYPE.K_DAY: "DAY",
    KL_TYPE.K_WEEK: "WEEK",
    KL_TYPE.K_MON: "MON",
    KL_TYPE.K_YEAR: "YEAR",
}


def get_kl_type_str(kl_type: KL_TYPE) -> str:
    """获取周期类型字符串"""
    return KL_TYPE_NAME.get(kl_type, str(kl_type))


def parse_kl_type_str(kl_type_str: str) -> KL_TYPE:
    """从字符串解析周期类型"""
    for k, v in KL_TYPE_NAME.items():
        if v == kl_type_str:
            return k
    raise ValueError(f"Unknown kl_type: {kl_type_str}")


class User(Base):
    """用户表（注册登录）"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(32), nullable=False, unique=True, index=True)  # 登录名
    password_hash = Column(String(128), nullable=False)  # bcrypt 哈希
    role = Column(String(16), nullable=False, default='user')  # 'user' | 'admin'
    status = Column(String(16), nullable=False, default='active')  # 'active' | 'disabled'
    credits = Column(Integer, nullable=False, default=0)  # 积分余额
    created_at = Column(DateTime, default=datetime.now)
    last_login_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'status': self.status,
            'credits': self.credits,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
        }


class CreditTransaction(Base):
    """积分变动流水（管理员调整积分时留痕）"""
    __tablename__ = "credit_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(Integer, nullable=False, index=True)          # 操作人(管理员 user_id)
    target_user_id = Column(Integer, nullable=False, index=True)    # 被操作用户 id
    delta = Column(Integer, nullable=False)                          # 变动额 +/-
    balance_after = Column(Integer, nullable=False)                  # 变动后余额(快照)
    reason = Column(String(255), nullable=False)                     # 变动原因
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index('idx_target_user_created', 'target_user_id', 'created_at'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'admin_id': self.admin_id,
            'target_user_id': self.target_user_id,
            'delta': self.delta,
            'balance_after': self.balance_after,
            'reason': self.reason,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
