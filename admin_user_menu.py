# ============================================================
# admin_user_menu.py
# سوییچ مستقیم ادمین به منوی کاربر (بدون اجرای دوباره‌ی /start)
# ============================================================

from config import bot
from decorators import admin_only
from keyboards import user_keyboard


@bot.message_handler(func=lambda m: m.text == "🏠 منوی کاربر")
@admin_only
def admin_switch_to_user_menu(message):
    bot.send_message(
        message.chat.id,
        "🏠 وارد منوی کاربر شدید.",
        reply_markup=user_keyboard()
    )
