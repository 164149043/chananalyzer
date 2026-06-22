"""
用户认证管理模块（注册登录 + 强制登录）

- bcrypt 密码哈希 + PyJWT 标准 token
- 基于 SQLite users 表
- 强制登录：无 token / 无效 token / 用户被禁用 → 401
"""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

from web.security import (
    hash_password,
    verify_password,
    create_jwt,
    decode_jwt,
)
from ChanAnalyzer.database import get_db, User

load_dotenv()

# 管理员账号配置（首启引导用，从 .env 读取）
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

# 用户名校验：3-32 位字母数字下划线
_USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{3,32}$')
MIN_PASSWORD_LENGTH = 6

# 用户扫描缓存文件存储目录（保留原行为）
USER_DATA_DIR = Path(__file__).parent / "users"
USER_DATA_DIR.mkdir(exist_ok=True)


# ============ 用户管理 ============

def validate_username(username: str) -> Optional[str]:
    """校验用户名，返回错误信息或 None"""
    if not username:
        return "用户名不能为空"
    if not _USERNAME_RE.match(username):
        return "用户名为 3-32 位字母、数字或下划线"
    return None


def register_user(db: Session, username: str, password: str) -> User:
    """
    注册新用户

    Raises:
        HTTPException(400): 用户名格式错误 / 已存在 / 密码过短
    """
    err = validate_username(username)
    if err:
        raise HTTPException(status_code=400, detail=err)
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"密码至少 {MIN_PASSWORD_LENGTH} 位")

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = User(
        username=username,
        password_hash=hash_password(password),
        role='user',
        status='active',
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    """验证用户名密码，返回 User 或 None；仅 status='active' 可登录"""
    if not username or not password:
        return None
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    if user.status != 'active':
        return None
    user.last_login_at = datetime.now()
    db.commit()
    return user


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def ensure_admin_account(db: Session) -> None:
    """
    首启引导 .env 管理员账号到数据库

    若 users 表无该 admin 用户则创建，保证现有管理员登录不中断。
    """
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        return
    existing = db.query(User).filter(User.username == ADMIN_USERNAME).first()
    if existing:
        if existing.role != 'admin':
            existing.role = 'admin'
            db.commit()
        return
    admin = User(
        username=ADMIN_USERNAME,
        password_hash=hash_password(ADMIN_PASSWORD),
        role='admin',
        status='active',
    )
    db.add(admin)
    db.commit()


# ============ Token ============

def create_token(user: User) -> str:
    """为用户签发 JWT"""
    return create_jwt(user.id, user.role)


def verify_token(token: str, db: Session) -> Optional[int]:
    """校验 token，返回 user_id(int) 或 None"""
    payload = decode_jwt(token)
    if not payload:
        return None
    try:
        user_id = int(payload.get('sub'))
    except (TypeError, ValueError):
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.status != 'active':
        return None
    return user_id


# ============ 用户缓存文件路径（保留原行为）============

def get_user_cache_file(user_id, scan_type: str) -> Path:
    """获取用户的扫描缓存文件路径"""
    return USER_DATA_DIR / f"{scan_type}_scan_{user_id}.json"


def get_user_status_file(user_id, scan_type: str) -> Path:
    """获取用户的扫描状态文件路径"""
    return USER_DATA_DIR / f"{scan_type}_status_{user_id}.json"


# ============ FastAPI 依赖 ============

async def get_current_user(authorization: str = Header(None)) -> int:
    """
    FastAPI 依赖：获取当前用户 id（int）

    无 token / 无效 token / 用户被禁用 → 401
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="未登录，请先登录")
    token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    with get_db() as db:
        user_id = verify_token(token, db)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return user_id


async def get_current_admin(user_id: int = Depends(get_current_user)) -> int:
    """
    FastAPI 依赖：要求当前用户为 admin，否则 403。

    复用 get_current_user 完成 token + status 校验，再查库验证 role
    （不信任 JWT 中的 role 字段，防篡改）。返回 admin 的 user_id。
    """
    with get_db() as db:
        user = get_user_by_id(db, user_id)
        if not user or user.role != 'admin':
            raise HTTPException(status_code=403, detail="需要管理员权限")
    return user_id
