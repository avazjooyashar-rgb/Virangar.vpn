# ============================================================
# admin_payment_settings.py
# نمای کلی پرداخت‌ها و تنظیم شماره کارت
# ============================================================

from config import bot
from database import db_execute, get_setting, set_setting
from decorators import admin_only


@bot.message_handler(func=lambda m: m.text == "💰 پرداخت‌ها")
@admin_only
def admin_payments(message):
    pending = db_execute(
        "SELECT COUNT(*) c FROM payments WHERE status='pending'",
        fetchone=True
    )["c"]

    approved = db_execute("""
    SELECT COALESCE(SUM(amount),0) total
    FROM payments
    WHERE status='approved'
    """, fetchone=True)["total"]

    bot.send_message(
        message.chat.id,
        "💰 <b>مدیریت پرداخت‌ها</b>\n\n"
        f"⏳ در انتظار بررسی: {pending}\n"
        f"✅ مجموع پرداخت تأییدشده: {approved:,} تومان"
    )


@bot.message_handler(func=lambda m: m.text == "💳 تنظیمات پرداخت")
@admin_only
def payment_settings(message):
    mode = get_setting("payment_mode", "manual")
    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")
    manual = get_setting("manual_payment_enabled", "1")
    online = get_setting("online_payment_enabled", "0")

    bot.send_message(
        message.chat.id,
        "💳 <b>تنظیمات پرداخت</b>\n\n"
        f"⚙️ حالت: {mode}\n"
        f"💳 کارت به کارت: {'فعال' if manual == '1' else 'غیرفعال'}\n"
        f"🌐 آنلاین: {'فعال' if online == '1' else 'غیرفعال'}\n"
        f"💳 کارت: {card or 'تنظیم نشده'}\n"
        f"👤 صاحب کارت: {holder or 'تنظیم نشده'}\n\n"
        "برای تغییر شماره کارت از دستور /setcard استفاده کنید."
    )


@bot.message_handler(commands=["setcard"])
@admin_only
def setcard(message):
    bot.send_message(message.chat.id, "💳 شماره کارت را ارسال کنید:")
    bot.register_next_step_handler(message, setcard_number)


def setcard_number(message):
    set_setting("card_number", message.text.strip())
    bot.send_message(message.chat.id, "👤 نام صاحب کارت را ارسال کنید:")
    bot.register_next_step_handler(message, setcard_holder)


def setcard_holder(message):
    set_setting("card_holder", message.text.strip())
    bot.send_message(message.chat.id, "✅ اطلاعات کارت ذخیره شد.")
