# ============================================================
# handlers_shop.py
# نمایش پنل‌ها، پلن‌های هر پنل، جزئیات پلن و سرویس‌های کاربر
# ============================================================
import re
from telebot import types
from config import bot
from database import db_execute, get_setting
from models import internal_user_id, get_user
from force_join import force_join_ok
from keyboards import force_join_markup

USERNAME_PREFIX = "virangarvpn."

# ============================================================
# STEP 1: PANEL LIST
# ============================================================

def active_panels_with_plans():
    return db_execute("""
    SELECT DISTINCT panels.*
    FROM panels
    JOIN plans ON plans.panel_id = panels.id
    WHERE panels.active=1 AND plans.active=1
    ORDER BY panels.id
    """, fetchall=True)


def panels_keyboard():
    panels = active_panels_with_plans()
    kb = types.InlineKeyboardMarkup()
    for panel in panels:
        kb.add(
            types.InlineKeyboardButton(
                f"🖥 {panel['name']}",
                callback_data=f"buypanel:{panel['id']}"
            )
        )
    return kb, panels


@bot.message_handler(func=lambda m: m.text == "🛒 خرید VPN")
def buy_vpn(message):
    if not force_join_ok(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "🔒 ابتدا عضو کانال شوید.",
            reply_markup=force_join_markup()
        )
        return
    show_panels(message.chat.id)


def show_panels(chat_id):
    kb, panels = panels_keyboard()
    if not panels:
        bot.send_message(chat_id, "❌ در حال حاضر هیچ پنل فعالی با پلن موجود نیست.")
        return
    bot.send_message(
        chat_id,
        "🖥 <b>انتخاب پنل</b>\n\n"
        "لطفاً یکی از پنل‌های زیر را انتخاب کنید:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data == "buy_back_home")
def buy_back_home(call):
    bot.answer_callback_query(call.id)
    show_panels(call.message.chat.id)


# ============================================================
# STEP 2: PLAN LIST (per panel)
# ============================================================

def plans_keyboard(panel_id):
    plans = db_execute("""
    SELECT * FROM plans
    WHERE active=1 AND panel_id=?
    ORDER BY sort_order, id
    """, (panel_id,), fetchall=True)
    kb = types.InlineKeyboardMarkup()
    for plan in plans:
        kb.add(
            types.InlineKeyboardButton(
                f"💎 {plan['name']} | {plan['price']:,} تومان",
                callback_data=f"buyplan:{plan['id']}"
            )
        )
    kb.add(
        types.InlineKeyboardButton("🔙 بازگشت", callback_data="buy_back_home")
    )
    return kb, plans


@bot.callback_query_handler(func=lambda call: call.data.startswith("buypanel:"))
def select_panel(call):
    panel_id = int(call.data.split(":")[1])
    panel = db_execute(
        "SELECT * FROM panels WHERE id=? AND active=1",
        (panel_id,),
        fetchone=True
    )
    if not panel:
        bot.answer_callback_query(call.id, "این پنل دیگر فعال نیست.", show_alert=True)
        return

    kb, plans = plans_keyboard(panel_id)
    bot.answer_callback_query(call.id)

    if not plans:
        bot.edit_message_text(
            f"🖥 <b>{panel['name']}</b>\n\n"
            "❌ برای این پنل هنوز پلنی تعریف نشده.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    bot.edit_message_text(
        f"🖥 پنل: <b>{panel['name']}</b>\n\n"
        "💎 یکی از پلن‌های زیر را انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# STEP 3: PLAN DETAILS -> ASK CUSTOM NAME
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("buyplan:"))
def select_plan(call):
    plan_id = int(call.data.split(":")[1])
    plan = db_execute(
        "SELECT * FROM plans WHERE id=? AND active=1",
        (plan_id,),
        fetchone=True
    )
    if not plan:
        bot.answer_callback_query(call.id, "پلن پیدا نشد", show_alert=True)
        return

    panel_id = plan["panel_id"]
    text = (
        "💎 <b>جزئیات پلن</b>\n\n"
        f"📦 نام: {plan['name']}\n"
        f"📊 حجم: {plan['volume']} GB\n"
        f"⏳ مدت: {plan['duration']} روز\n"
        f"📱 دستگاه: {plan['devices']}\n"
        f"💰 قیمت: {plan['price']:,} تومان\n\n"
        "🏷 یک نام دلخواه (فقط حروف انگلیسی کوچک و عدد) برای سرویس خود ارسال کنید:\n\n"
        f"نام نهایی به‌صورت <code>{USERNAME_PREFIX}nameshoma</code> ساخته می‌شود.\n"
        "مثال: <code>ali</code>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"buypanel:{panel_id}"))

    bot.answer_callback_query(call.id)
    sent = bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    bot.register_next_step_handler(sent, receive_username, plan_id)


def receive_username(message, plan_id):
    raw = (message.text or "").strip().lower()

    if not re.fullmatch(r"[a-z0-9_]{2,20}", raw):
        sent = bot.send_message(
            message.chat.id,
            "❌ نام نامعتبر است.\n\n"
            "فقط از حروف انگلیسی کوچک، عدد و _ استفاده کنید (۲ تا ۲۰ کاراکتر).\n\n"
            "دوباره ارسال کنید:"
        )
        bot.register_next_step_handler(sent, receive_username, plan_id)
        return

    plan = db_execute(
        "SELECT * FROM plans WHERE id=? AND active=1",
        (plan_id,),
        fetchone=T
