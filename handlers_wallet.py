# ============================================================
# handlers_wallet.py
# کیف پول: نمایش موجودی، شارژ، تاریخچه تراکنش
# ============================================================

from telebot import types

from config import bot
from database import db_execute, get_setting, now
from models import get_user, internal_user_id
from handlers_payment import notify_admin_payment


@bot.message_handler(func=lambda m: m.text == "💰 کیف پول")
def wallet(message):
    user = get_user(message.from_user.id)
    balance = user["balance"] if user else 0

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💳 شارژ کیف پول", callback_data="wallet_topup"))
    kb.add(types.InlineKeyboardButton("📜 تاریخچه تراکنش", callback_data="wallet_history"))

    bot.send_message(
        message.chat.id,
        f"💰 <b>کیف پول</b>\n\n"
        f"موجودی: <b>{balance:,} تومان</b>",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda call: call.data == "wallet_topup")
def wallet_topup(call):
    bot.send_message(call.message.chat.id, "💳 مبلغ شارژ را به تومان وارد کن:")
    bot.register_next_step_handler(call.message, wallet_amount)


def wallet_amount(message):
    try:
        amount = int(message.text.replace(",", "").replace(" ", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "❌ مبلغ نامعتبر است.")
        return

    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")

    if not card:
        bot.send_message(message.chat.id, "❌ پرداخت کارت به کارت تنظیم نشده.")
        return

    bot.send_message(
        message.chat.id,
        f"💳 مبلغ <b>{amount:,} تومان</b> را به کارت زیر انتقال بده:\n\n"
        f"<code>{card}</code>\n"
        f"👤 {holder}\n\n"
        "سپس تصویر رسید را ارسال کن."
    )

    bot.register_next_step_handler(message, wallet_receipt, amount)


def wallet_receipt(message, amount):
    if not message.photo:
        bot.send_message(message.chat.id, "❌ فقط تصویر رسید را ارسال کن.")
        bot.register_next_step_handler(message, wallet_receipt, amount)
        return

    user_id = internal_user_id(message.from_user.id)
    file_id = message.photo[-1].file_id

    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method,
     receipt_file_id, receipt_type,
     status, created_at, updated_at)
    VALUES (?, NULL, ?, 'wallet', ?, 'photo',
            'pending', ?, ?)
    """, (
        user_id, amount, file_id, now(), now()
    ))

    payment = db_execute("""
    SELECT * FROM payments
    WHERE user_id=? AND method='wallet'
    ORDER BY id DESC LIMIT 1
    """, (user_id,), fetchone=True)

    notify_admin_payment(payment)

    bot.send_message(
        message.chat.id,
        "✅ رسید شارژ کیف پول ثبت شد.\n\n"
        "⏳ منتظر تأیید مدیریت باشید."
    )


@bot.callback_query_handler(func=lambda call: call.data == "wallet_history")
def wallet_history(call):
    user_id = internal_user_id(call.from_user.id)

    rows = db_execute("""
    SELECT * FROM transactions
    WHERE user_id=?
    ORDER BY id DESC
    LIMIT 20
    """, (user_id,), fetchall=True)

    if not rows:
        bot.send_message(call.message.chat.id, "📭 هنوز تراکنشی ثبت نشده.")
        return

    lines = ["📜 <b>تراکنش‌های کیف پول</b>\n"]

    for row in rows:
        sign = "+" if row["amount"] >= 0 else ""
        lines.append(
            f"• {sign}{row['amount']:,} تومان\n"
            f"  {row['description']}\n"
            f"  {row['created_at']}\n"
        )

    bot.send_message(call.message.chat.id, "\n".join(lines))


# ============================================================
# TRANSACTIONS PAGE (from main user menu)
# ============================================================

@bot.message_handler(func=lambda m: m.text == "📜 تراکنش‌های من")
def my_transactions(message):
    user_id = internal_user_id(message.from_user.id)

    rows = db_execute("""
    SELECT * FROM transactions
    WHERE user_id=?
    ORDER BY id DESC
    LIMIT 30
    """, (user_id,), fetchall=True)

    if not rows:
        bot.send_message(message.chat.id, "📭 تراکنشی ندارید.")
        return

    text = ["📜 <b>تراکنش‌های من</b>\n"]

    for row in rows:
        text.append(
            f"🧾 {row['description']}\n"
            f"💰 {row['amount']:,} تومان\n"
            f"📅 {row['created_at']}\n"
            f"🔖 {row['reference'] or '---'}\n"
        )

    bot.send_message(message.chat.id, "\n".join(text))
