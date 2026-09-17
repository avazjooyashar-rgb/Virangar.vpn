# ============================================================
# force_join.py
# بررسی عضویت اجباری در کانال
# ============================================================

import logging

from telebot import types

from config import bot
from db import get_setting


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


def force_join_markup():
    markup = types.InlineKeyboardMarkup()

    url = get_setting("force_join_url", "").strip()

    if url:
        markup.add(
            types.InlineKeyboardButton(
                "📢 عضویت در کانال",
                url=url
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            "✅ بررسی عضویت",
            callback_data="check_join"
        )
    )

    return markup
