# ============================================================
# fallback.py
# هندلر پیش‌فرض برای پیام‌های نامشخص
# ============================================================
# نکته: این فایل باید همیشه آخرین ماژول import شده باشد
# چون هندلر آن با func=lambda message: True هر پیامی را می‌گیرد.
# ============================================================

from config import bot
from models import get_user, is_admin
from keyboards import user_keyboard, admin_keyboard


@bot.message_handler(func=lambda message: True)
def fallback(message):
    if not message.text:
        return

    if message.text.startswith("/"):
        return

    user = get_user(message.from_user.id)

    if user and user["is_blocked"]:
        bot.send_message(message.chat.id, "⛔ حساب شما مسدود است.")
        return

    bot.send_message(
        message.chat.id,
        "از منوی زیر استفاده کنید.",
        reply_markup=(
            admin_keyboard()
            if is_admin(message.from_user.id)
            else user_keyboard()
        )
    )
