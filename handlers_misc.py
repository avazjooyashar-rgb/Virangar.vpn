# ============================================================
# handlers_misc.py
# راهنما و حساب کاربری
# ============================================================

from telebot import types

from config import bot
from models import get_user
import chat_clean as cc


def _home_markup():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))
    return kb


@bot.message_handler(func=lambda m: m.text == "📚 راهنما")
def guide(message):
    cc.drop(message)  # پیام دکمه‌ی منو پاک بشه
    cc.show(
        message.chat.id,
        "📚 <b>راهنمای VirangarVPN</b>\n\n"
        "🛒 خرید VPN\n"
        "از بخش خرید، پلن موردنظر را انتخاب کنید.\n\n"
        "🛡 سرویس‌های من\n"
        "مشاهده و مدیریت سرویس‌های فعال.\n\n"
        "💰 کیف پول\n"
        "شارژ حساب و مشاهده تراکنش‌ها.\n\n"
        "🤝 نمایندگی\n"
        "مدیریت پنل و کاربران نمایندگی.\n\n"
        "🆘 پشتیبانی\n"
        "ایجاد و پیگیری تیکت.",
        reply_markup=_home_markup()
    )


@bot.message_handler(func=lambda m: m.text == "⚙️ حساب کاربری")
def account(message):
    cc.drop(message)  # پیام دکمه‌ی منو پاک بشه
    user = get_user(message.from_user.id)

    username = f"@{user['username']}" if user and user["username"] else "بدون یوزرنیم"

    cc.show(
        message.chat.id,
        "🪪 <b>حساب کاربری شما</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"🆔 آیدی عددی: <code>{message.from_user.id}</code>\n"
        f"👤 نام کاربری: {username}\n"
        f"💰 موجودی کیف پول: <b>{user['balance']:,}</b> تومان\n"
        f"📅 تاریخ عضویت: {user['created_at']}\n\n"
        "✨ برای شارژ کیف پول از منوی اصلی وارد بخش «💰 کیف پول» شو.",
        reply_markup=_home_markup()
    )
