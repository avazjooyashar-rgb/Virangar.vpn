# ============================================================
# handlers_misc.py
# راهنما و حساب کاربری
# ============================================================

from config import bot
from models import get_user


@bot.message_handler(func=lambda m: m.text == "📚 راهنما")
def guide(message):
    bot.send_message(
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
        "ایجاد و پیگیری تیکت."
    )


@bot.message_handler(func=lambda m: m.text == "⚙️ حساب کاربری")
def account(message):
    user = get_user(message.from_user.id)

    username = f"@{user['username']}" if user and user["username"] else "بدون یوزرنیم"

    bot.send_message(
        message.chat.id,
        "⚙️ <b>حساب کاربری</b>\n\n"
        f"🆔 Telegram ID: <code>{message.from_user.id}</code>\n"
        f"👤 Username: {username}\n"
        f"💰 موجودی: {user['balance']:,} تومان\n"
        f"📅 عضویت: {user['created_at']}"
    )
