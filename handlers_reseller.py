# ============================================================
# handlers_reseller.py
# پنل نمایندگی از دید کاربر (خرید پنل، مشاهده پلن‌ها)
# ============================================================

from telebot import types

from config import bot
from database import db_execute
import chat_clean as cc


def _reseller_menu_markup():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🛒 خرید پنل نمایندگی", callback_data="reseller_buy"))
    kb.add(types.InlineKeyboardButton("🖥 پنل‌های من", callback_data="reseller_panels"))
    kb.add(types.InlineKeyboardButton("👥 کاربران من", callback_data="reseller_users"))
    kb.add(types.InlineKeyboardButton("📈 آمار فروش", callback_data="reseller_stats"))
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))
    return kb


@bot.message_handler(func=lambda m: m.text == "🤝 پنل نمایندگی")
def reseller_menu(message):
    cc.drop(message)  # پیام دکمه‌ی منو پاک بشه
    cc.show(
        message.chat.id,
        "🤝 <b>پنل نمایندگی</b>\n\n"
        "از این قسمت می‌توانید نمایندگی خود را مدیریت کنید.",
        reply_markup=_reseller_menu_markup()
    )


@bot.callback_query_handler(func=lambda call: call.data == "reseller_back")
def reseller_back(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "🤝 <b>پنل نمایندگی</b>\n\n"
        "از این قسمت می‌توانید نمایندگی خود را مدیریت کنید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=_reseller_menu_markup(),
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data == "reseller_buy")
def reseller_buy(call):
    plans = db_execute("""
    SELECT * FROM reseller_plans
    WHERE active=1
    ORDER BY id
    """, fetchall=True)

    kb = types.InlineKeyboardMarkup()

    bot.answer_callback_query(call.id)

    if not plans:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="reseller_back"))
        bot.edit_message_text(
            "📭 پلن نمایندگی موجود نیست.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb
        )
        return

    for plan in plans:
        kb.add(
            types.InlineKeyboardButton(
                f"🤝 {plan['name']} | {plan['price']:,}",
                callback_data=f"rplan:{plan['id']}"
            )
        )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="reseller_back"))

    bot.edit_message_text(
        "🤝 پلن نمایندگی را انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("rplan:"))
def reseller_plan(call):
    plan_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT * FROM reseller_plans WHERE id=? AND active=1",
        (plan_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(call.id, "این پلن دیگر موجود نیست.", show_alert=True)
        return

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="reseller_buy"))

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"🤝 <b>{plan['name']}</b>\n\n"
        f"💰 قیمت: {plan['price']:,} تومان\n"
        f"👥 ظرفیت: {plan['capacity']}\n"
        f"⏳ مدت: {plan['duration']} روز\n\n"
        "خرید پنل نمایندگی در مرحله پرداخت انجام می‌شود.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )
