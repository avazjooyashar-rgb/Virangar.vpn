# ============================================================
# handlers/user_buy.py
# خرید VPN: انتخاب پلن، پرداخت کارت به کارت، پرداخت آنلاین
# ============================================================

from telebot import types

from config import bot
from db import db_execute, get_setting, now
from users import internal_user_id
from force_join import force_join_ok, force_join_markup
from keyboards import plans_keyboard
from handlers.payment_flow import notify_admin_payment


@bot.message_handler(func=lambda m: m.text == "🛒 خرید VPN")
def buy_vpn(message):
    if not force_join_ok(message.from_user.id):
        bot.send_message(
            message.chat.id, "🔒 ابتدا عضو کانال شوید.",
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
        (plan_id,), fetchone=True
    )

    if not plan:
        bot.answer_callback_query(call.id, "پلن پیدا نشد", show_alert=True)
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
        kb.add(types.InlineKeyboardButton(
            "💳 کارت به کارت", callback_data=f"manual:{plan_id}"
        ))

    if get_setting("online_payment_enabled", "0") == "1":
        kb.add(types.InlineKeyboardButton(
            "🌐 پرداخت آنلاین", callback_data=f"online:{plan_id}"
        ))

    kb.add(types.InlineKeyboardButton("🔙 برگشت", callback_data="back_plans"))

    bot.edit_message_text(
        text, call.message.chat.id, call.message.message_id, reply_markup=kb
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("manual:"))
def manual_payment(call):
    plan_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT * FROM plans WHERE id=? AND active=1",
        (plan_id,), fetchone=True
    )

    if not plan:
        return

    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")

    if not card:
        bot.answer_callback_query(
            call.id, "پرداخت کارت به کارت فعلاً تنظیم نشده.", show_alert=True
        )
        return

    text = (
        "💳 <b>پرداخت کارت به کارت</b>\n\n"
        f"💰 مبلغ: <b>{plan['price']:,} تومان</b>\n\n"
        f"💳 شماره کارت:\n<code>{card}</code>\n\n"
        f"👤 به نام: <b>{holder or '---'}</b>\n\n"
        "بعد از انتقال وجه، تصویر رسید را همینجا ارسال کنید."
    )

    bot.send_message(call.message.chat.id, text)

    bot.register_next_step_handler(call.message, receive_plan_receipt, plan_id)


def receive_plan_receipt(message, plan_id):
    if not message.photo:
        bot.send_message(message.chat.id, "❌ لطفاً تصویر رسید را ارسال کن.")
        bot.register_next_step_handler(message, receive_plan_receipt, plan_id)
        return

    file_id = message.photo[-1].file_id
    user_id = internal_user_id(message.from_user.id)

    plan = db_execute("SELECT * FROM plans WHERE id=?", (plan_id,), fetchone=True)
    if not plan:
        return

    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method,
     receipt_file_id, receipt_type,
     status, created_at, updated_at)
    VALUES (?, ?, ?, 'manual', ?, 'photo', 'pending', ?, ?)
    """, (user_id, plan_id, plan["price"], file_id, now(), now()))

    payment = db_execute("""
    SELECT * FROM payments
    WHERE user_id=? AND plan_id=? AND status='pending'
    ORDER BY id DESC LIMIT 1
    """, (user_id, plan_id), fetchone=True)

    notify_admin_payment(payment)

    bot.send_message(
        message.chat.id,
        "✅ رسید شما ثبت شد.\n\n"
        "⏳ پرداخت در انتظار بررسی مدیریت است."
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("online:"))
def online_payment(call):
    plan_id = int(call.data.split(":")[1])

    provider = get_setting("gateway_provider", "")

    if not provider:
        bot.answer_callback_query(
            call.id, "درگاه پرداخت تنظیم نشده.", show_alert=True
        )
        return

    bot.send_message(
        call.message.chat.id,
        "🌐 درگاه آنلاین فعال است، اما اتصال نهایی "
        "به API درگاه انتخابی نیاز به مشخصات همان درگاه دارد."
    )
