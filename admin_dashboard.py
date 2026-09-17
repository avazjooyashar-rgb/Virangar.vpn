# ============================================================
# admin_dashboard.py
# ورود به پنل مدیریت، داشبورد آماری، جستجو و مسدودسازی کاربر
# ============================================================

from telebot import types

from config import bot
from database import db_execute, now
from models import get_user, is_admin, is_superadmin
from decorators import admin_only
from keyboards import admin_keyboard


@bot.message_handler(commands=["admin"])
def admin_command(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ دسترسی ندارید.")
        return

    bot.send_message(
        message.chat.id,
        "👑 <b>پنل مدیریت VirangarVPN</b>",
        reply_markup=admin_keyboard()
    )


@bot.message_handler(func=lambda m: m.text == "📊 داشبورد")
@admin_only
def admin_dashboard(message):
    users = db_execute("SELECT COUNT(*) c FROM users", fetchone=True)["c"]

    active_users = db_execute("""
    SELECT COUNT(DISTINCT user_id) c
    FROM services
    WHERE status='active'
    """, fetchone=True)["c"]

    services = db_execute(
        "SELECT COUNT(*) c FROM services WHERE status='active'",
        fetchone=True
    )["c"]

    revenue = db_execute("""
    SELECT COALESCE(SUM(amount),0) total
    FROM payments
    WHERE status='approved'
    """, fetchone=True)["total"]

    panels = db_execute(
        "SELECT COUNT(*) c FROM panels WHERE active=1",
        fetchone=True
    )["c"]

    bot.send_message(
        message.chat.id,
        "📊 <b>داشبورد</b>\n\n"
        f"👥 کاربران: {users}\n"
        f"🟢 کاربران فعال: {active_users}\n"
        f"📦 سرویس فعال: {services}\n"
        f"🖥 پنل فعال: {panels}\n"
        f"💰 درآمد: {revenue:,} تومان"
    )


# ============================================================
# USERS
# ============================================================

@bot.message_handler(func=lambda m: m.text == "👥 کاربران")
@admin_only
def admin_users(message):
    count = db_execute("SELECT COUNT(*) c FROM users", fetchone=True)["c"]

    bot.send_message(
        message.chat.id,
        f"👥 <b>مدیریت کاربران</b>\n\n"
        f"تعداد کاربران: {count}\n\n"
        "برای جستجو، Telegram ID کاربر را ارسال کنید."
    )

    bot.register_next_step_handler(message, admin_user_search)


def admin_user_search(message):
    try:
        tg_id = int(message.text.strip())
    except Exception:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر.")
        return

    user = get_user(tg_id)

    if not user:
        bot.send_message(message.chat.id, "❌ کاربر پیدا نشد.")
        return

    services = db_execute(
        "SELECT COUNT(*) c FROM services WHERE user_id=?",
        (user["id"],), fetchone=True
    )["c"]

    text = (
        "👤 <b>اطلاعات کاربر</b>\n\n"
        f"🆔 {user['telegram_id']}\n"
        f"👤 @{user['username'] or '---'}\n"
        f"💰 موجودی: {user['balance']:,}\n"
        f"📦 سرویس‌ها: {services}\n"
        f"🚫 مسدود: {'بله' if user['is_blocked'] else 'خیر'}"
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚫 مسدود/رفع مسدودی", callback_data=f"blockuser:{tg_id}"))

    bot.send_message(message.chat.id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("blockuser:"))
def block_user(call):
    if not is_superadmin(call.from_user.id):
        return

    tg_id = int(call.data.split(":")[1])
    user = get_user(tg_id)

    if not user:
        return

    new_status = 0 if user["is_blocked"] else 1

    db_execute("""
    UPDATE users
    SET is_blocked=?, updated_at=?
    WHERE telegram_id=?
    """, (new_status, now(), tg_id))

    bot.answer_callback_query(call.id, "انجام شد ✅")
