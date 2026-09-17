# ============================================================
# admins.py
# بررسی سطح دسترسی مدیران
# ============================================================

from functools import wraps

from config import bot
from db import db_execute


def is_admin(tg_id):
    row = db_execute("""
    SELECT 1 FROM admins
    WHERE telegram_id=? AND is_active=1
    """, (tg_id,), fetchone=True)

    return bool(row)


def is_superadmin(tg_id):
    row = db_execute("""
    SELECT 1 FROM admins
    WHERE telegram_id=? AND role='superadmin' AND is_active=1
    """, (tg_id,), fetchone=True)

    return bool(row)


def admin_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if not is_admin(message.from_user.id):
            bot.send_message(
                message.chat.id,
                "⛔ دسترسی غیرمجاز"
            )
            return
        return func(message, *args, **kwargs)

    return wrapper
