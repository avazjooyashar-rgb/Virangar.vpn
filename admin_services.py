# ============================================================
# admin_services.py
# نمای کلی سرویس‌ها و نمایندگان برای ادمین
# ============================================================

from config import bot
from database import db_execute
from decorators import admin_only


@bot.message_handler(func=lambda m: m.text == "📦 سرویس‌ها")
@admin_only
def admin_services(message):
    count = db_execute("SELECT COUNT(*) c FROM services", fetchone=True)["c"]

    active = db_execute(
        "SELECT COUNT(*) c FROM services WHERE status='active'",
        fetchone=True
    )["c"]

    bot.send_message(
        message.chat.id,
        "📦 <b>مدیریت سرویس‌ها</b>\n\n"
        f"کل سرویس‌ها: {count}\n"
        f"سرویس فعال: {active}\n\n"
        "جستجوی سرویس با ID در نسخه مدیریت کامل انجام می‌شود."
    )


@bot.message_handler(func=lambda m: m.text == "🤝 نمایندگان")
@admin_only
def admin_resellers(message):
    count = db_execute(
        "SELECT COUNT(*) c FROM users WHERE is_reseller=1",
        fetchone=True
    )["c"]

    bot.send_message(
        message.chat.id,
        "🤝 <b>مدیریت نمایندگان</b>\n\n"
        f"تعداد نمایندگان: {count}"
    )
