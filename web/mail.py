"""
邮件验证码发送（阿里云邮件推送 DirectMail / 通用 SMTP SSL）

- 配置(.env):SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_FROM_NAME
- validate_email: 格式校验 + 临时邮箱黑名单
- send_mail_code: 发送 6 位验证码邮件
"""
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

from fastapi import HTTPException

# 临时/一次性邮箱域名黑名单(常见,可按需扩充)
DISPOSABLE_DOMAINS = {
    'mailinator.com', '10minutemail.com', 'guerrillamail.com', 'tempmail.com',
    'temp-mail.org', 'yopmail.com', 'throwaway.email', 'getnada.com',
    'dispostable.com', 'sharklasers.com', 'maildrop.cc', 'fakeinbox.com',
    'tempinbox.com', 'trbvm.com', 'emailondeck.com', 'mohmal.com',
}

_EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')


def validate_email(email: str) -> str:
    """校验邮箱格式 + 拦截临时邮箱,返回小写邮箱;非法抛 HTTPException(400)"""
    if not email:
        raise HTTPException(status_code=400, detail="邮箱不能为空")
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    domain = email.split('@')[-1]
    if domain in DISPOSABLE_DOMAINS:
        raise HTTPException(status_code=400, detail="不支持临时邮箱,请使用正规邮箱")
    return email


def send_mail(to_email: str, subject: str, body: str) -> None:
    """通用纯文本邮件发送。SMTP 配置缺失或发送失败抛 HTTPException(500)"""
    host = os.getenv('SMTP_HOST', '').strip()
    port = int(os.getenv('SMTP_PORT', '465'))
    user = os.getenv('SMTP_USER', '').strip()
    pwd = os.getenv('SMTP_PASS', '').strip()
    from_name = os.getenv('SMTP_FROM_NAME', '缠论分析').strip()
    if not (host and user and pwd):
        raise HTTPException(status_code=500, detail="邮件服务未配置(缺少 SMTP_HOST/SMTP_USER/SMTP_PASS)")

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = formataddr((from_name, user))
    msg['To'] = to_email

    try:
        with smtplib.SMTP_SSL(host, port, timeout=15) as s:
            s.login(user, pwd)
            s.send_message(msg)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"邮件发送失败:{e}")


def send_mail_code(to_email: str, code: str) -> None:
    """发送验证码邮件"""
    from_name = os.getenv('SMTP_FROM_NAME', '缠论分析').strip()
    send_mail(
        to_email,
        f"【{from_name}】您的注册验证码 {code}",
        (
            f"您好!\n\n"
            f"您的注册验证码是:{code}\n\n"
            f"验证码 5 分钟内有效,请尽快完成注册。\n"
            f"如非本人操作,请忽略此邮件,无需任何操作。\n\n"
            f"— {from_name}"
        ),
    )
