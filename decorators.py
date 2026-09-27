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


def admin_only_call(func):
    """
    نسخه‌ی مخصوص callback_query هندلرها (دکمه‌های inline).
    به جای send_message از answer_callback_query با alert استفاده می‌کند.
    """
    @wraps(func)
    def wrapper(call, *args, **kwargs):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(
                call.id,
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return
        return func(call, *args, **kwargs)

    return wrapper


def super_admin_only_call(func):
    @wraps(func)
    def wrapper(call, *args, **kwargs):
        if not is_superadmin(call.from_user.id):
            bot.answer_callback_query(
                call.id,
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return
        return func(call, *args, **kwargs)

    return wrapper
