# ============================================================
# handlers_shop.py
# نمایش پنل‌ها، پلن‌های هر پنل، جزئیات پلن و سرویس‌های کاربر
# ============================================================
import re
from datetime import datetime

from telebot import types
from config import bot
from database import db_execute, get_setting
from models import internal_user_id, get_user, is_superadmin
from force_join import force_join_ok
from keyboards import force_join_markup, user_keyboard
from pasarguard_api import pasarguard_get_user_usage, pasarguard_delete_service

USERNAME_PREFIX = "virangarvpn."

# ============================================================
# STEP 1: PANEL LIST
# ============================================================

def active_panels_with_plans():
    return db_execute("""
    SELECT DISTINCT panels.*
    FROM panels
    JOIN plans ON plans.panel_id = panels.id
    WHERE panels.active=1 AND plans.active=1
    ORDER BY panels.id
    """, fetchall=True)


def panels_keyboard():
    panels = active_panels_with_plans()
    kb = types.InlineKeyboardMarkup()
    for panel in panels:
        kb.add(
            types.InlineKeyboardButton(
                f"🖥 {panel['name']}",
                callback_data=f"buypanel:{panel['id']}"
            )
        )
    return kb, panels


@bot.message_handler(func=lambda m: m.text == "🛒 خرید VPN")
def buy_vpn(message):
    if not force_join_ok(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "🔒 ابتدا عضو کانال شوید.",
            reply_markup=force_join_markup()
        )
        return
    show_panels(message.chat.id)


def show_panels(chat_id):
    kb, panels = panels_keyboard()
    if not panels:
        bot.send_message(chat_id, "❌ در حال حاضر هیچ پنل فعالی با پلن موجود نیست.")
        return
    bot.send_message(
        chat_id,
        "🖥 <b>انتخاب پنل</b>\n\n"
        "لطفاً یکی از پنل‌های زیر را انتخاب کنید:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data == "buy_back_home")
def buy_back_home(call):
    bot.answer_callback_query(call.id)
    show_panels(call.message.chat.id)


# ============================================================
# STEP 2: PLAN LIST (per panel)
# ============================================================

def plans_keyboard(panel_id):
    plans = db_execute("""
    SELECT * FROM plans
    WHERE active=1 AND panel_id=?
    ORDER BY sort_order, id
    """, (panel_id,), fetchall=True)
    kb = types.InlineKeyboardMarkup()
    for plan in plans:
        kb.add(
            types.InlineKeyboardButton(
                f"💎 {plan['name']} | {plan['price']:,} تومان",
                callback_data=f"buyplan:{plan['id']}"
            )
        )
    kb.add(
        types.InlineKeyboardButton("🔙 بازگشت", callback_data="buy_back_home")
    )
    kb.add(
        types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home")
    )
    return kb, plans


@bot.callback_query_handler(func=lambda call: call.data.startswith("buypanel:"))
def select_panel(call):
    panel_id = int(call.data.split(":")[1])
    panel = db_execute(
        "SELECT * FROM panels WHERE id=? AND active=1",
        (panel_id,),
        fetchone=True
    )
    if not panel:
        bot.answer_callback_query(call.id, "این پنل دیگر فعال نیست.", show_alert=True)
        return

    kb, plans = plans_keyboard(panel_id)
    bot.answer_callback_query(call.id)

    if not plans:
        bot.edit_message_text(
            f"🖥 <b>{panel['name']}</b>\n\n"
            "❌ برای این پنل هنوز پلنی تعریف نشده.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    bot.edit_message_text(
        f"🖥 پنل: <b>{panel['name']}</b>\n\n"
        "💎 یکی از پلن‌های زیر را انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# STEP 3: PLAN DETAILS -> ASK CUSTOM NAME
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("buyplan:"))
def select_plan(call):
    plan_id = int(call.data.split(":")[1])
    plan = db_execute(
        "SELECT * FROM plans WHERE id=? AND active=1",
        (plan_id,),
        fetchone=True
    )
    if not plan:
        bot.answer_callback_query(call.id, "پلن پیدا نشد", show_alert=True)
        return

    panel_id = plan["panel_id"]
    text = (
        "💎 <b>جزئیات پلن</b>\n\n"
        f"📦 نام: {plan['name']}\n"
        f"📊 حجم: {plan['volume']} GB\n"
        f"⏳ مدت: {plan['duration']} روز\n"
        f"📱 دستگاه: {plan['devices']}\n"
        f"💰 قیمت: {plan['price']:,} تومان\n\n"
        "🏷 یک نام دلخواه (فقط حروف انگلیسی کوچک و عدد) برای سرویس خود ارسال کنید:\n\n"
        f"نام نهایی به‌صورت <code>{USERNAME_PREFIX}nameshoma</code> ساخته می‌شود.\n"
        "مثال: <code>ali</code>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"buypanel:{panel_id}"))
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))

    bot.answer_callback_query(call.id)
    sent = bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    bot.register_next_step_handler(sent, receive_username, plan_id)


def receive_username(message, plan_id):
    raw = (message.text or "").strip().lower()

    if not re.fullmatch(r"[a-z0-9_]{2,20}", raw):
        sent = bot.send_message(
            message.chat.id,
            "❌ نام نامعتبر است.\n\n"
            "فقط از حروف انگلیسی کوچک، عدد و _ استفاده کنید (۲ تا ۲۰ کاراکتر).\n\n"
            "دوباره ارسال کنید:"
        )
        bot.register_next_step_handler(sent, receive_username, plan_id)
        return

    plan = db_execute(
        "SELECT * FROM plans WHERE id=? AND active=1",
        (plan_id,),
        fetchone=True
    )
    if not plan:
        bot.send_message(message.chat.id, "❌ این پلن دیگر موجود نیست.")
        return

    username = f"{USERNAME_PREFIX}{raw}"

    existing_service = db_execute(
        "SELECT id FROM services WHERE username=?",
        (username,),
        fetchone=True
    )
    existing_pending_payment = db_execute(
        "SELECT id FROM payments WHERE custom_username=? AND status='pending'",
        (username,),
        fetchone=True
    )

    if existing_service or existing_pending_payment:
        sent = bot.send_message(
            message.chat.id,
            "❌ این نام قبلاً استفاده شده یا در انتظار تأیید یک پرداخت دیگر است.\n\n"
            "لطفاً یک نام دیگر انتخاب کنید:"
        )
        bot.register_next_step_handler(sent, receive_username, plan_id)
        return

    show_payment_methods(message.chat.id, message.from_user.id, plan, username)


# ============================================================
# STEP 4: PAYMENT METHOD SELECTION
# ============================================================

def show_payment_methods(chat_id, telegram_id, plan, username):
    user = get_user(telegram_id)
    balance = user["balance"] if user else 0

    text = (
        "✅ <b>تأیید سفارش</b>\n\n"
        f"💎 پلن: {plan['name']}\n"
        f"💰 قیمت: {plan['price']:,} تومان\n"
        f"🏷 نام سرویس: <code>{username}</code>\n\n"
        f"💰 موجودی کیف پول شما: {balance:,} تومان\n\n"
        "روش پرداخت را انتخاب کنید:"
    )
    kb = types.InlineKeyboardMarkup()
    if get_setting("manual_payment_enabled", "1") == "1":
        kb.add(
            types.InlineKeyboardButton(
                "💳 کارت به کارت",
                callback_data=f"manual:{plan['id']}:{username}"
            )
        )
    kb.add(
        types.InlineKeyboardButton(
            "💰 پرداخت از کیف پول",
            callback_data=f"walletpay:{plan['id']}:{username}"
        )
    )
    if get_setting("online_payment_enabled", "0") == "1":
        kb.add(
            types.InlineKeyboardButton(
                "🌐 پرداخت آنلاین",
                callback_data=f"online:{plan['id']}"
            )
        )
    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data=f"buypanel:{plan['panel_id']}"
        )
    )
    kb.add(
        types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home")
    )
    bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")


# ============================================================
# MY SERVICES — HELPERS
# ============================================================

def progress_bar(used, total, length=10):
    if not total or total <= 0:
        pct = 0
    else:
        pct = min(1, used / total)
    filled = int(pct * length)
    return "🟩" * filled + "⬜️" * (length - filled) + f"  {int(pct * 100)}٪"


def days_left(expires_at):
    if not expires_at:
        return None
    try:
        expire_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
        delta = (expire_dt - datetime.utcnow()).days
        return delta
    except Exception:
        return None


def _safe_get(row, key, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return value if value is not None else default


def service_label(service):
    """
    برچسب نمایشی سرویس به‌صورت خودکار از روی «حجم کل فعلی» و
    «مجموع روزهای خریداری‌شده» ساخته می‌شود، مثل «20GB 60روزه».
    این عدد با هر تمدید یا افزایش حجم به‌روز می‌ماند، چون هم
    volume و هم total_duration_days هرکدام جمع‌شونده هستند.
    اگر سرویس تست باشد (بدون پلن)، برچسب ثابت «سرویس تست» نمایش
    داده می‌شود.
    """
    if not service["plan_id"]:
        return "🎁 سرویس تست"

    volume = service["volume"]
    total_duration = _safe_get(service, "total_duration_days")

    if total_duration is None:
        # هنوز هیچ تمدیدی انجام نشده؛ از مدت پلن اصلی به‌عنوان مقدار پایه استفاده کن
        total_duration = _safe_get(service, "plan_duration", 0)

    return f"{volume}GB {total_duration}روزه"


def _services_list_keyboard(services):
    kb = types.InlineKeyboardMarkup()
    for service in services:
        status_icon = "🟢" if service["status"] == "active" else "🔴"
        remaining_days = days_left(service["expires_at"])
        days_str = f" | {remaining_days} روز مانده" if remaining_days is not None else ""

        kb.add(
            types.InlineKeyboardButton(
                f"{status_icon} {service_label(service)}{days_str}",
                callback_data=f"service:{service['id']}"
            )
        )
    kb.add(
        types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home")
    )
    return kb


def _get_user_services(telegram_id):
    user_id = internal_user_id(telegram_id)
    return db_execute("""
    SELECT services.*, plans.name AS plan_name, plans.duration AS plan_duration
    FROM services
    LEFT JOIN plans ON plans.id=services.plan_id
    WHERE services.user_id=?
    ORDER BY services.id DESC
    """, (user_id,), fetchall=True)


def _get_panel_for_service(service):
    """
    service یک sqlite3.Row است، نه دیکشنری معمولی — پس .get() ندارد.
    """
    try:
        panel_id = service["panel_id"]
    except (KeyError, IndexError):
        return None

    if not panel_id:
        return None

    return db_execute("SELECT * FROM panels WHERE id=?", (panel_id,), fetchone=True)


# ============================================================
# MY SERVICES — LIST
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🛡 سرویس‌های من")
def my_services(message):
    services = _get_user_services(message.from_user.id)

    if not services:
        bot.send_message(
            message.chat.id,
            "📭 شما هنوز سرویسی ندارید.\n\n"
            "برای خرید یا دریافت تست رایگان از منوی اصلی اقدام کنید."
        )
        return

    kb = _services_list_keyboard(services)

    bot.send_message(
        message.chat.id,
        "🛡 <b>سرویس‌های من</b>\n\n"
        "یکی از سرویس‌های زیر را انتخاب کن:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data == "services_back")
def services_back(call):
    bot.answer_callback_query(call.id)

    services = _get_user_services(call.from_user.id)

    if not services:
        bot.edit_message_text(
            "📭 شما هنوز سرویسی ندارید.",
            call.message.chat.id,
            call.message.message_id
        )
        return

    kb = _services_list_keyboard(services)

    bot.edit_message_text(
        "🛡 <b>سرویس‌های من</b>\n\n"
        "یکی از سرویس‌های زیر را انتخاب کن:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# بازگشت یکسان به منوی اصلی — همه‌جای ربات همین را صدا می‌زنند
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "go_home")
def go_home(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
    except Exception:
        pass

    bot.send_message(
        call.message.chat.id,
        "🏠 بازگشت به منوی اصلی",
        reply_markup=user_keyboard(
            is_super_admin=is_superadmin(call.from_user.id)
        )
    )


@bot.callback_query_handler(func=lambda call: call.data == "services_home_back")
def services_home_back(call):
    go_home(call)


# ============================================================
# MY SERVICES — DETAILS (+ مصرف زنده از پنل + دکمه بروزرسانی)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("service:"))
def service_details(call):
    service_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)

    service = db_execute("""
    SELECT services.*, plans.name AS plan_name, plans.panel_id AS panel_id,
           plans.duration AS plan_duration
    FROM services
    LEFT JOIN plans ON plans.id=services.plan_id
    WHERE services.id=? AND services.user_id=?
    """, (
        service_id,
        user_id
    ), fetchone=True)

    if not service:
        bot.answer_callback_query(
            call.id,
            "سرویس پیدا نشد.",
            show_alert=True
        )
        return

    # --- تلاش برای گرفتن مصرف زنده از پنل ---
    used_volume = service["used_volume"]
    total_volume = service["volume"]
    live_note = ""
    panel = _get_panel_for_service(service)

    if panel and service["username"]:
        usage = pasarguard_get_user_usage(panel, service["username"])
        if usage.get("success"):
            used_volume = round(usage["used_gb"], 2)
            if usage.get("data_limit_gb"):
                total_volume = round(usage["data_limit_gb"], 2)
            db_execute(
                "UPDATE services SET used_volume=?, volume=? WHERE id=?",
                (used_volume, total_volume, service_id)
            )
        else:
            live_note = "\n⚠️ دریافت مصرف زنده از پنل ناموفق بود؛ آخرین مقدار ذخیره‌شده نمایش داده می‌شود."

    remaining_volume = max(0, total_volume - used_volume)
    remaining_days = days_left(service["expires_at"])

    status_map = {
        "active": "🟢 فعال",
        "expired": "🔴 منقضی شده",
        "disabled": "⚫️ غیرفعال",
    }
    status_text = status_map.get(service["status"], service["status"])

    if remaining_days is None:
        days_text = "نامشخص"
    elif remaining_days < 0:
        days_text = "منقضی شده ❗️"
    else:
        days_text = f"{remaining_days} روز"

    text = (
        f"🛡 <b>{service_label(service)}</b>\n\n"
        f"👤 نام کاربری: <code>{service['username'] or '---'}</code>\n"
        f"📌 وضعیت: {status_text}\n"
        f"⏳ زمان باقی‌مانده: {days_text}\n\n"
        f"📊 <b>حجم مصرفی</b>\n"
        f"{progress_bar(used_volume, total_volume)}\n"
        f"مصرف‌شده: {used_volume} GB از {total_volume} GB\n"
        f"باقی‌مانده: {remaining_volume} GB\n\n"
        f"📱 تعداد دستگاه مجاز: {service['devices']}"
        f"{live_note}"
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("🔐 دریافت کانفیگ", callback_data=f"config:{service_id}")
    )
    kb.add(
        types.InlineKeyboardButton("🔄 تمدید سرویس", callback_data=f"renew:{service_id}"),
        types.InlineKeyboardButton("📈 افزایش حجم", callback_data=f"increase:{service_id}")
    )
    kb.add(
        types.InlineKeyboardButton("🗑 حذف سرویس", callback_data=f"delsvc_ask:{service_id}")
    )
    kb.add(
        types.InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"service:{service_id}")
    )
    kb.add(
        types.InlineKeyboardButton("🔙 بازگشت به لیست سرویس‌ها", callback_data="services_back")
    )

    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception as e:
        # اگر محتوا نسبت به قبل تغییری نکرده باشد، تلگرام خطای
        # "message is not modified" می‌دهد که بی‌خطر است و باید نادیده گرفته شود
        if "message is not modified" not in str(e):
            raise


@bot.callback_query_handler(func=lambda call: call.data.startswith("config:"))
def service_config(call):
    service_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)
    service = db_execute("""
    SELECT * FROM services
    WHERE id=? AND user_id=?
    """, (service_id, user_id), fetchone=True)

    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    config = service["config"] or "لینک اشتراک هنوز موجود نیست."

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"service:{service_id}"))

    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        f"🔗 <b>لینک اشتراک سرویس</b>\n\n"
        f"<code>{config}</code>",
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# حذف سرویس — با تأییدیه
# همیشه از دیتابیس محلی حذف می‌شود، صرف نظر از این‌که روی پنل
# پیدا شود یا نه (ممکن است کاربر یا ادمین قبلاً از پنل حذفش کرده
# باشد). تلاش برای حذف از پنل انجام می‌شود و اگر ناموفق بود فقط
# به‌عنوان هشدار نمایش داده می‌شود، نه مانعی برای حذف محلی.
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("delsvc_ask:"))
def delete_service_ask(call):
    service_id = int(call.data.split(":")[1])
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"delsvc_confirm:{service_id}"),
        types.InlineKeyboardButton("❌ انصراف", callback_data=f"service:{service_id}")
    )

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "⚠️ <b>حذف سرویس</b>\n\n"
        "با تأیید، این سرویس از لیست سرویس‌های شما حذف می‌شود "
        "(اگر روی پنل هم هنوز فعال باشد، از آنجا نیز حذف می‌شود).\n"
        "این عمل قابل بازگشت نیست. آیا مطمئنید؟",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("delsvc_confirm:"))
def delete_service_confirm(call):
    service_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)

    service = db_execute("""
    SELECT services.*, plans.panel_id AS panel_id
    FROM services
    LEFT JOIN plans ON plans.id=services.plan_id
    WHERE services.id=? AND services.user_id=?
    """, (service_id, user_id), fetchone=True)

    if not service:
        bot.answer_callback_query(call.id, "سرویس پیدا نشد.", show_alert=True)
        return

    panel_warning = ""
    panel = _get_panel_for_service(service)
    if panel and service["username"]:
        result = pasarguard_delete_service(panel, service["username"])
        if not result.get("success"):
            # از پنل حذف نشد (شاید از قبل روی پنل نبوده، یا پنل موقتاً
            # در دسترس نیست) — این جلوی حذف محلی را نمی‌گیرد
            panel_warning = (
                f"\n\n⚠️ توجه: حذف از پنل انجام نشد ({result.get('error')})."
                "\nاحتمالاً این سرویس از قبل روی پنل وجود نداشته است."
            )

    # همیشه از دیتابیس محلی حذف می‌شود
    db_execute("DELETE FROM services WHERE id=?", (service_id,))

    bot.answer_callback_query(call.id, "✅ سرویس حذف شد.")

    services = _get_user_services(call.from_user.id)
    if not services:
        bot.edit_message_text(
            f"📭 شما هیچ سرویسی ندارید.{panel_warning}",
            call.message.chat.id,
            call.message.message_id
        )
        return

    kb = _services_list_keyboard(services)
    bot.edit_message_text(
        f"🛡 <b>سرویس‌های من</b>\n\n"
        f"یکی از سرویس‌های زیر را انتخاب کن:{panel_warning}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )
