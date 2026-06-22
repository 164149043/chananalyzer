"""
积分消费/退还工具（预留接口，当前不接入业务端点）

本次管理员后台只做"管理员手动调整积分"，不做功能扣费闭环。
将来要在 analyze / scan / kline 等端点入口扣费时，调用本模块的
consume_credits / refund_credits 即可，签名稳定。

设计要点：
- db 由调用方传入：保证扣费与业务动作（如扫描）在同一事务，要么一起成功要么一起回滚
- actor：触发者标识，'system'（系统自动扣费）或 admin_id（管理员手动）
- 预留 HTTPException(402)：业务端点将来调 consume_credits 失败时返回 402，
  前端可据此弹"积分不足"提示
"""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ChanAnalyzer.database import User, CreditTransaction
from datetime import datetime


def check_credits(db: Session, user_id: int, required: int) -> bool:
    """检查用户积分是否 >= required，不修改数据。"""
    user = db.query(User).filter(User.id == user_id).first()
    return bool(user and user.credits >= required)


def consume_credits(
    db: Session,
    user_id: int,
    amount: int,
    reason: str,
    actor: str = "system",
) -> int:
    """
    扣减积分（预留，当前未启用）。

    Args:
        amount: 扣减量（正整数）
        reason: 扣费原因（写入流水）
        actor: 触发者，'system' 或管理员 user_id
    Returns:
        扣减后余额
    Raises:
        HTTPException(402): 余额不足
        HTTPException(400): 参数非法
    """
    raise NotImplementedError("积分扣费闭环暂未启用")


def refund_credits(
    db: Session,
    user_id: int,
    amount: int,
    reason: str,
    actor: str = "system",
) -> int:
    """退还积分（预留，当前未启用）。amount 为正整数，返回退还后余额。"""
    raise NotImplementedError("积分退还暂未启用")


def _record_transaction(
    db: Session,
    admin_id: int,
    target_user_id: int,
    delta: int,
    balance_after: int,
    reason: str,
) -> CreditTransaction:
    """
    写一条积分流水（内部工具，供管理员调整 / 将来扣费 / 退款复用）。

    注意：不负责 commit，由调用方在事务内统一提交。
    """
    tx = CreditTransaction(
        admin_id=admin_id,
        target_user_id=target_user_id,
        delta=delta,
        balance_after=balance_after,
        reason=reason,
        created_at=datetime.now(),
    )
    db.add(tx)
    return tx
