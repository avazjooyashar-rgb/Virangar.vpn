# ============================================================
# handlers_trial.py
# تست رایگان برای کاربران عادی
# ============================================================

from config import bot
from database import db_execute, get_setting
from models import get_user, is_admin
from pasarguard import pasarguard_create_service
from services import create_local_service


@bot.message_handler(func=lambda m: m.text == "🎁 تست رایگان" and not is_admin(m.from_user.id))
def free_trial(message):
    user = get_user(message.from_user.id)

    if get_setting("trial_enabled", "1") != "1":
        bot.send_message(message.chat.id, "❌ تست رایگان غیرفعال است.")
        return

    existing = db_execute("""
    SELECT id FROM services
    WHERE user_id=? AND plan_id IS NULL
    LIMIT 1
    """, (user["id"],), fetchone=True)

    if existing:
        bot.send_message(message.chat.id, "❌ شما قبلاً از تست رایگان استفاده کرده‌اید.")
        return

    volume = int(get_setting("trial_volume", "5"))
    duration = int(get_setting("trial_duration", "1"))
    devices = int(get_setting("trial_devices", "1"))

    panel = db_execute("""
    SELECT * FROM panels
    WHERE active=1
    ORDER BY assigned_sales ASC, id ASC
    LIMIT 1
    """, fetchone=True)

    if not panel:
        bot.send_message(message.chat.id, "❌ در حال حاضر پنل فعالی برای تست وجود ندارد.")
        return

    fake_plan = {
        "id": None,
        "name": "Free Trial",
        "price": 0,
        "volume": volume,
        "duration": duration,
        "devices": devices
    }

    result = pasarguard_create_service(panel=panel, telegram_user=user, plan=fake_plan)

    if not result["success"]:
        bot.send_message(message.chat.id, "❌ ساخت تست رایگان انجام نشد.")
        return

    service = create_local_service(user=user, plan=fake_plan, panel=panel, result=result)

    bot.send_message(
        message.chat.id,
        "🎁 <b>تست رایگان فعال شد!</b>\n\n"
        f"📊 حجم: {volume} GB\n"
        f"⏳ مدت: {duration} روز\n"
        f"📱 دستگاه: {devices}\n\n"
        f"🔗 لینک اشتراک:\n"
        f"<code>{service['config']}</code>"
    )


# ============================================================
# ADMIN VIEW OF TRIAL SETTINGS (same button text, admin only)
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🎁 تست رایگان" and is_admin(m.from_user.id))
def admin_trial_settings(message):
    bot.send_message(
        message.chat.id,
        "🎁 <b>تنظیمات تست رایگان</b>\n\n"
        f"وضعیت: {get_setting('trial_enabled')}\n"
        f"حجم: {get_setting('trial_volume')} GB\n"
        f"مدت: {get_setting('trial_duration')} روز\n"
        f"دستگاه: {get_setting('trial_devices')}\n"
        f"محدودیت: {get_setting('trial_limit')}"
    )
