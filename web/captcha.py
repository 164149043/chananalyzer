"""
图形验证码（开放注册防机器人）

- Pillow 绘制算术题验证码（朱砂红字符 + 墨黑背景 + 干扰线/噪点，匹配禅意主题）
- 进程内字典存储答案，TTL 10 分钟，一次性（校验后即删）
- 适合单进程部署；多实例需换 Redis 等共享存储
"""
import io
import random
import secrets
import threading
import time
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

# 禅意主题配色（与前端一致）
_BG = (10, 10, 10)        # 墨黑背景
_FG = (200, 55, 46)       # 朱砂红字符
_NOISE = (150, 150, 150)  # 噪点/干扰线灰

# 进程内验证码存储：{captcha_id: (answer_str, expire_ts)}
_store = {}
_lock = threading.Lock()
_TTL_SECONDS = 600          # 10 分钟有效
_CLEANUP_INTERVAL = 20      # 每生成 N 次惰性清理一次过期项
_generation_count = 0


def _cleanup_expired() -> None:
    """删除过期验证码"""
    now = time.time()
    expired = [k for k, (_, exp) in _store.items() if exp < now]
    for k in expired:
        del _store[k]


def _get_font(size: int):
    """获取字体，优先系统字体，回退默认位图字体"""
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def generate_captcha() -> Tuple[str, bytes]:
    """
    生成一个算术验证码

    Returns:
        (captcha_id, png_bytes)
    """
    global _generation_count

    a = random.randint(1, 9)
    b = random.randint(1, 9)
    op = random.choice(['+', '-', '×'])
    if op == '+':
        answer = a + b
        text = f"{a} + {b} = ?"
    elif op == '-':
        if a < b:
            a, b = b, a
        answer = a - b
        text = f"{a} - {b} = ?"
    else:
        answer = a * b
        text = f"{a} × {b} = ?"

    # 绘制图片
    width, height = 160, 50
    img = Image.new('RGB', (width, height), _BG)
    draw = ImageDraw.Draw(img)
    font = _get_font(24)

    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            ((width - tw) / 2 - bbox[0], (height - th) / 2 - bbox[1]),
            text, fill=_FG, font=font,
        )
    except Exception:
        draw.text((20, 12), text, fill=_FG, font=font)

    # 干扰线
    for _ in range(3):
        draw.line(
            [(random.randint(0, width), random.randint(0, height)),
             (random.randint(0, width), random.randint(0, height))],
            fill=_NOISE, width=1,
        )

    # 噪点
    for _ in range(60):
        draw.point((random.randint(0, width - 1), random.randint(0, height - 1)), fill=_NOISE)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    png_bytes = buf.getvalue()

    captcha_id = secrets.token_urlsafe(16)
    with _lock:
        _generation_count += 1
        if _generation_count % _CLEANUP_INTERVAL == 0:
            _cleanup_expired()
        _store[captcha_id] = (str(answer), time.time() + _TTL_SECONDS)

    return captcha_id, png_bytes


def verify_captcha(captcha_id: str, answer: str) -> bool:
    """
    校验验证码（一次性：校验后无论对错都删除该 id）

    Returns:
        True 校验通过
    """
    if not captcha_id or answer is None:
        return False
    with _lock:
        entry = _store.pop(captcha_id, None)
    if entry is None:
        return False
    stored_answer, expire_ts = entry
    if time.time() > expire_ts:
        return False
    return stored_answer == str(answer).strip()
