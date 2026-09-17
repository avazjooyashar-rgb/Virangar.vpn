# ============================================================
# handlers_support.py
# پشتیبانی و تیکت‌های کاربر
# ============================================================

from telebot import types

from config import bot, SUPER_ADMIN_ID
from database import db_execute, get_setting, now
from models import internal_user_id


@bot.message_handler(func=lambda m: m.text == "🆘 پشتیبانی")
def support(message):
    kb = types.InlineKeyboardMarkup()

    kb.add(types.InlineKeyboardButton("🎫 تیکت جدید", callback_data="ticket_new"))
    kb.add(types.InlineKeyboardButton("📂 تیکت‌های من", callback_data="ticket_list"))

    support_username = get_setting("support_username", "").strip()

    if support_username:
        username = support_username[1:] if support_username.startswith("@") else support_username

        kb.add(
            types.InlineKeyboardButton(
                "👨‍💻 ارتباط مستقیم",
                url=f"https://t.me/{username}"
            )
        )

    bot.send_message(
        message.chat.id,
        "🆘 <b>مرکز پشتیبانی</b>\n\n"
        "برای ارتباط با پشتیبانی تیکت ایجاد کنید.",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda call: call.data == "ticket_new")
def ticket_new(call):
    bot.send_message(call.message.chat.id, "🎫 موضوع یا متن مشکل خود را ارسال کنید:")
    bot.register_next_step_handler(call.message, create_ticket)


def create_ticket(message):
    user_id = internal_user_id(message.from_user.id)

    db_execute("""
    INSERT INTO tickets
    (user_id, subject, status, created_at, updated_at)
    VALUES (?, ?, 'open', ?, ?)
    """, (
        user_id, message.text or "بدون موضوع", now(), now()
    ))

    ticket = db_execute("""
    SELECT * FROM tickets
    WHERE user_id=?
    ORDER BY id DESC LIMIT 1
    """, (user_id,), fetchone=True)

    db_execute("""
    INSERT INTO ticket_messages
    (ticket_id, sender_id, message, created_at)
    VALUES (?, ?, ?, ?)
    """, (
        ticket["id"], message.from_user.id, message.text or "", now()
    ))

    bot.send_message(
        message.chat.id,
        f"✅ تیکت <b>#{ticket['id']}</b> ایجاد شد.\n\n"
        "پشتیبانی به‌زودی پاسخ می‌دهد."
    )

    if SUPER_ADMIN_ID:
        bot.send_message(
            SUPER_ADMIN_ID,
            f"🎫 <b>تیکت جدید #{ticket['id']}</b>\n\n"
            f"👤 Telegram ID: {message.from_user.id}\n"
            f"📝 {message.text}"
        )


@bot.callback_query_handler(func=lambda call: call.data == "ticket_list")
def ticket_list(call):
    user_id = internal_user_id(call.from_user.id)

    tickets = db_execute("""
    SELECT * FROM tickets
    WHERE user_id=?
    ORDER BY id DESC
    LIMIT 20
    """, (user_id,), fetchall=True)

    if not tickets:
        bot.send_message(call.message.chat.id, "📭 تیکتی ندارید.")
        return

    text = ["🎫 <b>تیکت‌های من</b>\n"]

    for ticket in tickets:
        text.append(f"#{ticket['id']} — {ticket['subject']}\n📌 {ticket['status']}\n")

    bot.send_message(call.message.chat.id, "\n".join(text))
