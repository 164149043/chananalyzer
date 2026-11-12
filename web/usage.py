"""
注册审核 + AI 分析每日限额（纯免费制，无会员概念）

- 只依赖 ChanAnalyzer.database，不 import web.auth（避免循环导入，
  与原 membership.py 相同的约束）
- assert_approved：AI/扫描端点入口校验，pending/disabled 抛 403
- consume_ai_usage：原子预扣 1 次（单条 UPDATE 完成检查+扣减，无竞态）
- refund_ai_usage：两位分析师全失败时回退 1 次（客户端断开不回退，
  generator 被 cancel 走不到这里，天然防刷）
- admin 不限量、不受审核约束
"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import text

from ChanAnalyzer.database import User, engine

# 普通用户每日 AI 分析次数上限（可用环境变量覆盖：AI_DAILY_LIMIT）
import os
AI_DAILY_LIMIT = int(os.getenv('AI_DAILY_LIMIT', '5'))


def _get_user(db, user_id):
    """按 id 查用户（内联，避免依赖 web.auth 触发循环导入）"""
    return db.query(User).filter(User.id == int(user_id)).first()


# ============ 审核校验 ============

def assert_approved(db, user_id) -> None:
    """
    功能端点入口校验（AI 分析 / 买卖点扫描 / 智能筛选）：
    admin 放行；pending 抛 403 提示待审核；disabled 抛 403。
    """
    user = _get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    if user.role == 'admin':
        return
    if user.status == 'pending':
        raise HTTPException(status_code=403, detail="账号待管理员审核，审核通过后即可使用 AI 分析与扫描功能")
    if user.status != 'active':
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")


# ============ AI 每日限额 ============

def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def get_ai_remaining(user: User):
    """剩余次数：admin 返回 None（不限量），否则 0~AI_DAILY_LIMIT"""
    if user.role == 'admin':
        return None
    if user.ai_usage_date != _today():
        return AI_DAILY_LIMIT
    return max(0, AI_DAILY_LIMIT - (user.ai_usage_count or 0))


def consume_ai_usage(db, user_id) -> bool:
    """
    原子预扣 1 次：检查与扣减在同一条 UPDATE 中完成，多标签并发请求不会绕过上限。
    返回 True=扣减成功；False=今日已达上限。
    admin 由调用方跳过，不进入本函数。
    """
    today = _today()
    result = db.execute(
        text(
            "UPDATE users SET "
            "  ai_usage_count = CASE WHEN ai_usage_date = :today THEN ai_usage_count + 1 ELSE 1 END, "
            "  ai_usage_date = :today "
            "WHERE id = :uid AND (ai_usage_date != :today OR ai_usage_count < :limit)"
        ),
        {"today": today, "uid": int(user_id), "limit": AI_DAILY_LIMIT},
    )
    db.commit()
    return result.rowcount > 0


def refund_ai_usage(db, user_id) -> None:
    """回退 1 次（仅当计数归属今天且 >0；服务端失败补偿，非用户主动断开）"""
    db.execute(
        text(
            "UPDATE users SET ai_usage_count = ai_usage_count - 1 "
            "WHERE id = :uid AND ai_usage_date = :today AND ai_usage_count > 0"
        ),
        {"uid": int(user_id), "today": _today()},
    )
    db.commit()


def reset_ai_usage(db, user_id) -> None:
    """管理员重置某用户今日用量"""
    user = _get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.ai_usage_date = None
    user.ai_usage_count = 0
    db.commit()
