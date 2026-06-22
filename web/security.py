"""
密码哈希与 JWT 工具

- bcrypt 哈希存储密码
- PyJWT 签发/校验标准 JWT
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'chanalyzer-secret-key-change-in-production')
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = int(os.getenv('JWT_EXPIRE_HOURS', '24'))


def hash_password(plain: str) -> str:
    """bcrypt 哈希密码，返回可存储的字符串"""
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def verify_password(plain: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配"""
    if not plain or not password_hash:
        return False
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), password_hash.encode('utf-8'))
    except (ValueError, TypeError):
        return False


def create_jwt(user_id: int, role: str, expire_hours: int = TOKEN_EXPIRE_HOURS) -> str:
    """签发 JWT，payload 含 sub(user_id)、role、iat、exp"""
    now = datetime.now(timezone.utc)
    payload = {
        'sub': str(user_id),
        'role': role,
        'iat': now,
        'exp': now + timedelta(hours=expire_hours),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> Optional[dict]:
    """解码并校验 JWT，失败（过期/签名错误等）返回 None"""
    if not token:
        return None
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
