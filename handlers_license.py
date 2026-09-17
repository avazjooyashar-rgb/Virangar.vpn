# ============================================================
# handlers_license.py
# خرید و مشاهده لایسنس ربات
# ============================================================

from telebot import types

from config import bot
from database import db_execute
from models import internal_user_id


@bot.message_handler(func=lambda m: m.text == "🎫 خرید لایسنس ربات")
def license_menu(message):
    kb = types.InlineKeyboardMarkup()

    kb.add(types.InlineKeyboardButton("🎫 خرید لایسنس", callback_data="license_buy"))
    kb.add(types.InlineKeyboardButton("📜 لایسنس‌های من", callback_data="license_my"))

    bot.send_message(message.chat.id, "🎫 <b>لایسنس ربات</b>", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data == "license_buy")
def license_buy(call):
    bot.send_message(call.message.chat.id, "🎫 پلن‌های لایسنس در حال تنظیم هستند.")


@bot.callback_query_handler(func=lambda call: call.data == "license_my")
def license_my(call):
    user_id = internal_user_id(call.from_user.id)

    rows = db_execute("""
    SELECT * FROM licenses
    WHERE user_id=?
    ORDER BY id DESC
    """, (user_id,), fetchall=True)

    if not rows:
        bot.send_message(call.message.chat.id, "📭 لایسنسی ندارید.")
        return

    text = ["🎫 <b>لایسنس‌های من</b>\n"]

    for row in rows:
        text.append(
            f"🔑 <code>{row['license_key']}</code>\n"
            f"📅 {row['expires_at']}\n"
            f"📌 {row['status']}\n"
        )

    bot.send_message(call.message.chat.id, "\n".join(text))
