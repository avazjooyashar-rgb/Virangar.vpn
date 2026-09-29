# ============================================================
# handlers_license.py
# فعلاً غیرفعال — بعداً کامل پیاده‌سازی میشه.
# فقط یه پیام «در دسترس نیست» با دکمه‌ی بازگشت به منوی اصلی.
# ============================================================

from telebot import types

from config import bot
import chat_clean as cc


@bot.message_handler(func=lambda m: m.text == "🎫 خرید لایسنس ربات")
def license_not_available(message):
    cc.drop(message)  # پیام دکمه‌ی منو پاک بشه

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))

    cc.show(
        message.chat.id,
        "🚧 <b>این قسمت فعلاً در دسترس نیست.</b>\n\n"
        "به‌زودی فعال می‌شود.",
        reply_markup=kb
    )
