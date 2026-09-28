# ============================================================
# force_join.py
# منطق عضویت اجباری در کانال + دستور /start
# ============================================================

import logging

from config import bot, BOT_NAME
from database import get_setting
from models import ensure_user, is_superadmin
from keyboards import user_keyboard, force_join_markup


DEFAULT_FORCE_JOIN_MESSAGE = (
    "🚀 <b>فقط یه قدم تا شروع فاصله داری!</b>\n\n"
    "برای استفاده از امکانات ربات، اول عضو کانال ما شو؛ "
    "اونجا خبرای داغ، تخفیف‌های ویژه و آپدیت‌های جدید منتظرتن 🎁\n\n"
    "بعد از عضویت، دکمه‌ی «بررسی عضویت» رو بزن 👇"
)


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


def _force_join_message_text():
    text = get_setting("force_join_message_text", "").strip()
    return text or DEFAULT_FORCE_JOIN_MESSAGE


def _send_start(chat_id, from_user):
    user = ensure_user(from_user)

    if user["is_blocked"]:
        bot.send_message(
            chat_id,
            "⛔ حساب شما مسدود شده است."
        )
        return

    if not force_join_ok(from_user.id):
        bot.send_message(
            chat_id,
            _force_join_message_text(),
            reply_markup=force_join_markup(),
            parse_mode="HTML"
        )
        return

    text = (
        f"🔥 <b>{BOT_NAME}</b>\n\n"
        "به ربات خوش آمدید ❤️\n\n"
        "از منوی زیر سرویس موردنظر خود را انتخاب کنید."
    )

    bot.send_message(
        chat_id,
        text,
        reply_markup=user_keyboard(
            is_super_admin=is_superadmin(from_user.id)
        )
    )


@bot.message_handler(commands=["start"])
def start(message):
    # اگه از یه مرحله‌ی نیمه‌کاره‌ی پنل ادمین (broadcast/force-join) هندلری
    # روی این چت رجیستر مونده باشه، پاکش می‌کنیم تا جلوی /start رو نگیره.
    bot.clear_step_handler_by_chat_id(message.chat.id)
    _send_start(message.chat.id, message.from_user)


# دکمه‌ی «استارت» داخل پیام‌های همگانی: همون کار /start رو مستقیم تو همون چت انجام میده
@bot.callback_query_handler(func=lambda call: call.data == "go_start")
def go_start(call):
    bot.answer_callback_query(call.id)
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _send_start(call.message.chat.id, call.from_user)


@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join(call):
    if force_join_ok(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            "🎉 عضویت تأیید شد!"
        )

        bot.send_message(
            call.message.chat.id,
            "✅ خوش اومدی! حالا می‌تونی از همه‌ی امکانات ربات استفاده کنی 🚀",
            reply_markup=user_keyboard(
                is_super_admin=is_superadmin(call.from_user.id)
            )
        )
    else:
        bot.answer_callback_query(
            call.id,
            "❌ هنوز عضو کانال نشدی. اول عضو شو، بعد دوباره بزن.",
            show_alert=True
        )
