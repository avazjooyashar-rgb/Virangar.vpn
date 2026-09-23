# ============================================================
# handlers_shop.py
# نمایش پنل‌ها، پلن‌های هر پنل، جزئیات پلن و سرویس‌های کاربر
# ============================================================
import re
from datetime import datetime

from telebot import types
from config import bot
from database import db_execute, get_setting
from models import internal_user_id, get_user
from force_join import force_join_ok
from keyboards import force_join_markup

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


def service_label(service):
    if service["plan_name"]:
        return service["plan_name"]
    return "🎁 سرویس تست"


# ============================================================
# MY SERVICES — LIST
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🛡 سرویس‌های من")
def my_services(message):
    user_id = internal_user_id(message.from_user.id)
    services = db_execute("""
    SELECT services.*, plans.name AS plan_name
    FROM services
    LEFT JOIN plans ON plans.id=services.plan_id
    WHERE services.user_id=?
    ORDER BY services.id DESC
    """, (user_id,), fetchall=True)

    if not services:
        bot.send_message(
            message.chat.id,
            "📭 شما هنوز سرویسی ندارید.\n\n"
            "برای خرید یا دریافت تست رایگان از منوی اصلی اقدام کنید."
        )
        return

    kb = types.InlineKeyboardMarkup()
    for service in services:
        status_icon = "🟢" if service["status"] == "active" else "🔴"
        remaining_days = days_left(service["expires_at"])
        days_str = f" | {remaining_days} روز" if remaining_days is not None else ""

        kb.add(
            types.InlineKeyboardButton(
                f"{status_icon} {service_label(service)}{days_str}",
                callback_data=f"service:{service['id']}"
            )
        )

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

    user_id = internal_user_id(call.from_user.id)
    services = db_execute("""
    SELECT services.*, plans.name AS plan_name
    FROM services
    LEFT JOIN plans ON plans.id=services.plan_id
    WHERE services.user_id=?
    ORDER BY services.id DESC
    """, (user_id,), fetchall=True)

    if not services:
        bot.edit_message_text(
            "📭 شما هنوز سرویسی ندارید.",
            call.message.chat.id,
            call.message.message_id
        )
        return

    kb = types.InlineKeyboardMarkup()
    for service in services:
        status_icon = "🟢" if service["status"] == "active" else "🔴"
        remaining_days = days_left(service["expires_at"])
        days_str = f" | {remaining_days} روز" if remaining_days is not None else ""

        kb.add(
            types.InlineKeyboardButton(
                f"{status_icon} {service_label(service)}{days_str}",
                callback_data=f"service:{service['id']}"
            )
        )

    bot.edit_message_text(
        "🛡 <b>سرویس‌های من</b>\n\n"
        "یکی از سرویس‌های زیر را انتخاب کن:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# MY SERVICES — DETAILS
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("service:"))
def service_details(call):
    service_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)

    service = db_execute("""
    SELECT services.*, plans.name AS plan_name
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

    remaining_volume = max(0, service["volume"] - service["used_volume"])
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
        f"{progress_bar(service['used_volume'], service['volume'])}\n"
        f"مصرف‌شده: {service['used_volume']} GB از {service['volume']} GB\n"
        f"باقی‌مانده: {remaining_volume} GB\n\n"
        f"📱 تعداد دستگاه مجاز: {service['devices']}\n"
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
        types.InlineKeyboardButton("🔙 بازگشت به لیست سرویس‌ها", callback_data="services_back")
    )

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )


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

    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        f"🔗 <b>لینک اشتراک سرویس</b>\n\n"
        f"<code>{config}</code>",
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("renew:"))
def renew_service(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "🔄 <b>تمدید سرویس</b>\n\n"
        "این بخش به‌زودی به سیستم پرداخت وصل می‌شود.\n"
        "در حال حاضر برای تمدید با پشتیبانی در تماس باشید.",
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("increase:"))
def increase_service(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "📈 <b>افزایش حجم</b>\n\n"
        "این بخش به‌زودی به سیستم پرداخت وصل می‌شود.\n"
        "در حال حاضر برای افزایش حجم با پشتیبانی در تماس باشید.",
        parse_mode="HTML"
    )
