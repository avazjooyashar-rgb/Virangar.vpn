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


@bot.message_handler(commands=["start"])
def start(message):
    # اگه از یه مرحله‌ی نیمه‌کاره‌ی پنل ادمین (broadcast/force-join) هندلری
    # روی این چت رجیستر مونده باشه، پاکش می‌کنیم تا جلوی /start رو نگیره.
    bot.clear_step_handler_by_chat_id(message.chat.id)

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
        message.chat.id,
        text,
        reply_markup=user_keyboard(
            is_super_admin=is_superadmin(message.from_user.id)
        )
    )


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
