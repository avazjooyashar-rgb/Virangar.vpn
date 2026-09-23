# ============================================================
# user_admin_menu.py
# سوییچ مستقیم سوپر ادمین از منوی کاربر به منوی ادمین
# ============================================================

from config import bot
from decorators import super_admin_only
from keyboards import admin_keyboard


@bot.message_handler(func=lambda m: m.text == "👑 پنل سوپر ادمین")
@super_admin_only
def user_switch_to_admin_menu(message):
    bot.send_message(
        message.chat.id,
        "👑 وارد پنل سوپر ادمین شدید.",
        reply_markup=admin_keyboard()
    )
