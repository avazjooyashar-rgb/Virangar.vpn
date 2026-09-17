# ============================================================
# admin_broadcast.py
# ارسال پیام همگانی و تنظیمات عضویت اجباری
# ============================================================

import time

from config import bot
from database import db_execute, get_setting, set_setting
from decorators import admin_only


# ============================================================
# BROADCAST
# ============================================================

@bot.message_handler(func=lambda m: m.text == "📢 ارسال همگانی")
@admin_only
def broadcast(message):
    bot.send_message(message.chat.id, "📢 متن پیام همگانی را ارسال کنید:")
    bot.register_next_step_handler(message, broadcast_send)


def broadcast_send(message):
    users = db_execute("SELECT telegram_id FROM users WHERE is_blocked=0", fetchall=True)

    sent = 0

    for user in users:
        try:
            bot.send_message(user["telegram_id"], message.text)
            sent += 1
            time.sleep(0.04)
        except Exception:
            pass

    bot.send_message(
        message.chat.id,
        f"✅ ارسال انجام شد.\n"
        f"تعداد موفق: {sent}"
    )


# ============================================================
# FORCE JOIN SETTINGS
# ============================================================

@bot.message_handler(func=lambda m: m.text == "📢 عضویت اجباری")
@admin_only
def admin_force_join(message):
    enabled = get_setting("force_join_enabled", "0")
    channel = get_setting("force_join_channel", "")
    url = get_setting("force_join_url", "")

    bot.send_message(
        message.chat.id,
        "📢 <b>عضویت اجباری</b>\n\n"
        f"وضعیت: {'فعال' if enabled == '1' else 'غیرفعال'}\n"
        f"کانال: {channel or '---'}\n"
        f"لینک: {url or '---'}\n\n"
        "برای تغییر از /setforcejoin استفاده کنید."
    )


@bot.message_handler(commands=["setforcejoin"])
@admin_only
def setforcejoin(message):
    bot.send_message(message.chat.id, "📢 آیدی کانال را ارسال کنید:")
    bot.register_next_step_handler(message, setforce_channel)


def setforce_channel(message):
    set_setting("force_join_channel", message.text.strip())
    bot.send_message(message.chat.id, "🔗 لینک کانال را ارسال کنید:")
    bot.register_next_step_handler(message, setforce_url)


def setforce_url(message):
    set_setting("force_join_url", message.text.strip())
    set_setting("force_join_enabled", "1")
    bot.send_message(message.chat.id, "✅ عضویت اجباری فعال شد.")
