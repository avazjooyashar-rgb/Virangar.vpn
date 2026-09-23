# ============================================================
# handlers_renewal.py
# تمدید سرویس و افزایش حجم — با پرداخت از کیف پول یا کارت به کارت
# ============================================================
from datetime import datetime, timedelta

from telebot import types
from config import bot
from database import db_execute, get_setting, set_setting, now
from models import internal_user_id, get_user
from decorators import admin_only

QUICK_VOLUME_OPTIONS = [10, 20, 50]  # گزینه‌های سریع افزایش حجم (GB)


# ============================================================
# HELPERS
# ============================================================

def _get_owned_service(service_id, telegram_id):
    user_id = internal_user_id(telegram_id)
    return db_execute("""
    SELECT services.*, plans.name AS plan_name, plans.price AS plan_price,
           plans.duration AS plan_duration, plans.volume AS plan_volume
    FROM services
    LEFT JOIN plans ON plans.id=services.plan_id
    WHERE services.id=? AND services.user_id=?
    """, (service_id, user_id), fetchone=True)


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
# RENEW — STEP 1: نمایش جزئیات و انتخاب روش پرداخت
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

    text = (
        "🔄 <b>تمدید سرویس</b>\n\n"
        f"📦 پلن: {service['plan_name']}\n"
        f"⏳ مدت تمدید: {service['plan_duration']} روز\n"
        f"💰 هزینه: {service['plan_price']:,} تومان\n\n"
        "با تمدید، حجم مصرفی صفر شده و اعتبار زمانی افزوده می‌شود.\n\n"
        "روش پرداخت را انتخاب کنید:"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💰 پرداخت از کیف پول", callback_data=f"renewwallet:{service_id}"))
    if get_setting("manual_payment_enabled", "1") == "1":
        kb.add(types.InlineKeyboardButton("💳 کارت به کارت", callback_data=f"renewcard:{service_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"service:{service_id}"))

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# RENEW — پرداخت از کیف پول (فوری)
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

    new_expiry = _extend_expiry(service["expires_at"], service["plan_duration"])

    db_execute("UPDATE users SET balance=balance-? WHERE id=?", (price, user["id"]))
    db_execute("""
    UPDATE services
    SET expires_at=?, used_volume=0, status='active', updated_at=?
    WHERE id=?
    """, (new_expiry, now(), service_id))
    db_execute("""
    INSERT INTO transactions
    (user_id, amount, type, description, reference, created_at)
    VALUES (?, ?, 'debit', ?, ?, ?)
    """, (user["id"], -price, f"تمدید سرویس {service['plan_name']}", f"renew:{service_id}", now()))
    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method, type, target_service_id,
     extra_days, status, created_at, updated_at)
    VALUES (?, ?, ?, 'wallet_renew', 'renew', ?, ?, 'approved', ?, ?)
    """, (
        user["id"], service["plan_id"], price, service_id,
        service["plan_duration"], now(), now()
    ))

    bot.answer_callback_query(call.id, "✅ سرویس با موفقیت تمدید شد.")
    bot.send_message(
        call.message.chat.id,
        f"🎉 <b>تمدید موفق</b>\n\n"
        f"📦 پلن: {service['plan_name']}\n"
        f"📅 تاریخ انقضای جدید: <code>{new_expiry}</code>",
        parse_mode="HTML"
    )


# ============================================================
# RENEW — کارت به کارت (نیاز به تأیید ادمین)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("renewcard:"))
def renew_card(call):
    service_id = int(call.data.split(":")[1])
    service = _get_owned_service(service_id, call.from_user.id)

    if not service or not service["plan_id"]:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")
    if not card:
        bot.answer_callback_query(call.id, "پرداخت کارت به کارت فعلاً تنظیم نشده.", show_alert=True)
        return

    text = (
        "💳 <b>پرداخت کارت به کارت — تمدید سرویس</b>\n\n"
        f"💰 مبلغ: <b>{service['plan_price']:,} تومان</b>\n\n"
        f"💳 شماره کارت:\n<code>{card}</code>\n\n"
        f"👤 به نام: <b>{holder or '---'}</b>\n\n"
        "بعد از انتقال وجه، تصویر رسید را همینجا ارسال کنید."
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML")
    bot.register_next_step_handler(call.message, receive_renew_receipt, service_id)


def receive_renew_receipt(message, service_id):
    if not message.photo:
        sent = bot.send_message(message.chat.id, "❌ لطفاً تصویر رسید را ارسال کن.")
        bot.register_next_step_handler(sent, receive_renew_receipt, service_id)
        return

    service = _get_owned_service(service_id, message.from_user.id)
    if not service or not service["plan_id"]:
        bot.send_message(message.chat.id, "❌ سرویس پیدا نشد.")
        return

    file_id = message.photo[-1].file_id
    user_id = internal_user_id(message.from_user.id)

    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method, receipt_file_id, receipt_type,
     type, target_service_id, extra_days, status, created_at, updated_at)
    VALUES (?, ?, ?, 'manual', ?, 'photo', 'renew', ?, ?, 'pending', ?, ?)
    """, (
        user_id, service["plan_id"], service["plan_price"], file_id,
        service_id, service["plan_duration"], now(), now()
    ))

    bot.send_message(
        message.chat.id,
        "✅ رسید شما ثبت شد.\n\n"
        "⏳ درخواست تمدید در انتظار بررسی مدیریت است."
    )


# ============================================================
# INCREASE VOLUME — STEP 1: انتخاب مقدار
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("increase:") and call.data.count(":") == 1)
def increase_service(call):
    service_id = int(call.data.split(":")[1])
    service = _get_owned_service(service_id, call.from_user.id)

    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    price_per_gb = int(get_setting("extra_gb_price", "0") or 0)
    if price_per_gb <= 0:
        bot.answer_callback_query(
            call.id,
            "قیمت افزایش حجم هنوز توسط مدیریت تنظیم نشده. با پشتیبانی تماس بگیرید.",
            show_alert=True
        )
        return

    kb = types.InlineKeyboardMarkup()
    for gb in QUICK_VOLUME_OPTIONS:
        price = gb * price_per_gb
        kb.add(
            types.InlineKeyboardButton(
                f"📈 {gb} GB — {price:,} تومان",
                callback_data=f"incamt:{service_id}:{gb}"
            )
        )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"service:{service_id}"))

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "📈 <b>افزایش حجم سرویس</b>\n\n"
        f"هر گیگابایت: {price_per_gb:,} تومان\n\n"
        "مقدار موردنظر را انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# INCREASE VOLUME — STEP 2: انتخاب روش پرداخت
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("incamt:"))
def increase_amount_selected(call):
    _, service_id, gb = call.data.split(":")
    service_id = int(service_id)
    gb = int(gb)

    service = _get_owned_service(service_id, call.from_user.id)
    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    price_per_gb = int(get_setting("extra_gb_price", "0") or 0)
    price = gb * price_per_gb

    text = (
        "📈 <b>تأیید افزایش حجم</b>\n\n"
        f"➕ مقدار: {gb} GB\n"
        f"💰 قیمت: {price:,} تومان\n\n"
        "روش پرداخت را انتخاب کنید:"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💰 پرداخت از کیف پول", callback_data=f"incwallet:{service_id}:{gb}"))
    if get_setting("manual_payment_enabled", "1") == "1":
        kb.add(types.InlineKeyboardButton("💳 کارت به کارت", callback_data=f"inccard:{service_id}:{gb}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"increase:{service_id}"))

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# INCREASE VOLUME — پرداخت از کیف پول (فوری)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("incwallet:"))
def increase_wallet(call):
    _, service_id, gb = call.data.split(":")
    service_id = int(service_id)
    gb = int(gb)

    service = _get_owned_service(service_id, call.from_user.id)
    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    price_per_gb = int(get_setting("extra_gb_price", "0") or 0)
    price = gb * price_per_gb

    user = get_user(call.from_user.id)
    if user["balance"] < price:
        bot.answer_callback_query(
            call.id,
            f"❌ موجودی کافی نیست.\nموجودی: {user['balance']:,} | هزینه: {price:,}",
            show_alert=True
        )
        return

    db_execute("UPDATE users SET balance=balance-? WHERE id=?", (price, user["id"]))
    db_execute("""
    UPDATE services
    SET volume=volume+?, updated_at=?
    WHERE id=?
    """, (gb, now(), service_id))
    db_execute("""
    INSERT INTO transactions
    (user_id, amount, type, description, reference, created_at)
    VALUES (?, ?, 'debit', ?, ?, ?)
    """, (user["id"], -price, f"افزایش {gb}GB حجم سرویس", f"increase:{service_id}", now()))
    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method, type, target_service_id,
     extra_volume, status, created_at, updated_at)
    VALUES (?, ?, ?, 'wallet_increase', 'increase', ?, ?, 'approved', ?, ?)
    """, (
        user["id"], service["plan_id"], price, service_id, gb, now(), now()
    ))

    bot.answer_callback_query(call.id, "✅ حجم با موفقیت اضافه شد.")
    bot.send_message(
        call.message.chat.id,
        f"🎉 <b>افزایش حجم موفق</b>\n\n"
        f"➕ {gb} GB به حجم سرویس شما اضافه شد."
    )


# ============================================================
# INCREASE VOLUME — کارت به کارت (نیاز به تأیید ادمین)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("inccard:"))
def increase_card(call):
    _, service_id, gb = call.data.split(":")
    service_id = int(service_id)
    gb = int(gb)

    service = _get_owned_service(service_id, call.from_user.id)
    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    price_per_gb = int(get_setting("extra_gb_price", "0") or 0)
    price = gb * price_per_gb

    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")
    if not card:
        bot.answer_callback_query(call.id, "پرداخت کارت به کارت فعلاً تنظیم نشده.", show_alert=True)
        return

    text = (
        "💳 <b>پرداخت کارت به کارت — افزایش حجم</b>\n\n"
        f"➕ مقدار: {gb} GB\n"
        f"💰 مبلغ: <b>{price:,} تومان</b>\n\n"
        f"💳 شماره کارت:\n<code>{card}</code>\n\n"
        f"👤 به نام: <b>{holder or '---'}</b>\n\n"
        "بعد از انتقال وجه، تصویر رسید را همینجا ارسال کنید."
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML")
    bot.register_next_step_handler(call.message, receive_increase_receipt, service_id, gb)


def receive_increase_receipt(message, service_id, gb):
    if not message.photo:
        sent = bot.send_message(message.chat.id, "❌ لطفاً تصویر رسید را ارسال کن.")
        bot.register_next_step_handler(sent, receive_increase_receipt, service_id, gb)
        return

    service = _get_owned_service(service_id, message.from_user.id)
    if not service:
        bot.send_message(message.chat.id, "❌ سرویس پیدا نشد.")
        return

    price_per_gb = int(get_setting("extra_gb_price", "0") or 0)
    price = gb * price_per_gb

    file_id = message.photo[-1].file_id
    user_id = internal_user_id(message.from_user.id)

    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method, receipt_file_id, receipt_type,
     type, target_service_id, extra_volume, status, created_at, updated_at)
    VALUES (?, ?, ?, 'manual', ?, 'photo', 'increase', ?, ?, 'pending', ?, ?)
    """, (
        user_id, service["plan_id"], price, file_id,
        service_id, gb, now(), now()
    ))

    bot.send_message(
        message.chat.id,
        "✅ رسید شما ثبت شد.\n\n"
        "⏳ درخواست افزایش حجم در انتظار بررسی مدیریت است."
    )


# ============================================================
# APPLY MANUAL RENEW/INCREASE — بعد از تأیید ادمین صدا زده می‌شود
# (این تابع از handlers_payment.py فراخوانی می‌شود)
# ============================================================

def apply_manual_renew_or_increase(payment):
    service = db_execute(
        "SELECT * FROM services WHERE id=?",
        (payment["target_service_id"],),
        fetchone=True
    )
    if not service:
        return False, "سرویس پیدا نشد"

    user = db_execute(
        "SELECT * FROM users WHERE id=?",
        (payment["user_id"],),
        fetchone=True
    )

    if payment["type"] == "renew":
        new_expiry = _extend_expiry(service["expires_at"], payment["extra_days"])
        db_execute("""
        UPDATE services
        SET expires_at=?, used_volume=0, status='active', updated_at=?
        WHERE id=?
        """, (new_expiry, now(), service["id"]))

        if user:
            bot.send_message(
                user["telegram_id"],
                f"🎉 <b>تمدید سرویس تأیید شد!</b>\n\n"
                f"📅 تاریخ انقضای جدید: <code>{new_expiry}</code>",
                parse_mode="HTML"
            )
        return True, "renewed"

    if payment["type"] == "increase":
        db_execute("""
        UPDATE services
        SET volume=volume+?, updated_at=?
        WHERE id=?
        """, (payment["extra_volume"], now(), service["id"]))

        if user:
            bot.send_message(
                user["telegram_id"],
                f"🎉 <b>افزایش حجم تأیید شد!</b>\n\n"
                f"➕ {payment['extra_volume']} GB به حجم سرویس شما اضافه شد.",
                parse_mode="HTML"
            )
        return True, "increased"

    return False, "نوع پرداخت نامعتبر"


# ============================================================
# تنظیم سریع قیمت هر گیگابایت افزایش حجم (فقط ادمین)
# ============================================================

@bot.message_handler(commands=["setgbprice"])
@admin_only
def set_gb_price(message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "فرمت درست:\n/setgbprice 5000")
        return
    set_setting("extra_gb_price", parts[1])
    bot.reply_to(message, f"✅ قیمت هر گیگابایت افزایش حجم روی {int(parts[1]):,} تومان تنظیم شد.")
