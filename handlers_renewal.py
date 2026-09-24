from datetime import datetime, timedelta

from telebot import types
from config import bot
from database import db_execute, get_setting, now
from models import internal_user_id, get_user
from pasarguard_api import pasarguard_apply_renewal, pasarguard_apply_volume_increase


def _get_owned_service(service_id, telegram_id):
    user_id = internal_user_id(telegram_id)
    return db_execute("""
    SELECT services.*, plans.name AS plan_name, plans.price AS plan_price,
           plans.duration AS plan_duration, plans.volume AS plan_volume,
           plans.panel_id AS panel_id
    FROM services
    LEFT JOIN plans ON plans.id=services.plan_id
    WHERE services.id=? AND services.user_id=?
    """, (service_id, user_id), fetchone=True)


def _get_panel(panel_id):
    if not panel_id:
        return None
    return db_execute("SELECT * FROM panels WHERE id=?", (panel_id,), fetchone=True)


def _extend_expiry(current_expiry, days):
    base = datetime.utcnow()
    if current_expiry:
        try:
            current_dt = datetime.strptime(current_expiry, "%Y-%m-%d %H:%M:%S")
            if current_dt > base:
                base = current_dt
        except Exception:
            pass
    return (base + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# RENEW — STEP 1: نمایش جزئیات (بدون تغییر)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("renew:") and call.data.count(":") == 1)
def renew_service(call):
    service_id = int(call.data.split(":")[1])
    service = _get_owned_service(service_id, call.from_user.id)

    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return
    if not service["plan_id"]:
        bot.answer_callback_query(
            call.id,
            "این یک سرویس تست است و از این طریق قابل تمدید نیست. با پشتیبانی تماس بگیرید.",
            show_alert=True
        )
        return

    new_total_volume = service["volume"] + service["plan_volume"]
    text = (
        "🔄 <b>تمدید سرویس</b>\n\n"
        f"📦 پلن: {service['plan_name']}\n"
        f"➕ حجم اضافه‌شونده: {service['plan_volume']} GB "
        f"(حجم کل بعد از تمدید: {new_total_volume} GB)\n"
        f"⏳ مدت اضافه‌شونده: {service['plan_duration']} روز\n"
        f"💰 هزینه: {service['plan_price']:,} تومان\n\n"
        "با تمدید، این مقدار حجم و زمان به سرویس فعلی اضافه می‌شود "
        "و مصرف روی پنل صفر خواهد شد.\n\n"
        "روش پرداخت را انتخاب کنید:"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💰 پرداخت از کیف پول", callback_data=f"renewwallet:{service_id}"))
    if get_setting("manual_payment_enabled", "1") == "1":
        kb.add(types.InlineKeyboardButton("💳 کارت به کارت", callback_data=f"renewcard:{service_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"service:{service_id}"))
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))

    bot.answer_callback_query(call.id)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                           reply_markup=kb, parse_mode="HTML")


# ============================================================
# RENEW — پرداخت از کیف پول (فوری) — اصلاح‌شده
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("renewwallet:"))
def renew_wallet(call):
    service_id = int(call.data.split(":")[1])
    service = _get_owned_service(service_id, call.from_user.id)

    if not service or not service["plan_id"]:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    user = get_user(call.from_user.id)
    price = service["plan_price"]

    if user["balance"] < price:
        bot.answer_callback_query(
            call.id,
            f"❌ موجودی کافی نیست.\nموجودی: {user['balance']:,} | هزینه: {price:,}",
            show_alert=True
        )
        return

    panel = _get_panel(service["panel_id"])
    if not panel or not service["username"]:
        bot.answer_callback_query(call.id, "❌ اطلاعات پنل این سرویس ناقص است. به پشتیبانی اطلاع دهید.", show_alert=True)
        return

    # اول پنل، بعد کیف پول و دیتابیس داخلی — تا هیچوقت این دو ناهماهنگ نشوند
    panel_result = pasarguard_apply_renewal(
        panel, service["username"], service["plan_volume"], service["plan_duration"]
    )
    if not panel_result.get("success"):
        bot.answer_callback_query(
            call.id,
            f"❌ تمدید روی پنل ناموفق بود: {panel_result.get('error', 'خطای نامشخص')}",
            show_alert=True
        )
        return

    new_total_volume = round(panel_result["data_limit_gb"], 2)
    new_expiry = datetime.utcfromtimestamp(panel_result["expire"]).strftime("%Y-%m-%d %H:%M:%S")

    db_execute("UPDATE users SET balance=balance-? WHERE id=?", (price, user["id"]))
    db_execute("""
    UPDATE services
    SET volume=?, used_volume=0, expires_at=?, status='active', updated_at=?
    WHERE id=?
    """, (new_total_volume, new_expiry, now(), service_id))
    db_execute("""
    INSERT INTO transactions (user_id, amount, type, description, reference, created_at)
    VALUES (?, ?, 'debit', ?, ?, ?)
    """, (user["id"], -price, f"تمدید سرویس {service['plan_name']}", f"renew:{service_id}", now()))
    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method, type, target_service_id,
     extra_days, extra_volume, status, created_at, updated_at)
    VALUES (?, ?, ?, 'wallet_renew', 'renew', ?, ?, ?, 'approved', ?, ?)
    """, (
        user["id"], service["plan_id"], price, service_id,
        service["plan_duration"], service["plan_volume"], now(), now()
    ))

    bot.answer_callback_query(call.id, "✅ سرویس با موفقیت تمدید شد.")
    bot.send_message(
        call.message.chat.id,
        f"🎉 <b>تمدید موفق</b>\n\n"
        f"📦 پلن: {service['plan_name']}\n"
        f"📊 حجم کل جدید: <code>{new_total_volume} GB</code>\n"
        f"📅 تاریخ انقضای جدید: <code>{new_expiry}</code>\n\n"
        f"✅ این مقادیر مستقیماً از پنل خوانده شده و تضمینی است.",
        parse_mode="HTML"
    )


# renewcard و receive_renew_receipt بدون تغییر می‌مانند (فقط رسید ثبت می‌کنند)
# ... (همان کدهای قبلی خودتان را نگه دارید)
