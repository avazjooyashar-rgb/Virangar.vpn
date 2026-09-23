# ============================================================
# decorators.py
# دکوریتورهای کنترل دسترسی
# ============================================================

from functools import wraps

from config import bot
from models import is_admin, is_superadmin


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


def super_admin_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if not is_superadmin(message.from_user.id):
            bot.send_message(
                message.chat.id,
                "⛔ دسترسی غیرمجاز"
            )
            return
        return func(message, *args, **kwargs)

    return wrapper
