# ============================================================
# force_join.py
# منطق عضویت اجباری در کانال + دستور /start
# ============================================================

import logging

from config import bot, BOT_NAME
from database import get_setting
from models import ensure_user
from keyboards import user_keyboard, force_join_markup


def force_join_ok(user_id):
    enabled = get_setting("force_join_enabled", "0") == "1"

    if not enabled:
        return True

    channel = get_setting("force_join_channel", "").strip()

    if not channel:
        return True

    try:
        member = bot.get_chat_member(channel, user_id)

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except Exception as e:
        logging.warning("Force join check: %s", e)
        return False


@bot.message_handler(commands=["start"])
def start(message):
    user = ensure_user(message.from_user)

    if user["is_blocked"]:
        bot.send_message(
            message.chat.id,
            "⛔ حساب شما مسدود شده است."
        )
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

    bot.send_message(
        message.chat.id,
        text,
        reply_markup=user_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join(call):
    if force_join_ok(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            "عضویت تأیید شد ✅"
        )

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
