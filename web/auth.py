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
from sqlalchemy import or_
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
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')  # 可选：管理员邮箱(用于邮箱登录)

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


def register_user(db: Session, username: str, password: str, email: Optional[str] = None) -> User:
    """
    注册新用户（可选绑定邮箱，单事务写入）

    新用户 status='pending'：可登录浏览，AI 分析与扫描功能需管理员审核通过后使用。

    Args:
        email: 注册邮箱（已小写），传入则在创建时一并绑定；并发唯一冲突会抛 IntegrityError

    Raises:
        HTTPException(400): 用户名格式错误 / 已存在 / 密码过短
        IntegrityError: 并发场景下用户名/邮箱唯一约束冲突（由调用方捕获转友好提示）
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
        status='pending',
        email=email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    """验证 邮箱/用户名 + 密码，返回 User 或 None

    仅 status='disabled' 拒绝登录；pending 可登录（浏览功能，AI/扫描由
    usage.assert_approved 拦截）。
    username 参数实际可为邮箱或用户名(兼容管理员账号、早期无邮箱用户)。
    """
    if not username or not password:
        return None
    account = username.strip()
    # 邮箱(小写匹配,邮箱存储时已统一小写)或用户名(精确)任一命中
    user = db.query(User).filter(
        or_(User.username == account, User.email == account.lower())
    ).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    if user.status == 'disabled':
        return None
    user.last_login_at = datetime.now()
    db.commit()
    return user


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def ensure_admin_account(db: Session) -> None:
    """
    引导 .env 管理员账号到数据库(startup 调用)

    admin 不存在则按 .env 创建;已存在则确保 role=admin,
    并在 .env 的 ADMIN_PASSWORD 与库中哈希不一致时同步覆盖
    (改 .env → 重启即用新密码生效;代价:网页端改过的 admin 密码重启后会被 .env 覆盖),
    以及 .env 配了 ADMIN_EMAIL 且该账号尚无邮箱时补绑邮箱。
    """
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        return
    existing = db.query(User).filter(User.username == ADMIN_USERNAME).first()
    if existing:
        changed = False
        if existing.role != 'admin':
            existing.role = 'admin'
            changed = True
        # 同步密码:.env 的 ADMIN_PASSWORD 与库中哈希不一致时覆盖,
        # 让"改 .env → 重启"对新密码立即生效
        if not verify_password(ADMIN_PASSWORD, existing.password_hash):
            existing.password_hash = hash_password(ADMIN_PASSWORD)
            changed = True
        # 补绑邮箱(若 .env 配了 ADMIN_EMAIL 且当前无邮箱,且邮箱未被他人占用)
        if ADMIN_EMAIL and not existing.email:
            clash = db.query(User).filter(
                User.email == ADMIN_EMAIL, User.id != existing.id
            ).first()
            if not clash:
                existing.email = ADMIN_EMAIL
                changed = True
        if changed:
            db.commit()
        return
    admin = User(
        username=ADMIN_USERNAME,
        password_hash=hash_password(ADMIN_PASSWORD),
        role='admin',
        status='active',
        email=ADMIN_EMAIL or None,
    )
    db.add(admin)
    db.commit()


# ============ Token ============

def create_token(user: User) -> str:
    """为用户签发 JWT（携带当前 token_version，改密/找回后旧 token 立即失效）"""
    return create_jwt(user.id, user.role, user.token_version)


def verify_token(token: str, db: Session) -> Optional[int]:
    """校验 token，返回 user_id(int) 或 None（disabled 用户 token 失效；pending 放行）"""
    payload = decode_jwt(token)
    if not payload:
        return None
    try:
        user_id = int(payload.get('sub'))
    except (TypeError, ValueError):
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.status == 'disabled':
        return None
    # token 版本号严格比对：改密/找回后 token_version +1，该用户所有旧 token 即时失效
    if payload.get('token_version') != user.token_version:
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
