# ============================================================
# handlers_reseller.py
# پنل نمایندگی از دید کاربر (خرید پنل، مشاهده پلن‌ها)
# ============================================================

from telebot import types

from config import bot
from database import db_execute


@bot.message_handler(func=lambda m: m.text == "🤝 پنل نمایندگی")
def reseller_menu(message):
    kb = types.InlineKeyboardMarkup()

    kb.add(types.InlineKeyboardButton("🛒 خرید پنل نمایندگی", callback_data="reseller_buy"))
    kb.add(types.InlineKeyboardButton("🖥 پنل‌های من", callback_data="reseller_panels"))
    kb.add(types.InlineKeyboardButton("👥 کاربران من", callback_data="reseller_users"))
    kb.add(types.InlineKeyboardButton("📈 آمار فروش", callback_data="reseller_stats"))

    bot.send_message(
        message.chat.id,
        "🤝 <b>پنل نمایندگی</b>\n\n"
        "از این قسمت می‌توانید نمایندگی خود را مدیریت کنید.",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda call: call.data == "reseller_buy")
def reseller_buy(call):
    plans = db_execute("""
    SELECT * FROM reseller_plans
    WHERE active=1
    ORDER BY id
    """, fetchall=True)

    if not plans:
        bot.send_message(call.message.chat.id, "📭 پلن نمایندگی موجود نیست.")
        return

    kb = types.InlineKeyboardMarkup()

    for plan in plans:
        kb.add(
            types.InlineKeyboardButton(
                f"🤝 {plan['name']} | {plan['price']:,}",
                callback_data=f"rplan:{plan['id']}"
            )
        )

    bot.send_message(call.message.chat.id, "🤝 پلن نمایندگی را انتخاب کنید:", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("rplan:"))
def reseller_plan(call):
    plan_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT * FROM reseller_plans WHERE id=? AND active=1",
        (plan_id,),
        fetchone=True
    )

    if not plan:
        return

    bot.send_message(
        call.message.chat.id,
        f"🤝 <b>{plan['name']}</b>\n\n"
        f"💰 قیمت: {plan['price']:,} تومان\n"
        f"👥 ظرفیت: {plan['capacity']}\n"
        f"⏳ مدت: {plan['duration']} روز\n\n"
        "خرید پنل نمایندگی در مرحله پرداخت انجام می‌شود."
    )
