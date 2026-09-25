# ============================================================
# handlers_renewal.py
# تمدید سرویس و افزایش حجم — همیشه اول روی پنل PasarGuard اعمال
# می‌شود و فقط در صورت موفقیت پنل، دیتابیس داخلی آپدیت می‌شود.
# افزایش حجم دقیقاً مثل تمدید عمل می‌کند (هم حجم هم زمان اضافه
# می‌شود) و از روی جدول renewal_plans خوانده می‌شود.
# بعد از هر تمدید/افزایش موفق، total_duration_days نیز جمع می‌شود
# تا برچسب سرویس (مثل «20GB 60روزه») همیشه واقعی و به‌روز بماند.
# ============================================================
from datetime import datetime, timedelta

from telebot import types
from config import bot
from database import db_execute, get_setting, now
from models import internal_user_id, get_user
from pasarguard_api import pasarguard_apply_renewal


# ============================================================
# HELPERS
# ============================================================

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


def _safe_get(row, key, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return value if value is not None else default


def _next_total_duration(service, added_days):
    """
    مجموع روزهای خریداری‌شده تا الان + روزهای این تمدید/افزایش.
    اگر تا حالا هیچ تمدیدی انجام نشده (ستون خالی است)، از مدت
    پلن اصلی خرید به‌عنوان مقدار پایه استفاده می‌شود.
    """
    current_total = _safe_get(service, "total_duration_days")
    if current_total is None:
        current_total = _safe_get(service, "plan_duration", 0)
    return current_total + int(added_days)


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

    current_remaining = max(0, service["volume"] - service["used_volume"])
    new_remaining_estimate = current_remaining + service["plan_volume"]

    text = (
        "🔄 <b>تمدید سرویس</b>\n\n"
        f"📦 پلن: {service['plan_name']}\n"
        f"➕ حجم اضافه‌شونده: {service['plan_volume']} GB\n"
        f"📊 باقیمانده فعلی: {current_remaining} GB\n"
        f"📊 باقیمانده بعد از تمدید: تقریباً {new_remaining_estimate} GB\n"
        f"⏳ مدت اضافه‌شونده: {service['plan_duration']} روز\n"
        f"💰 هزینه: {service['plan_price']:,} تومان\n\n"
        "با تمدید، این مقدار حجم و زمان به سرویس فعلی اضافه می‌شود.\n"
        "مصرف قبلی شما صفر نمی‌شود؛ فقط سقف حجم بالا می‌رود.\n\n"
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

    panel = _get_panel(service["panel_id"])
    if not panel or not service["username"]:
        bot.answer_callback_query(
            call.id,
            "❌ اطلاعات پنل این سرویس ناقص است. به پشتیبانی اطلاع دهید.",
            show_alert=True
        )
        return

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
    new_total_duration = _next_total_duration(service, service["plan_duration"])

    db_execute("UPDATE users SET balance=balance-? WHERE id=?", (price, user["id"]))
    db_execute("""
    UPDATE services
    SET volume=?, expires_at=?, status='active', updated_at=?, total_duration_days=?
    WHERE id=?
    """, (new_total_volume, new_expiry, now(), new_total_duration, service_id))
    db_execute("""
    INSERT INTO transactions
    (user_id, amount, type, description, reference, created_at)
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

    remaining_after = round(max(0, new_total_volume - service["used_volume"]), 2)

    bot.answer_callback_query(call.id, "✅ سرویس با موفقیت تمدید شد.")
    bot.send_message(
        call.message.chat.id,
        f"🎉 <b>تمدید موفق</b>\n\n"
        f"📦 برچسب جدید سرویس: <code>{new_total_volume}GB {new_total_duration}روزه</code>\n"
        f"📊 باقیمانده فعلی: <code>{remaining_after} GB</code>\n"
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
     type, target_service_id, extra_days, extra_volume, status, created_at, updated_at)
    VALUES (?, ?, ?, 'manual', ?, 'photo', 'renew', ?, ?, ?, 'pending', ?, ?)
    """, (
        user_id, service["plan_id"], service["plan_price"], file_id,
        service_id, service["plan_duration"], service["plan_volume"], now(), now()
    ))

    bot.send_message(
        message.chat.id,
        "✅ رسید شما ثبت شد.\n\n"
        "⏳ درخواست تمدید در انتظار بررسی مدیریت است."
    )


# ============================================================
# INCREASE VOLUME — STEP 1: نمایش پلن‌های افزایش حجم (از renewal_plans)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("increase:") and call.data.count(":") == 1)
def increase_service(call):
    service_id = int(call.data.split(":")[1])
    service = _get_owned_service(service_id, call.from_user.id)

    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    packages = db_execute(
        "SELECT * FROM renewal_plans WHERE active=1 AND panel_id=? ORDER BY sort_order ASC, id ASC",
        (service["panel_id"],),
        fetchall=True
    )

    if not packages:
        bot.answer_callback_query(
            call.id,
            "فعلاً هیچ پلن افزایش حجمی برای پنل این سرویس تعریف نشده. با پشتیبانی تماس بگیرید.",
            show_alert=True
        )
        return

    kb = types.InlineKeyboardMarkup()
    for pkg in packages:
        kb.add(
            types.InlineKeyboardButton(
                f"📈 {pkg['name']} — {pkg['volume']}GB / {pkg['duration']}روز — {pkg['price']:,} تومان",
                callback_data=f"incpkg:{service_id}:{pkg['id']}"
            )
        )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"service:{service_id}"))

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "📈 <b>افزایش حجم سرویس</b>\n\n"
        "با انتخاب هرکدام از پلن‌های زیر، هم حجم و هم زمان سرویس شما اضافه می‌شود:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# INCREASE VOLUME — STEP 2: انتخاب روش پرداخت
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("incpkg:"))
def increase_package_selected(call):
    _, service_id, pkg_id = call.data.split(":")
    service_id = int(service_id)
    pkg_id = int(pkg_id)

    service = _get_owned_service(service_id, call.from_user.id)
    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    pkg = db_execute(
        "SELECT * FROM renewal_plans WHERE id=? AND active=1",
        (pkg_id,),
        fetchone=True
    )
    if not pkg:
        bot.answer_callback_query(call.id, "این پلن دیگر فعال نیست.", show_alert=True)
        return

    text = (
        "📈 <b>تأیید افزایش حجم</b>\n\n"
        f"🏷 پلن: {pkg['name']}\n"
        f"➕ حجم: {pkg['volume']} GB\n"
        f"⏳ مدت: {pkg['duration']} روز\n"
        f"💰 قیمت: {pkg['price']:,} تومان\n\n"
        "با تأیید، این حجم و زمان به سرویس فعلی شما اضافه می‌شود.\n\n"
        "روش پرداخت را انتخاب کنید:"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💰 پرداخت از کیف پول", callback_data=f"incwallet:{service_id}:{pkg_id}"))
    if get_setting("manual_payment_enabled", "1") == "1":
        kb.add(types.InlineKeyboardButton("💳 کارت به کارت", callback_data=f"inccard:{service_id}:{pkg_id}"))
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
    _, service_id, pkg_id = call.data.split(":")
    service_id = int(service_id)
    pkg_id = int(pkg_id)

    service = _get_owned_service(service_id, call.from_user.id)
    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    pkg = db_execute(
        "SELECT * FROM renewal_plans WHERE id=? AND active=1",
        (pkg_id,),
        fetchone=True
    )
    if not pkg:
        bot.answer_callback_query(call.id, "این پلن دیگر فعال نیست.", show_alert=True)
        return

    user = get_user(call.from_user.id)
    if user["balance"] < pkg["price"]:
        bot.answer_callback_query(
            call.id,
            f"❌ موجودی کافی نیست.\nموجودی: {user['balance']:,} | هزینه: {pkg['price']:,}",
            show_alert=True
        )
        return

    panel = _get_panel(service["panel_id"])
    if not panel or not service["username"]:
        bot.answer_callback_query(
            call.id,
            "❌ اطلاعات پنل این سرویس ناقص است.",
            show_alert=True
        )
        return

    result = pasarguard_apply_renewal(panel, service["username"], pkg["volume"], pkg["duration"])
    if not result.get("success"):
        bot.answer_callback_query(
            call.id,
            f"❌ افزایش حجم روی پنل ناموفق بود: {result.get('error')}",
            show_alert=True
        )
        return

    new_total_volume = round(result["data_limit_gb"], 2)
    new_expiry = datetime.utcfromtimestamp(result["expire"]).strftime("%Y-%m-%d %H:%M:%S")
    new_total_duration = _next_total_duration(service, pkg["duration"])

    db_execute("UPDATE users SET balance=balance-? WHERE id=?", (pkg["price"], user["id"]))
    db_execute("""
    UPDATE services
    SET volume=?, expires_at=?, status='active', updated_at=?, total_duration_days=?
    WHERE id=?
    """, (new_total_volume, new_expiry, now(), new_total_duration, service_id))
    db_execute("""
    INSERT INTO transactions
    (user_id, amount, type, description, reference, created_at)
    VALUES (?, ?, 'debit', ?, ?, ?)
    """, (user["id"], -pkg["price"], f"افزایش حجم ({pkg['name']})", f"increase:{service_id}", now()))
    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method, type, target_service_id,
     extra_days, extra_volume, status, created_at, updated_at)
    VALUES (?, ?, ?, 'wallet_increase', 'increase', ?, ?, ?, 'approved', ?, ?)
    """, (
        user["id"], service["plan_id"], pkg["price"], service_id,
        pkg["duration"], pkg["volume"], now(), now()
    ))

    remaining_after = round(max(0, new_total_volume - service["used_volume"]), 2)

    bot.answer_callback_query(call.id, "✅ حجم و زمان با موفقیت اضافه شد.")
    bot.send_message(
        call.message.chat.id,
        f"🎉 <b>افزایش حجم موفق</b>\n\n"
        f"📦 برچسب جدید سرویس: <code>{new_total_volume}GB {new_total_duration}روزه</code>\n"
        f"📊 باقیمانده فعلی: <code>{remaining_after} GB</code>\n"
        f"📅 تاریخ انقضای جدید: <code>{new_expiry}</code>",
        parse_mode="HTML"
    )


# ============================================================
# INCREASE VOLUME — کارت به کارت (نیاز به تأیید ادمین)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("inccard:"))
def increase_card(call):
    _, service_id, pkg_id = call.data.split(":")
    service_id = int(service_id)
    pkg_id = int(pkg_id)

    service = _get_owned_service(service_id, call.from_user.id)
    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    pkg = db_execute(
        "SELECT * FROM renewal_plans WHERE id=? AND active=1",
        (pkg_id,),
        fetchone=True
    )
    if not pkg:
        bot.answer_callback_query(call.id, "این پلن دیگر فعال نیست.", show_alert=True)
        return

    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")
    if not card:
        bot.answer_callback_query(call.id, "پرداخت کارت به کارت فعلاً تنظیم نشده.", show_alert=True)
        return

    text = (
        "💳 <b>پرداخت کارت به کارت — افزایش حجم</b>\n\n"
        f"🏷 پلن: {pkg['name']}\n"
        f"➕ حجم: {pkg['volume']} GB\n"
        f"⏳ مدت: {pkg['duration']} روز\n"
        f"💰 مبلغ: <b>{pkg['price']:,} تومان</b>\n\n"
        f"💳 شماره کارت:\n<code>{card}</code>\n\n"
        f"👤 به نام: <b>{holder or '---'}</b>\n\n"
        "بعد از انتقال وجه، تصویر رسید را همینجا ارسال کنید."
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML")
    bot.register_next_step_handler(call.message, receive_increase_receipt, service_id, pkg_id)


def receive_increase_receipt(message, service_id, pkg_id):
    if not message.photo:
        sent = bot.send_message(message.chat.id, "❌ لطفاً تصویر رسید را ارسال کن.")
        bot.register_next_step_handler(sent, receive_increase_receipt, service_id, pkg_id)
        return

    service = _get_owned_service(service_id, message.from_user.id)
    if not service:
        bot.send_message(message.chat.id, "❌ سرویس پیدا نشد.")
        return

    pkg = db_execute(
        "SELECT * FROM renewal_plans WHERE id=?",
        (pkg_id,),
        fetchone=True
    )
    if not pkg:
        bot.send_message(message.chat.id, "❌ پلن پیدا نشد.")
        return

    file_id = message.photo[-1].file_id
    user_id = internal_user_id(message.from_user.id)

    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method, receipt_file_id, receipt_type,
     type, target_service_id, extra_days, extra_volume, status, created_at, updated_at)
    VALUES (?, ?, ?, 'manual', ?, 'photo', 'increase', ?, ?, ?, 'pending', ?, ?)
    """, (
        user_id, service["plan_id"], pkg["price"], file_id,
        service_id, pkg["duration"], pkg["volume"], now(), now()
    ))

    bot.send_message(
        message.chat.id,
        "✅ رسید شما ثبت شد.\n\n"
        "⏳ درخواست افزایش حجم در انتظار بررسی مدیریت است."
    )


# ============================================================
# APPLY MANUAL RENEW/INCREASE — بعد از تأیید ادمین صدا زده می‌شود
# ============================================================

def apply_manual_renew_or_increase(payment):
    service = db_execute("""
    SELECT services.*, plans.panel_id AS panel_id, plans.duration AS plan_duration
    FROM services
    LEFT JOIN plans ON plans.id=services.plan_id
    WHERE services.id=?
    """, (payment["target_service_id"],), fetchone=True)

    if not service:
        return False, "سرویس پیدا نشد"

    user = db_execute(
        "SELECT * FROM users WHERE id=?",
        (payment["user_id"],),
        fetchone=True
    )

    panel = _get_panel(service["panel_id"])
    if not panel or not service["username"]:
        return False, "اطلاعات پنل این سرویس ناقص است"

    if payment["type"] == "renew":
        result = pasarguard_apply_renewal(
            panel, service["username"], payment["extra_volume"], payment["extra_days"]
        )
        if not result.get("success"):
            return False, f"خطای پنل: {result.get('error')}"

        new_total_volume = round(result["data_limit_gb"], 2)
        new_expiry = datetime.utcfromtimestamp(result["expire"]).strftime("%Y-%m-%d %H:%M:%S")
        new_total_duration = _next_total_duration(service, payment["extra_days"])

        db_execute("""
        UPDATE services
        SET volume=?, expires_at=?, status='active', updated_at=?, total_duration_days=?
        WHERE id=?
        """, (new_total_volume, new_expiry, now(), new_total_duration, service["id"]))

        remaining_after = round(max(0, new_total_volume - service["used_volume"]), 2)

        if user:
            bot.send_message(
                user["telegram_id"],
                f"🎉 <b>تمدید سرویس تأیید شد!</b>\n\n"
                f"📦 برچسب جدید سرویس: <code>{new_total_volume}GB {new_total_duration}روزه</code>\n"
                f"📊 باقیمانده فعلی: <code>{remaining_after} GB</code>\n"
                f"📅 تاریخ انقضای جدید: <code>{new_expiry}</code>",
                parse_mode="HTML"
            )
        return True, "renewed"

    if payment["type"] == "increase":
        result = pasarguard_apply_renewal(
            panel, service["username"], payment["extra_volume"], payment["extra_days"]
        )
        if not result.get("success"):
            return False, f"خطای پنل: {result.get('error')}"

        new_total_volume = round(result["data_limit_gb"], 2)
        new_expiry = datetime.utcfromtimestamp(result["expire"]).strftime("%Y-%m-%d %H:%M:%S")
        new_total_duration = _next_total_duration(service, payment["extra_days"])

        db_execute("""
        UPDATE services
        SET volume=?, expires_at=?, status='active', updated_at=?, total_duration_days=?
        WHERE id=?
        """, (new_total_volume, new_expiry, now(), new_total_duration, service["id"]))

        remaining_after = round(max(0, new_total_volume - service["used_volume"]), 2)

        if user:
            bot.send_message(
                user["telegram_id"],
                f"🎉 <b>افزایش حجم تأیید شد!</b>\n\n"
                f"📦 برچسب جدید سرویس: <code>{new_total_volume}GB {new_total_duration}روزه</code>\n"
                f"📊 باقیمانده فعلی: <code>{remaining_after} GB</code>\n"
                f"📅 تاریخ انقضای جدید: <code>{new_expiry}</code>",
                parse_mode="HTML"
            )
        return True, "increased"

    return False, "نوع پرداخت نامعتبر"
