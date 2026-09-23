# ============================================================
# handlers_wallet.py
# کیف پول: نمایش موجودی، شارژ، تاریخچه تراکنش
# ============================================================

from telebot import types

from config import bot
from database import db_execute, get_setting, now
from models import get_user, internal_user_id
from handlers_payment import notify_admin_payment
from keyboards import user_keyboard


@bot.message_handler(func=lambda m: m.text == "💰 کیف پول")
def wallet(message):
    render_wallet_menu(message.chat.id, message.from_user.id)


def render_wallet_menu(chat_id, from_user_id, message_id=None):
    user = get_user(from_user_id)
    balance = user["balance"] if user else 0

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💳 شارژ کیف پول", callback_data="wallet_topup"))
    kb.add(types.InlineKeyboardButton("📜 تاریخچه تراکنش", callback_data="wallet_history"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="wallet:back_main"))

    text = f"💰 <b>کیف پول</b>\n\nموجودی: <b>{balance:,} تومان</b>"

    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data == "wallet:menu")
def wallet_menu_cb(call):
    bot.answer_callback_query(call.id)
    render_wallet_menu(call.message.chat.id, call.from_user.id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "wallet:back_main")
def wallet_back_main(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(call.message.chat.id, "🏠 بازگشت به منوی اصلی", reply_markup=user_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == "wallet_topup")
def wallet_topup(call):
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data="wallet:menu"))
    sent = bot.send_message(call.message.chat.id, "💳 مبلغ شارژ را به تومان وارد کن:", reply_markup=kb)
    bot.register_next_step_handler(sent, wallet_amount)


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


def _build_transaction_entries(user_id):
    """
    ادغام دو منبع:
    1) خریدهای کارت‌به‌کارت تأییدشده (جدول payments، method='manual')
       که هیچ‌وقت تو transactions ثبت نمی‌شن.
    2) تراکنش‌های کیف‌پول (شارژ، خرید با موجودی و ...) از جدول transactions.
    بدون تکراری‌شدن، مرتب‌شده بر اساس تاریخ نزولی.
    """
    manual_purchases = db_execute("""
    SELECT payments.*, plans.name AS plan_name
    FROM payments
    LEFT JOIN plans ON plans.id = payments.plan_id
    WHERE payments.user_id=? AND payments.status='approved' AND payments.method='manual'
    ORDER BY payments.updated_at DESC
    LIMIT 30
    """, (user_id,), fetchall=True) or []

    wallet_rows = db_execute("""
    SELECT * FROM transactions
    WHERE user_id=?
    ORDER BY created_at DESC
    LIMIT 30
    """, (user_id,), fetchall=True) or []

    entries = []

    for row in manual_purchases:
        date = row["updated_at"] or row["created_at"] or ""
        entries.append({
            "date": date,
            "text": (
                f"🧾 خرید پلن {row['plan_name'] or '---'} (کارت به کارت)\n"
                f"💰 -{row['amount']:,} تومان\n"
                f"📅 {date}\n"
                f"🔖 payment:{row['id']}\n"
            )
        })

    for row in wallet_rows:
        entries.append({
            "date": row["created_at"] or "",
            "text": (
                f"🧾 {row['description']}\n"
                f"💰 {row['amount']:,} تومان\n"
                f"📅 {row['created_at']}\n"
                f"🔖 {row['reference'] or '---'}\n"
            )
        })

    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[:30]


@bot.callback_query_handler(func=lambda call: call.data == "wallet_history")
def wallet_history(call):
    user_id = internal_user_id(call.from_user.id)
    entries = _build_transaction_entries(user_id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به کیف پول", callback_data="wallet:menu"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="wallet:back_main"))

    if not entries:
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "📭 هنوز تراکنشی ثبت نشده.", reply_markup=kb)
        return

    bot.answer_callback_query(call.id)
    lines = ["📜 <b>تراکنش‌های کیف پول</b>\n"] + [e["text"] for e in entries]
    bot.send_message(call.message.chat.id, "\n".join(lines), reply_markup=kb)


# ============================================================
# TRANSACTIONS PAGE (from main user menu)
# ============================================================

@bot.message_handler(func=lambda m: m.text == "📜 تراکنش‌های من")
def my_transactions(message):
    user_id = internal_user_id(message.from_user.id)
    entries = _build_transaction_entries(user_id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="wallet:back_main"))

    if not entries:
        bot.send_message(message.chat.id, "📭 تراکنشی ندارید.", reply_markup=kb)
        return

    text = ["📜 <b>تراکنش‌های من</b>\n"] + [e["text"] for e in entries]
    bot.send_message(message.chat.id, "\n".join(text), reply_markup=kb)
