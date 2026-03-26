"""
用户会话和认证管理模块

支持简单的JWT Token认证，用于多用户环境下的会话隔离
"""
import os
import uuid
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import Optional
from functools import wraps
import json
from pathlib import Path

# 加载 .env 文件 - 必须在读取环境变量之前调用
load_dotenv()

# 从环境变量读取密钥，或使用默认值
SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'chanalyzer-secret-key-change-in-production')
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

# 管理员账号配置（必须从 .env 文件配置）
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')


def verify_credentials(username: str, password: str) -> bool:
    """
    验证管理员账号密码

    Args:
        username: 用户名
        password: 密码

    Returns:
        验证成功返回 True，否则返回 False
    """
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

# 用户数据存储目录
USER_DATA_DIR = Path(__file__).parent / "users"
USER_DATA_DIR.mkdir(exist_ok=True)


def generate_user_id() -> str:
    """生成新的用户ID"""
    return str(uuid.uuid4())


def create_session_token(user_id: str) -> tuple[str, str]:
    """
    创建会话Token

    Args:
        user_id: 用户ID

    Returns:
        (token, user_id) - 如果用户已存在则返回现有user_id，否则创建新的
    """
    # 如果user_id为空或为'guest'，生成新ID
    if not user_id or user_id == 'guest':
        user_id = generate_user_id()

    # 简单的Token实现（使用user_id + 时间戳的hash）
    # 生产环境应使用标准的jwt库
    token_data = {
        'user_id': user_id,
        'expire': (datetime.now() + timedelta(hours=TOKEN_EXPIRE_HOURS)).isoformat()
    }

    # 将Token数据存储到用户文件中
    user_file = USER_DATA_DIR / f"{user_id}.json"
    user_data = {}
    if user_file.exists():
        with open(user_file, 'r', encoding='utf-8') as f:
            user_data = json.load(f)

    user_data['token'] = _encode_token(token_data)
    user_data['last_active'] = datetime.now().isoformat()

    with open(user_file, 'w', encoding='utf-8') as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2)

    return user_data['token'], user_id


def _encode_token(data: dict) -> str:
    """简单的Token编码（生产环境应使用PyJWT）"""
    import base64
    import hashlib

    json_str = json.dumps(data, separators=(',', ':'))
    signature = hashlib.sha256(f"{json_str}{SECRET_KEY}".encode()).hexdigest()[:16]
    encoded = base64.b64encode(f"{json_str}.{signature}".encode()).decode()
    return encoded


def _decode_token(token: str) -> Optional[dict]:
    """简单的Token解码"""
    import base64
    import hashlib

    try:
        decoded = base64.b64decode(token.encode()).decode()
        json_str, signature = decoded.rsplit('.', 1)

        # 验证签名
        expected_signature = hashlib.sha256(f"{json_str}{SECRET_KEY}".encode()).hexdigest()[:16]
        if signature != expected_signature:
            return None

        data = json.loads(json_str)

        # 检查过期
        expire = datetime.fromisoformat(data['expire'])
        if datetime.now() > expire:
            return None

        return data
    except Exception:
        return None


def verify_token(token: str) -> Optional[str]:
    """
    验证Token并返回user_id

    Args:
        token: 会话Token

    Returns:
        user_id 或 None
    """
    if not token:
        return None

    token_data = _decode_token(token)
    if not token_data:
        return None

    user_id = token_data.get('user_id')
    if not user_id:
        return None

    # 验证用户文件存在
    user_file = USER_DATA_DIR / f"{user_id}.json"
    if not user_file.exists():
        return None

    # 更新最后活跃时间
    try:
        with open(user_file, 'r', encoding='utf-8') as f:
            user_data = json.load(f)
        user_data['last_active'] = datetime.now().isoformat()
        with open(user_file, 'w', encoding='utf-8') as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return user_id


def get_or_create_user(token: Optional[str] = None) -> tuple[str, str]:
    """
    获取或创建用户

    Args:
        token: 客户端传递的Token

    Returns:
        (token, user_id)
    """
    user_id = verify_token(token) if token else None
    return create_session_token(user_id or 'guest')


def get_user_cache_file(user_id: str, scan_type: str) -> Path:
    """
    获取用户的缓存文件路径

    Args:
        user_id: 用户ID
        scan_type: 扫描类型 ('buy' 或 'sell')

    Returns:
        缓存文件路径
    """
    filename = f"{scan_type}_scan_{user_id}.json"
    return USER_DATA_DIR / filename


def get_user_status_file(user_id: str, scan_type: str) -> Path:
    """
    获取用户的状态文件路径

    Args:
        user_id: 用户ID
        scan_type: 扫描类型 ('buy' 或 'sell')

    Returns:
        状态文件路径
    """
    filename = f"{scan_type}_status_{user_id}.json"
    return USER_DATA_DIR / filename


def cleanup_inactive_users(days: int = 7) -> int:
    """
    清理不活跃的用户数据

    Args:
        days: 不活跃天数阈值

    Returns:
        清理的用户数量
    """
    threshold = datetime.now() - timedelta(days=days)
    cleaned = 0

    for user_file in USER_DATA_DIR.glob("*.json"):
        if user_file.name.startswith('buy_') or user_file.name.startswith('sell_'):
            continue  # 跳过缓存文件

        try:
            with open(user_file, 'r', encoding='utf-8') as f:
                user_data = json.load(f)

            last_active = datetime.fromisoformat(user_data.get('last_active', ''))
            if last_active < threshold:
                user_file.unlink()
                # 同时清理该用户的缓存文件
                for cache_file in USER_DATA_DIR.glob(f"*_{user_id}.json"):
                    cache_file.unlink()
                cleaned += 1
        except Exception:
            continue

    return cleaned


# FastAPI依赖
from fastapi import Header, HTTPException


async def get_current_user(authorization: str = Header(None)) -> str:
    """
    FastAPI依赖：获取当前用户ID

    用法:
        @app.get("/api/protected")
        async def protected_endpoint(user_id: str = Depends(get_current_user)):
            ...
    """
    if not authorization:
        # 允许无Token访问，自动创建新用户
        _, user_id = get_or_create_user()
        return user_id

    # 支持两种格式: "Bearer <token>" 或直接token
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization

    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的会话，请刷新页面")

    return user_id
