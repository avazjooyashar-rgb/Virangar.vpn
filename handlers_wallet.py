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
import chat_clean as cc


@bot.message_handler(func=lambda m: m.text == "💰 کیف پول")
def wallet(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)  # اگه وسط یه مرحله‌ی قبلی (مثلاً شارژ) رها شده بود
    cc.drop(message)  # پیام دکمه‌ی منو پاک بشه
    render_wallet_menu(message.chat.id, message.from_user.id)


def render_wallet_menu(chat_id, from_user_id, message_id=None):
    user = get_user(from_user_id)
    balance = user["balance"] if user else 0

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💳 شارژ کیف پول", callback_data="wallet_topup"))
    kb.add(types.InlineKeyboardButton("📜 تاریخچه تراکنش", callback_data="wallet_history"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="wallet:back_main"))

    text = (
        f"💰 <b>کیف پول</b>\n\n"
        f"موجودی: <b>{balance:,} تومان</b>\n\n"
        "👇 از دکمه‌های زیر همین پیام استفاده کن:"
    )

    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
            return
        except Exception:
            pass
    cc.show(chat_id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data == "wallet:menu")
def wallet_menu_cb(call):
    bot.answer_callback_query(call.id)
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    render_wallet_menu(call.message.chat.id, call.from_user.id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "wallet:back_main")
def wallet_back_main(call):
    bot.answer_callback_query(call.id)
    cc.show(call.message.chat.id, "🏠 بازگشت به منوی اصلی", reply_markup=user_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == "wallet_topup")
def wallet_topup(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data="wallet:menu"))

    try:
        bot.edit_message_text(
            "💳 مبلغ شارژ را به تومان وارد کن:",
            chat_id, call.message.message_id, reply_markup=kb
        )
    except Exception:
        cc.show(chat_id, "💳 مبلغ شارژ را به تومان وارد کن:", reply_markup=kb)

    bot.register_next_step_handler_by_chat_id(chat_id, wallet_amount)


def wallet_amount(message):
    chat_id = message.chat.id
    cc.drop(message)  # عددی که کاربر تایپ کرده پاک بشه

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data="wallet:menu"))
    screen_id = cc.get_screen(chat_id)

    try:
        amount = int(message.text.replace(",", "").replace(" ", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        text = "❌ مبلغ نامعتبر است. دوباره وارد کن:"
        if screen_id:
            try:
                bot.edit_message_text(text, chat_id, screen_id, reply_markup=kb)
            except Exception:
                cc.show(chat_id, text, reply_markup=kb)
        else:
            cc.show(chat_id, text, reply_markup=kb)
        bot.register_next_step_handler_by_chat_id(chat_id, wallet_amount)
        return

    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")

    if not card:
        text = "❌ پرداخت کارت به کارت تنظیم نشده."
        if screen_id:
            try:
                bot.edit_message_text(text, chat_id, screen_id, reply_markup=kb)
            except Exception:
                cc.show(chat_id, text, reply_markup=kb)
        else:
            cc.show(chat_id, text, reply_markup=kb)
        return

    text = (
        f"💳 مبلغ <b>{amount:,} تومان</b> را به کارت زیر انتقال بده:\n\n"
        f"<code>{card}</code>\n"
        f"👤 {holder}\n\n"
        "سپس تصویر رسید را ارسال کن."
    )
    if screen_id:
        try:
            bot.edit_message_text(text, chat_id, screen_id, reply_markup=kb)
        except Exception:
            cc.show(chat_id, text, reply_markup=kb)
    else:
        cc.show(chat_id, text, reply_markup=kb)

    bot.register_next_step_handler_by_chat_id(chat_id, wallet_receipt, amount)


def wallet_receipt(message, amount):
    chat_id = message.chat.id
    cc.drop(message)  # عکس/پیام کاربر پاک بشه

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data="wallet:menu"))
    screen_id = cc.get_screen(chat_id)

    if not message.photo:
        text = "❌ فقط تصویر رسید را ارسال کن."
        if screen_id:
            try:
                bot.edit_message_text(text, chat_id, screen_id, reply_markup=kb)
            except Exception:
                cc.show(chat_id, text, reply_markup=kb)
        else:
            cc.show(chat_id, text, reply_markup=kb)
        bot.register_next_step_handler_by_chat_id(chat_id, wallet_receipt, amount)
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

    text = (
        "✅ رسید شارژ کیف پول ثبت شد.\n\n"
        "⏳ منتظر تأیید مدیریت باشید."
    )
    ok_kb = types.InlineKeyboardMarkup()
    ok_kb.add(types.InlineKeyboardButton("🔙 بازگشت به کیف پول", callback_data="wallet:menu"))

    if screen_id:
        try:
            bot.edit_message_text(text, chat_id, screen_id, reply_markup=ok_kb)
            return
        except Exception:
            pass
    cc.show(chat_id, text, reply_markup=ok_kb)


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

    bot.answer_callback_query(call.id)

    if not entries:
        text = "📭 هنوز تراکنشی ثبت نشده."
    else:
        text = "\n".join(["📜 <b>تراکنش‌های کیف پول</b>\n"] + [e["text"] for e in entries])

    # همون پیام منوی کیف پول جای خودش این لیست رو نشون می‌ده
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        cc.show(call.message.chat.id, text, reply_markup=kb)


# ============================================================
# TRANSACTIONS PAGE (from main user menu)
# ============================================================

@bot.message_handler(func=lambda m: m.text == "📜 تراکنش‌های من")
def my_transactions(message):
    cc.drop(message)  # پیام دکمه‌ی منو پاک بشه
    user_id = internal_user_id(message.from_user.id)
    entries = _build_transaction_entries(user_id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="wallet:back_main"))

    if not entries:
        cc.show(message.chat.id, "📭 تراکنشی ندارید.", reply_markup=kb)
        return

    text = "\n".join(["📜 <b>تراکنش‌های من</b>\n"] + [e["text"] for e in entries])
    cc.show(message.chat.id, text, reply_markup=kb)
