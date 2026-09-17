# ============================================================
# handlers_shop.py
# نمایش پلن‌ها، جزئیات پلن و سرویس‌های کاربر
# ============================================================

from telebot import types

from config import bot
from database import db_execute, get_setting
from models import internal_user_id
from force_join import force_join_ok
from keyboards import force_join_markup


# ============================================================
# PLAN LISTING
# ============================================================

def plans_keyboard():
    plans = db_execute("""
    SELECT * FROM plans
    WHERE active=1
    ORDER BY sort_order, id
    """, fetchall=True)

    kb = types.InlineKeyboardMarkup()

    for plan in plans:
        kb.add(
            types.InlineKeyboardButton(
                f"💎 {plan['name']} | {plan['price']:,} تومان",
                callback_data=f"plan:{plan['id']}"
            )
        )

    return kb


@bot.message_handler(func=lambda m: m.text == "🛒 خرید VPN")
def buy_vpn(message):
    if not force_join_ok(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "🔒 ابتدا عضو کانال شوید.",
            reply_markup=force_join_markup()
        )
        return

    bot.send_message(
        message.chat.id,
        "💎 <b>انتخاب پلن</b>\n\n"
        "پلن موردنظر خود را انتخاب کنید:",
        reply_markup=plans_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("plan:"))
def select_plan(call):
    plan_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT * FROM plans WHERE id=? AND active=1",
        (plan_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(
            call.id,
            "پلن پیدا نشد",
            show_alert=True
        )
        return

    text = (
        "💎 <b>جزئیات پلن</b>\n\n"
        f"📦 نام: {plan['name']}\n"
        f"📊 حجم: {plan['volume']} GB\n"
        f"⏳ مدت: {plan['duration']} روز\n"
        f"📱 دستگاه: {plan['devices']}\n"
        f"💰 قیمت: {plan['price']:,} تومان\n\n"
        "روش پرداخت را انتخاب کنید:"
    )

    kb = types.InlineKeyboardMarkup()

    if get_setting("manual_payment_enabled", "1") == "1":
        kb.add(
            types.InlineKeyboardButton(
                "💳 کارت به کارت",
                callback_data=f"manual:{plan_id}"
            )
        )

    if get_setting("online_payment_enabled", "0") == "1":
        kb.add(
            types.InlineKeyboardButton(
                "🌐 پرداخت آنلاین",
                callback_data=f"online:{plan_id}"
            )
        )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="back_plans"
        )
    )

    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb
    )


# ============================================================
# MY SERVICES
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
            "📭 شما هنوز سرویسی ندارید."
        )
        return

    kb = types.InlineKeyboardMarkup()

    for service in services:
        status = "🟢" if service["status"] == "active" else "🔴"

        kb.add(
            types.InlineKeyboardButton(
                f"{status} {service['plan_name'] or 'سرویس'}",
                callback_data=f"service:{service['id']}"
            )
        )

    bot.send_message(
        message.chat.id,
        "🛡 <b>سرویس‌های من</b>\n\n"
        "سرویس را انتخاب کن:",
        reply_markup=kb
    )


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

    remaining = max(0, service["volume"] - service["used_volume"])

    text = (
        "🛡 <b>جزئیات سرویس</b>\n\n"
        f"📦 پلن: {service['plan_name'] or '---'}\n"
        f"📊 حجم کل: {service['volume']} GB\n"
        f"📈 باقی‌مانده: {remaining} GB\n"
        f"📱 دستگاه: {service['devices']}\n"
        f"⏳ انقضا: {service['expires_at'] or '---'}\n"
        f"📌 وضعیت: {service['status']}\n"
    )

    kb = types.InlineKeyboardMarkup()

    kb.add(types.InlineKeyboardButton("🔐 کانفیگ", callback_data=f"config:{service_id}"))
    kb.add(types.InlineKeyboardButton("🔄 تمدید", callback_data=f"renew:{service_id}"))
    kb.add(types.InlineKeyboardButton("📊 افزایش حجم", callback_data=f"increase:{service_id}"))

    bot.send_message(call.message.chat.id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("config:"))
def service_config(call):
    service_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)

    service = db_execute("""
    SELECT * FROM services
    WHERE id=? AND user_id=?
    """, (service_id, user_id), fetchone=True)

    if not service:
        return

    config = service["config"] or "لینک اشتراک هنوز موجود نیست."

    bot.send_message(
        call.message.chat.id,
        f"🔗 <b>لینک اشتراک سرویس</b>\n\n"
        f"<code>{config}</code>"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("renew:"))
def renew_service(call):
    bot.send_message(
        call.message.chat.id,
        "🔄 تمدید سرویس از داخل سیستم پرداخت انجام می‌شود.\n\n"
        "در مرحله بعد پلن تمدید را انتخاب می‌کنیم."
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("increase:"))
def increase_service(call):
    bot.send_message(
        call.message.chat.id,
        "📊 افزایش حجم آماده مدیریت است.\n\n"
        "در مرحله بعد حجم‌های قابل خرید نمایش داده می‌شوند."
    )
