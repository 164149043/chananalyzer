"""
K线数据缓存 - 数据库模型

使用 SQLite 存储历史 K 线数据，实现增量更新和本地缓存。
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Boolean, Index, UniqueConstraint, inspect, text
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
    _migrate_users_membership()
    _migrate_users_email()
    _migrate_users_token_version()
    _migrate_users_usage()


def _migrate_users_membership():
    """幂等迁移：为老库补 membership_expires_at 列（会员制已废弃，列保留不删，代码不再读写）"""
    insp = inspect(engine)
    if not insp.has_table('users'):
        return  # 全新部署：create_all 已建含该列的完整表
    if 'membership_expires_at' in [c['name'] for c in insp.get_columns('users')]:
        return  # 已迁移，跳过
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN membership_expires_at DATETIME"))


def _migrate_users_usage():
    """幂等迁移：为已存在的 users 表补 AI 每日计数字段（ai_usage_date / ai_usage_count）"""
    insp = inspect(engine)
    if not insp.has_table('users'):
        return  # 全新部署：create_all 已建含该列的完整表
    cols = [c['name'] for c in insp.get_columns('users')]
    with engine.begin() as conn:
        if 'ai_usage_date' not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN ai_usage_date VARCHAR(10)"))
        if 'ai_usage_count' not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN ai_usage_count INTEGER NOT NULL DEFAULT 0"))


def _migrate_users_email():
    """幂等迁移：为已存在的 users 表补 email 列 + 邮箱唯一索引"""
    insp = inspect(engine)
    if not insp.has_table('users'):
        return  # 全新部署：create_all 已建含 email 的完整表
    if 'email' not in [c['name'] for c in insp.get_columns('users')]:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(128)"))
    # 邮箱唯一索引（仅对非 NULL 行生效，允许老用户/管理员 email 为空）
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique "
            "ON users(email) WHERE email IS NOT NULL"
        ))


def _migrate_users_token_version():
    """幂等迁移：为已存在的 users 表补 token_version 列（改密/找回后作废旧 token 的版本号）"""
    insp = inspect(engine)
    if not insp.has_table('users'):
        return  # 全新部署：create_all 已建含该列
    if 'token_version' in [c['name'] for c in insp.get_columns('users')]:
        return  # 已迁移
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1"))


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
    # 'pending'=待管理员审核(可登录,仅能浏览) | 'active'=正常 | 'disabled'=禁用/被拒
    status = Column(String(16), nullable=False, default='pending')
    created_at = Column(DateTime, default=datetime.now)
    last_login_at = Column(DateTime, nullable=True)
    email = Column(String(128), nullable=True, index=True)   # 注册邮箱(唯一, 由 partial unique index 约束)
    token_version = Column(Integer, nullable=False, default=1)  # token 版本号(改密/找回 +1,作废该用户所有旧 token)
    # AI 分析每日用量（自然日重置；admin 不限量）
    ai_usage_date = Column(String(10), nullable=True)             # 计数归属日 'YYYY-MM-DD'
    ai_usage_count = Column(Integer, nullable=False, default=0)   # 当日已用次数

    def to_dict(self) -> dict:
        from web.usage import AI_DAILY_LIMIT, get_ai_remaining
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
            'email': self.email,
            'ai_remaining': get_ai_remaining(self),
            'ai_daily_limit': AI_DAILY_LIMIT,
        }


class VerificationCode(Base):
    """邮箱/手机验证码（注册、找回密码等场景）"""
    __tablename__ = "verification_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target = Column(String(128), nullable=False, index=True)          # 邮箱或手机号
    code = Column(String(8), nullable=False)                           # 验证码
    purpose = Column(String(16), nullable=False, default='register')   # 用途
    expires_at = Column(DateTime, nullable=False)                      # 过期时间
    used = Column(Boolean, nullable=False, default=False)              # 是否已使用
    ip = Column(String(64), nullable=True)                             # 请求来源 IP
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index('idx_vc_target_created', 'target', 'created_at'),
    )
