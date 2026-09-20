# ============================================================
# admin_tickets.py
# مشاهده لیست تیکت‌ها توسط ادمین
# ============================================================

from config import bot
from database import db_execute
from decorators import admin_only


@bot.message_handler(func=lambda m: m.text == "🎫 مدیریت تیکت‌ها")
@admin_only
def admin_tickets(message):
    tickets = db_execute("""
    SELECT tickets.*, users.telegram_id
    FROM tickets
    JOIN users ON users.id=tickets.user_id
    ORDER BY tickets.id DESC
    LIMIT 30
    """, fetchall=True)

    if not tickets:
        bot.send_message(message.chat.id, "📭 تیکتی وجود ندارد.")
        return

    lines = ["🎫 <b>آخرین تیکت‌ها</b>\n"]

    for ticket in tickets:
        lines.append(
            f"#{ticket['id']} | "
            f"{ticket['status']} | "
            f"{ticket['telegram_id']}\n"
            f"{ticket['subject']}\n"
        )

    bot.send_message(message.chat.id, "\n".join(lines))
