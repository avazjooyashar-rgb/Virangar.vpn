# ============================================================
# admin_plans.py
# مدیریت پلن‌های VPN توسط ادمین
# ============================================================

from telebot import types

from config import bot
from database import db_execute
from models import is_admin
from decorators import admin_only


@bot.message_handler(func=lambda m: m.text == "💎 پلن‌های VPN")
@admin_only
def admin_plans(message):
    plans = db_execute("SELECT * FROM plans ORDER BY sort_order, id", fetchall=True)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ افزودن پلن", callback_data="plan_admin_add"))

    for plan in plans:
        status = "🟢" if plan["active"] else "🔴"
        kb.add(
            types.InlineKeyboardButton(
                f"{status} {plan['name']}",
                callback_data=f"planadmin:{plan['id']}"
            )
        )

    bot.send_message(message.chat.id, "💎 <b>مدیریت پلن‌ها</b>", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("planadmin:"))
def plan_admin_details(call):
    if not is_admin(call.from_user.id):
        return

    plan_id = int(call.data.split(":")[1])
    plan = db_execute("SELECT * FROM plans WHERE id=?", (plan_id,), fetchone=True)

    if not plan:
        return

    text = (
        f"💎 <b>{plan['name']}</b>\n\n"
        f"💰 قیمت: {plan['price']:,}\n"
        f"📊 حجم: {plan['volume']} GB\n"
        f"⏳ مدت: {plan['duration']} روز\n"
        f"📱 دستگاه: {plan['devices']}\n"
        f"🤝 قیمت نماینده: {plan['reseller_price']:,}\n"
        f"📍 لوکیشن: {plan['location'] or '---'}\n"
        f"🖥 Panel ID: {plan['panel_id'] or '---'}"
    )

    bot.send_message(call.message.chat.id, text)
