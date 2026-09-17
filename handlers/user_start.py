# ============================================================
# handlers/user_start.py
# /start، بررسی عضویت، راهنما، حساب کاربری، fallback
# ============================================================

from config import bot, BOT_NAME
from users import ensure_user, get_user
from admins import is_admin
from force_join import force_join_ok, force_join_markup
from keyboards import user_keyboard, admin_keyboard


@bot.message_handler(commands=["start"])
def start(message):
    user = ensure_user(message.from_user)

    if user["is_blocked"]:
        bot.send_message(message.chat.id, "⛔ حساب شما مسدود شده است.")
        return

    if not force_join_ok(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "🔒 برای استفاده از ربات ابتدا عضو کانال شوید.",
            reply_markup=force_join_markup()
        )
        return

    text = (
        f"🔥 <b>{BOT_NAME}</b>\n\n"
        "به ربات خوش آمدید ❤️\n\n"
        "از منوی زیر سرویس موردنظر خود را انتخاب کنید."
    )

    bot.send_message(message.chat.id, text, reply_markup=user_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join(call):
    if force_join_ok(call.from_user.id):
        bot.answer_callback_query(call.id, "عضویت تأیید شد ✅")

        bot.send_message(
            call.message.chat.id,
            "🔥 حالا می‌تونی از ربات استفاده کنی.",
            reply_markup=user_keyboard()
        )
    else:
        bot.answer_callback_query(
            call.id,
            "هنوز عضو کانال نیستی ❌",
            show_alert=True
        )


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

    username = (
        f"@{user['username']}"
        if user and user["username"]
        else "بدون یوزرنیم"
    )

    bot.send_message(
        message.chat.id,
        "⚙️ <b>حساب کاربری</b>\n\n"
        f"🆔 Telegram ID: <code>{message.from_user.id}</code>\n"
        f"👤 Username: {username}\n"
        f"💰 موجودی: {user['balance']:,} تومان\n"
        f"📅 عضویت: {user['created_at']}"
    )


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
