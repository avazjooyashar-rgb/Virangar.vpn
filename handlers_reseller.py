# ============================================================
# handlers_reseller.py  [نسخه: می‌پرسه حجم/مدت/دستگاه — اگه این خط رو
# تو فایل سرورت نمی‌بینی یعنی فایل قدیمی هنوز جایگزین نشده]
# پنل نمایندگی از دید کاربر:
#   - خرید حجم نمایندگی (کارت به کارت، نیاز به تأیید ادمین)
#   - پنل‌های من = استخرهای حجمی که در هر پنل داره
#   - ساخت سرویس نامحدود برای مشتری (فقط از استخر کم می‌شود، قطره‌ای)
#   - کاربران من = لیست سرویس‌هایی که برای مشتری‌هاش ساخته
#
# نکته‌ی مهم طراحی: «مشتریِ نماینده» یک کاربر تلگرامی جدا نیست.
# سرویس مستقیم زیر حساب خودِ نماینده ثبت می‌شود (user_id = خودِ
# نماینده) و فقط یک نام دلخواه روی آن است؛ نماینده خودش لینک
# اشتراک را دستی به مشتری‌اش می‌دهد.
# ============================================================

import re
from datetime import datetime, timedelta

from telebot import types

from config import bot
from database import db_execute, get_setting, now
from models import get_user, internal_user_id
from pasarguard_api import (
    pasarguard_create_unlimited_service,
    pasarguard_create_service,
    pasarguard_set_status,
    pasarguard_delete_service,
)
import chat_clean as cc
import reseller_billing

# فلوی چندمرحله‌ایِ «ساخت سرویس برای مشتری» (حجم/زمان/تعداد کاربر)
_draft = {}  # chat_id -> dict

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{2,20}$")


# ============================================================
# HELPERS
# ============================================================

def render(chat_id, text, kb, message_id=None):
    """پیام مرحله رو ادیت می‌کنه (اگه message_id بدیم) وگرنه با cc.show می‌فرسته."""
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="HTML")
            return message_id
        except Exception:
            pass
    sent = cc.show(chat_id, text, reply_markup=kb, parse_mode="HTML")
    return sent.message_id if sent else None


def _home_markup():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))
    return kb


def _get_pool(pool_id, owner_user_id):
    """
    عمداً اسم واقعیِ پنل (که فقط سوپرادمین می‌بینه) اینجا برنمی‌گرده؛
    به‌جاش اسمِ پلن نمایندگی (همونی که خود نماینده موقع خرید دیده)
    به‌عنوان برچسب استخر نشون داده میشه.
    """
    return db_execute("""
    SELECT reseller_panels.*, reseller_plans.name AS pool_label
    FROM reseller_panels
    LEFT JOIN reseller_plans ON reseller_plans.id = reseller_panels.reseller_plan_id
    WHERE reseller_panels.id=? AND reseller_panels.user_id=?
    """, (pool_id, owner_user_id), fetchone=True)


def _pool_label(pool):
    return pool["pool_label"] or f"استخر #{pool['id']}"


def _progress_bar(used, total, length=10):
    total = total or 0
    if total <= 0:
        pct = 0
    else:
        pct = min(1, max(0, used) / total)
    filled = int(pct * length)
    return "🟩" * filled + "⬜️" * (length - filled) + f"  {int(pct * 100)}٪"


def _fmt_gb(value):
    value = float(value or 0)
    if value == int(value):
        return f"{int(value)}"
    return f"{value:.2f}"


# ============================================================
# MAIN MENU
# ============================================================

def _reseller_menu_markup():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🛒 خرید حجم نمایندگی", callback_data="res_buy"))
    kb.add(types.InlineKeyboardButton("🖥 پنل‌های من", callback_data="res_pools"))
    kb.add(types.InlineKeyboardButton("👥 کاربران من", callback_data="res_customers"))
    kb.add(types.InlineKeyboardButton("📈 آمار فروش", callback_data="res_stats"))
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))
    return kb


@bot.message_handler(func=lambda m: m.text == "🤝 پنل نمایندگی")
def reseller_menu(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    cc.drop(message)
    cc.show(
        message.chat.id,
        "🤝 <b>پنل نمایندگی</b>\n\n"
        "از این قسمت می‌تونی حجم نمایندگی بخری، برای مشتری‌هات سرویس بسازی و وضعیت استخرهات رو ببینی.",
        reply_markup=_reseller_menu_markup(),
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data == "res_menu")
def res_menu_cb(call):
    bot.answer_callback_query(call.id)
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    render(
        call.message.chat.id,
        "🤝 <b>پنل نمایندگی</b>\n\n"
        "از این قسمت می‌تونی حجم نمایندگی بخری، برای مشتری‌هات سرویس بسازی و وضعیت استخرهات رو ببینی.",
        _reseller_menu_markup(),
        call.message.message_id
    )


# ============================================================
# BUY RESELLER VOLUME
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "res_buy")
def res_buy(call):
    bot.answer_callback_query(call.id)

    plans = db_execute("""
    SELECT reseller_plans.*, panels.name AS panel_name
    FROM reseller_plans
    LEFT JOIN panels ON panels.id = reseller_plans.panel_id
    WHERE reseller_plans.active=1
    ORDER BY reseller_plans.id
    """, fetchall=True) or []

    kb = types.InlineKeyboardMarkup()

    if not plans:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))
        render(call.message.chat.id, "📭 فعلاً پلن نمایندگی‌ای تعریف نشده.", kb, call.message.message_id)
        return

    for plan in plans:
        kb.add(types.InlineKeyboardButton(
            f"🤝 {plan['name']} | {_fmt_gb(plan['volume_gb'])}GB | {plan['price']:,} تومان",
            callback_data=f"resplan:{plan['id']}"
        ))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))

    render(call.message.chat.id, "🤝 <b>خرید حجم نمایندگی</b>\n\nیه پلن انتخاب کن:", kb, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("resplan:"))
def resplan_detail(call):
    plan_id = int(call.data.split(":")[1])
    plan = db_execute("""
    SELECT reseller_plans.*, panels.name AS panel_name
    FROM reseller_plans
    LEFT JOIN panels ON panels.id = reseller_plans.panel_id
    WHERE reseller_plans.id=? AND reseller_plans.active=1
    """, (plan_id,), fetchone=True)

    if not plan:
        bot.answer_callback_query(call.id, "این پلن دیگر موجود نیست.", show_alert=True)
        return

    bot.answer_callback_query(call.id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💳 پرداخت کارت به کارت", callback_data=f"respay:{plan_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_buy"))

    render(
        call.message.chat.id,
        f"🤝 <b>{plan['name']}</b>\n\n"
        f"📊 حجم: {_fmt_gb(plan['volume_gb'])} گیگ\n"
        f"💰 قیمت: {plan['price']:,} تومان\n\n"
        "⏳ بدون محدودیت زمانی — تا هر وقت حجمش تموم نشه می‌تونی ازش بفروشی.\n\n"
        "با خرید بیشتر از همین پلن، حجمش به استخر قبلیت اضافه میشه (جمع میشه).",
        kb,
        call.message.message_id
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("respay:"))
def respay_start(call):
    plan_id = int(call.data.split(":")[1])
    plan = db_execute("SELECT * FROM reseller_plans WHERE id=? AND active=1", (plan_id,), fetchone=True)

    if not plan:
        bot.answer_callback_query(call.id, "این پلن دیگر موجود نیست.", show_alert=True)
        return

    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")

    if not card:
        bot.answer_callback_query(call.id, "پرداخت کارت به کارت فعلاً تنظیم نشده.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 انصراف", callback_data=f"resplan:{plan_id}"))

    render(
        chat_id,
        f"💳 مبلغ <b>{plan['price']:,} تومان</b> رو به کارت زیر انتقال بده:\n\n"
        f"<code>{card}</code>\n"
        f"👤 {holder or '---'}\n\n"
        "بعد از انتقال، تصویر رسید رو همینجا بفرست.",
        kb,
        call.message.message_id
    )
    bot.register_next_step_handler_by_chat_id(chat_id, respay_receipt, plan_id)


def respay_receipt(message, plan_id):
    chat_id = message.chat.id
    cc.drop(message)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 انصراف", callback_data=f"resplan:{plan_id}"))
    screen_id = cc.get_screen(chat_id)

    if not message.photo:
        text = "❌ فقط تصویر رسید رو بفرست."
        if screen_id:
            try:
                bot.edit_message_text(text, chat_id, screen_id, reply_markup=kb)
            except Exception:
                cc.show(chat_id, text, reply_markup=kb)
        else:
            cc.show(chat_id, text, reply_markup=kb)
        bot.register_next_step_handler_by_chat_id(chat_id, respay_receipt, plan_id)
        return

    plan = db_execute("SELECT * FROM reseller_plans WHERE id=?", (plan_id,), fetchone=True)
    if not plan:
        cc.show(chat_id, "❌ این پلن دیگر موجود نیست.", reply_markup=_home_markup())
        return

    user_id = internal_user_id(message.from_user.id)
    file_id = message.photo[-1].file_id

    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method,
     receipt_file_id, receipt_type,
     type, reseller_plan_id,
     status, created_at, updated_at)
    VALUES (?, NULL, ?, 'manual', ?, 'photo',
            'reseller', ?, 'pending', ?, ?)
    """, (
        user_id, plan["price"], file_id, plan_id, now(), now()
    ))

    ok_kb = types.InlineKeyboardMarkup()
    ok_kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل نمایندگی", callback_data="res_menu"))

    text = "✅ رسید ثبت شد.\n\n⏳ بعد از تأیید مدیریت، حجم به استخرت اضافه میشه."
    if screen_id:
        try:
            bot.edit_message_text(text, chat_id, screen_id, reply_markup=ok_kb)
            return
        except Exception:
            pass
    cc.show(chat_id, text, reply_markup=ok_kb)


# ============================================================
# تأیید پرداخت (صدا زده میشه از handlers_payment.py بعد از approve)
# ============================================================

def apply_reseller_topup(payment):
    """
    بعد از تأیید ادمین: حجمِ پلنِ خریداری‌شده به استخر نماینده تو
    همون پنل اضافه میشه (اگه استخری نباشه، ساخته میشه).
    """
    reseller_plan_id = payment["reseller_plan_id"] if "reseller_plan_id" in payment.keys() else None
    if not reseller_plan_id:
        return False, "پلن نمایندگی نامعتبر است"

    rplan = db_execute("SELECT * FROM reseller_plans WHERE id=?", (reseller_plan_id,), fetchone=True)
    if not rplan:
        return False, "پلن نمایندگی پیدا نشد"

    panel_id = rplan["panel_id"]
    if not panel_id:
        return False, "این پلن نمایندگی به هیچ پنلی وصل نیست"

    volume = rplan["volume_gb"] or 0
    user_id = payment["user_id"]

    pool = db_execute(
        "SELECT * FROM reseller_panels WHERE user_id=? AND panel_id=?",
        (user_id, panel_id), fetchone=True
    )

    if pool:
        new_balance = (pool["balance"] or 0) + volume
        new_total = (pool["total_purchased"] or 0) + volume
        db_execute("""
        UPDATE reseller_panels
        SET balance=?, total_purchased=?, active=1, updated_at=?
        WHERE id=?
        """, (new_balance, new_total, now(), pool["id"]))
    else:
        db_execute("""
        INSERT INTO reseller_panels
        (user_id, reseller_plan_id, panel_id, name, balance, total_purchased, active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (user_id, reseller_plan_id, panel_id, rplan["name"], volume, volume, now(), now()))

    db_execute("UPDATE users SET is_reseller=1 WHERE id=?", (user_id,))

    user = db_execute("SELECT * FROM users WHERE id=?", (user_id,), fetchone=True)
    if user:
        try:
            bot.send_message(
                user["telegram_id"],
                "✅ <b>خرید حجم نمایندگی تأیید شد!</b>\n\n"
                f"➕ {_fmt_gb(volume)} گیگ به استخر «{rplan['name']}» اضافه شد.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    return True, "ok"


# ============================================================
# MY POOLS
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "res_pools")
def res_pools(call):
    bot.answer_callback_query(call.id)
    user_id = internal_user_id(call.from_user.id)

    pools = db_execute("""
    SELECT reseller_panels.*, reseller_plans.name AS pool_label
    FROM reseller_panels
    LEFT JOIN reseller_plans ON reseller_plans.id = reseller_panels.reseller_plan_id
    WHERE reseller_panels.user_id=?
    ORDER BY reseller_panels.id DESC
    """, (user_id,), fetchall=True) or []

    kb = types.InlineKeyboardMarkup()

    if not pools:
        kb.add(types.InlineKeyboardButton("🛒 خرید حجم نمایندگی", callback_data="res_buy"))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))
        render(call.message.chat.id, "📭 هنوز هیچ استخر حجمی نداری.", kb, call.message.message_id)
        return

    for pool in pools:
        icon = "🟢" if pool["active"] and (pool["balance"] or 0) > 0 else "🔴"
        kb.add(types.InlineKeyboardButton(
            f"{icon} {_pool_label(pool)}",
            callback_data=f"respool:{pool['id']}"
        ))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))

    render(call.message.chat.id, "🖥 <b>پنل‌های من</b>\n\nروی هرکدوم بزن:", kb, call.message.message_id)


def _pool_customer_stats(pool):
    row = db_execute("""
    SELECT COUNT(*) AS total, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active
    FROM services
    WHERE reseller_id=? AND panel_id=?
    """, (pool["user_id"], pool["panel_id"]), fetchone=True)
    total = row["total"] or 0
    active = row["active"] or 0
    return active, total


def _render_pool_detail(chat_id, pool_id, message_id=None):
    pool = db_execute("SELECT * FROM reseller_panels WHERE id=?", (pool_id,), fetchone=True)

    if not pool:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_pools"))
        render(chat_id, "❌ این استخر دیگه وجود نداره.", kb, message_id)
        return

    active_customers, total_customers = _pool_customer_stats(pool)

    balance = pool["balance"] or 0
    total_purchased = pool["total_purchased"] or 0
    used = max(0, total_purchased - balance)

    status_line = "🟢 فعال" if pool["active"] and balance > 0 else "🔴 تموم‌شده / غیرفعال"

    kb = types.InlineKeyboardMarkup()
    if balance > 0:
        kb.add(types.InlineKeyboardButton("➕ ساخت سرویس برای مشتری", callback_data=f"resnew:{pool_id}"))
    kb.row(
        types.InlineKeyboardButton("👥 مشتری‌های این پنل", callback_data=f"respoolcust:{pool_id}"),
        types.InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"respoolrefresh:{pool_id}"),
    )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_pools"))

    text = (
        f"🖥 <b>{_pool_label(pool)}</b>\n\n"
        f"وضعیت: {status_line}\n\n"
        f"📊 <b>مصرف از استخر</b>\n"
        f"{_progress_bar(used, total_purchased)}\n"
        f"مصرف‌شده: {_fmt_gb(used)} GB از {_fmt_gb(total_purchased)} GB\n"
        f"باقیمونده: <b>{_fmt_gb(balance)} GB</b>\n\n"
        f"👥 مشتری‌ها: {active_customers} فعال از {total_customers} کل"
    )

    render(chat_id, text, kb, message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respool:"))
def respool_detail(call):
    pool_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)
    pool = _get_pool(pool_id, user_id)

    if not pool:
        bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    _render_pool_detail(call.message.chat.id, pool_id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respoolrefresh:"))
def respool_refresh(call):
    pool_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)
    pool = _get_pool(pool_id, user_id)

    if not pool:
        bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
        return

    bot.answer_callback_query(call.id, "⏳ در حال بروزرسانی مصرف...")
    try:
        reseller_billing.refresh_pool(pool_id)
    except Exception:
        pass
    _render_pool_detail(call.message.chat.id, pool_id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respoolcust:"))
def respool_customers(call):
    pool_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)
    pool = _get_pool(pool_id, user_id)

    if not pool:
        bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
        return

    services = db_execute("""
    SELECT * FROM services
    WHERE reseller_id=? AND panel_id=?
    ORDER BY id DESC
    LIMIT 50
    """, (pool["user_id"], pool["panel_id"]), fetchall=True) or []

    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup()

    if not services:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))
        render(call.message.chat.id, "📭 هنوز برای این پنل مشتری‌ای نساختی.", kb, call.message.message_id)
        return

    for svc in services:
        icon = "🟢" if svc["status"] == "active" else "🔴"
        kb.add(types.InlineKeyboardButton(f"{icon} {svc['username']}", callback_data=f"rescust:{svc['id']}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))

    render(
        call.message.chat.id,
        f"👥 <b>مشتری‌های {_pool_label(pool)}</b>\n\nروی هرکدوم بزن:",
        kb, call.message.message_id
    )


# ============================================================
# CREATE CUSTOMER SERVICE
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("resnew:"))
def resnew_start(call):
    pool_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)
    pool = _get_pool(pool_id, user_id)

    if not pool or (pool["balance"] or 0) <= 0:
        bot.answer_callback_query(call.id, "این استخر موجودی نداره.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))

    render(
        chat_id,
        "🏷 یه نام دلخواه برای این مشتری بفرست (فقط حروف/عدد انگلیسی، بدون فاصله):\n\n"
        "مثال: <code>ali</code>",
        kb,
        call.message.message_id
    )
    bot.register_next_step_handler_by_chat_id(chat_id, resnew_name, pool_id)


def _sanitize_customer_name(owner_id, raw):
    return f"res{owner_id}_{raw}"


def resnew_name(message, pool_id):
    chat_id = message.chat.id
    cc.drop(message)
    user_id = internal_user_id(message.from_user.id)
    pool = _get_pool(pool_id, user_id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))
    screen_id = cc.get_screen(chat_id)

    def _reask(text):
        if screen_id:
            try:
                bot.edit_message_text(text, chat_id, screen_id, reply_markup=kb)
            except Exception:
                cc.show(chat_id, text, reply_markup=kb)
        else:
            cc.show(chat_id, text, reply_markup=kb)
        bot.register_next_step_handler_by_chat_id(chat_id, resnew_name, pool_id)

    if not pool or (pool["balance"] or 0) <= 0:
        cc.show(chat_id, "❌ این استخر دیگه موجودی نداره.", reply_markup=_home_markup())
        return

    raw = (message.text or "").strip().lower()
    if not USERNAME_PATTERN.match(raw):
        _reask("❌ نام نامعتبره. فقط حروف/عدد انگلیسی و بدون فاصله (۲ تا ۲۰ کاراکتر). دوباره بفرست:")
        return

    final_username = _sanitize_customer_name(user_id, raw)
    exists = db_execute("SELECT id FROM services WHERE username=?", (final_username,), fetchone=True)
    if exists:
        _reask(f"❌ نام «{raw}» قبلاً استفاده شده. یه نام دیگه بفرست:")
        return

    _draft[chat_id] = {"pool_id": pool_id, "raw": raw}

    text = (
        f"📊 این مشتری چند گیگ داشته باشه؟ (فقط عدد)\n\n"
        f"باقیمونده‌ی استخرت: {_fmt_gb(pool['balance'])} گیگ"
    )
    if screen_id:
        try:
            bot.edit_message_text(text, chat_id, screen_id, reply_markup=kb)
        except Exception:
            cc.show(chat_id, text, reply_markup=kb)
    else:
        cc.show(chat_id, text, reply_markup=kb)
    bot.register_next_step_handler_by_chat_id(chat_id, resnew_volume, pool_id)


def resnew_volume(message, pool_id):
    chat_id = message.chat.id
    cc.drop(message)
    draft = _draft.get(chat_id)
    if not draft:
        return

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))
    screen_id = cc.get_screen(chat_id)

    text = (message.text or "").strip().replace(",", ".")
    try:
        volume = float(text)
        if volume <= 0:
            raise ValueError
    except ValueError:
        err = "❌ فقط عدد بزرگ‌تر از صفر بفرست:"
        if screen_id:
            try:
                bot.edit_message_text(err, chat_id, screen_id, reply_markup=kb)
            except Exception:
                cc.show(chat_id, err, reply_markup=kb)
        else:
            cc.show(chat_id, err, reply_markup=kb)
        bot.register_next_step_handler_by_chat_id(chat_id, resnew_volume, pool_id)
        return

    draft["volume"] = volume
    prompt = "⏳ چند روز اعتبار داشته باشه؟ (فقط عدد)"
    if screen_id:
        try:
            bot.edit_message_text(prompt, chat_id, screen_id, reply_markup=kb)
        except Exception:
            cc.show(chat_id, prompt, reply_markup=kb)
    else:
        cc.show(chat_id, prompt, reply_markup=kb)
    bot.register_next_step_handler_by_chat_id(chat_id, resnew_duration, pool_id)


def resnew_duration(message, pool_id):
    chat_id = message.chat.id
    cc.drop(message)
    draft = _draft.get(chat_id)
    if not draft:
        return

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))
    screen_id = cc.get_screen(chat_id)

    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        err = "❌ فقط عدد روز (بزرگ‌تر از صفر) بفرست:"
        if screen_id:
            try:
                bot.edit_message_text(err, chat_id, screen_id, reply_markup=kb)
            except Exception:
                cc.show(chat_id, err, reply_markup=kb)
        else:
            cc.show(chat_id, err, reply_markup=kb)
        bot.register_next_step_handler_by_chat_id(chat_id, resnew_duration, pool_id)
        return

    draft["duration"] = int(text)
    prompt = "📱 چند تا دستگاه همزمان مجاز باشه؟ (فقط عدد)"
    if screen_id:
        try:
            bot.edit_message_text(prompt, chat_id, screen_id, reply_markup=kb)
        except Exception:
            cc.show(chat_id, prompt, reply_markup=kb)
    else:
        cc.show(chat_id, prompt, reply_markup=kb)
    bot.register_next_step_handler_by_chat_id(chat_id, resnew_devices, pool_id)


def resnew_devices(message, pool_id):
    chat_id = message.chat.id
    cc.drop(message)
    draft = _draft.get(chat_id)
    if not draft:
        return

    user_id = internal_user_id(message.from_user.id)
    pool = _get_pool(pool_id, user_id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))
    screen_id = cc.get_screen(chat_id)

    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        err = "❌ فقط عدد بزرگ‌تر از صفر بفرست:"
        if screen_id:
            try:
                bot.edit_message_text(err, chat_id, screen_id, reply_markup=kb)
            except Exception:
                cc.show(chat_id, err, reply_markup=kb)
        else:
            cc.show(chat_id, err, reply_markup=kb)
        bot.register_next_step_handler_by_chat_id(chat_id, resnew_devices, pool_id)
        return

    draft["devices"] = int(text)

    if not pool or (pool["balance"] or 0) <= 0:
        _draft.pop(chat_id, None)
        cc.show(chat_id, "❌ این استخر دیگه موجودی نداره.", reply_markup=_home_markup())
        return

    final_username = _sanitize_customer_name(user_id, draft["raw"])
    kb2 = types.InlineKeyboardMarkup()
    kb2.row(
        types.InlineKeyboardButton("✅ بساز", callback_data="resmk_confirm"),
        types.InlineKeyboardButton("❌ انصراف", callback_data=f"respool:{pool_id}"),
    )

    text2 = (
        "🔎 <b>مشخصات سرویس مشتری</b>\n\n"
        f"🏷 استخر: {_pool_label(pool)}\n"
        f"👤 نام کاربری: <code>{final_username}</code>\n"
        f"📊 حجم: {_fmt_gb(draft['volume'])} گیگ\n"
        f"⏳ مدت: {draft['duration']} روز\n"
        f"📱 دستگاه: {draft['devices']}\n\n"
        "مصرف واقعی این مشتری از استخرت کم میشه. تایید می‌کنی؟"
    )
    if screen_id:
        try:
            bot.edit_message_text(text2, chat_id, screen_id, reply_markup=kb2, parse_mode="HTML")
            return
        except Exception:
            pass
    cc.show(chat_id, text2, reply_markup=kb2, parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: call.data == "resmk_confirm")
def resnew_confirm(call):
    chat_id = call.message.chat.id
    draft = _draft.get(chat_id)
    if not draft:
        bot.answer_callback_query(call.id, "⛔ این مرحله منقضی شده، دوباره از اول بزن.", show_alert=True)
        return

    pool_id = draft["pool_id"]
    user_id = internal_user_id(call.from_user.id)
    pool = _get_pool(pool_id, user_id)

    if not pool or (pool["balance"] or 0) <= 0:
        _draft.pop(chat_id, None)
        bot.answer_callback_query(call.id, "این استخر دیگه موجودی نداره.", show_alert=True)
        return

    panel = db_execute("SELECT * FROM panels WHERE id=?", (pool["panel_id"],), fetchone=True)
    if not panel:
        bot.answer_callback_query(call.id, "پنل این استخر پیدا نشد.", show_alert=True)
        return

    final_username = _sanitize_customer_name(user_id, draft["raw"])
    if db_execute("SELECT id FROM services WHERE username=?", (final_username,), fetchone=True):
        _draft.pop(chat_id, None)
        bot.answer_callback_query(call.id, "این نام همین الان گرفته شد، از اول با یه نام دیگه امتحان کن.", show_alert=True)
        return

    bot.answer_callback_query(call.id, "⏳ در حال ساخت سرویس...")
    try:
        bot.edit_message_text("⏳ در حال ساخت سرویس...", chat_id, call.message.message_id)
    except Exception:
        pass

    fake_plan = {
        "name": f"Reseller:{pool_id}",
        "price": 0,
        "volume": draft["volume"],
        "duration": draft["duration"],
        "devices": draft["devices"],
    }
    owner = {"telegram_id": f"reseller{user_id}"}

    result = pasarguard_create_service(
        panel=panel,
        telegram_user=owner,
        plan=fake_plan,
        desired_username=final_username
    )

    kb_back = types.InlineKeyboardMarkup()
    kb_back.add(types.InlineKeyboardButton("🔙 بازگشت به استخر", callback_data=f"respool:{pool_id}"))

    if not result.get("success"):
        render(
            chat_id,
            f"❌ ساخت سرویس ناموفق بود.\n\n<code>{result.get('error', 'نامشخص')}</code>",
            kb_back, call.message.message_id
        )
        _draft.pop(chat_id, None)
        return

    expires_at = (datetime.utcnow() + timedelta(days=draft["duration"])).strftime("%Y-%m-%d %H:%M:%S")

    db_execute("""
    INSERT INTO services
    (user_id, plan_id, panel_id, username, config, qr,
     volume, used_volume, duration, devices,
     expires_at, status, reseller_id, is_unlimited,
     created_at, updated_at)
    VALUES (?, NULL, ?, ?, ?, '', ?, 0, ?, ?, ?, 'active', ?, 0, ?, ?)
    """, (
        user_id, pool["panel_id"], result.get("username", final_username),
        result.get("config", ""), draft["volume"], draft["duration"], draft["devices"],
        expires_at, user_id, now(), now()
    ))

    _draft.pop(chat_id, None)

    render(
        chat_id,
        "🎉 <b>سرویس مشتری ساخته شد!</b>\n\n"
        f"👤 نام کاربری: <code>{result.get('username', final_username)}</code>\n"
        f"📊 حجم: {_fmt_gb(draft['volume'])} گیگ | ⏳ {draft['duration']} روز | 📱 {draft['devices']} دستگاه\n\n"
        f"🔗 لینک اشتراک (این رو به مشتریت بده):\n<code>{result.get('config', '---')}</code>",
        kb_back, call.message.message_id
    )


# ============================================================
# MY CUSTOMERS
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "res_customers")
def res_customers(call):
    bot.answer_callback_query(call.id)
    user_id = internal_user_id(call.from_user.id)

    services = db_execute("""
    SELECT * FROM services
    WHERE reseller_id=?
    ORDER BY id DESC
    LIMIT 50
    """, (user_id,), fetchall=True) or []

    kb = types.InlineKeyboardMarkup()

    if not services:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))
        render(call.message.chat.id, "📭 هنوز برای هیچ مشتری‌ای سرویس نساختی.", kb, call.message.message_id)
        return

    for svc in services:
        icon = "🟢" if svc["status"] == "active" else "🔴"
        kb.add(types.InlineKeyboardButton(f"{icon} {svc['username']}", callback_data=f"rescust:{svc['id']}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))

    render(call.message.chat.id, "👥 <b>کاربران من</b>\n\nروی هرکدوم بزن:", kb, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("rescust:"))
def rescust_detail(call):
    service_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)

    svc = db_execute(
        "SELECT * FROM services WHERE id=? AND reseller_id=?",
        (service_id, user_id), fetchone=True
    )
    if not svc:
        bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
        return

    bot.answer_callback_query(call.id)

    total_used = db_execute(
        "SELECT COALESCE(SUM(amount_gb),0) t FROM reseller_usage_log WHERE service_id=?",
        (service_id,), fetchone=True
    )["t"]

    status_label = "🟢 فعال" if svc["status"] == "active" else "🔴 غیرفعال"

    kb = types.InlineKeyboardMarkup()
    if svc["status"] == "active":
        kb.add(types.InlineKeyboardButton("⏸ غیرفعال کردن دستی", callback_data=f"respause:{service_id}"))
    else:
        kb.add(types.InlineKeyboardButton("▶️ فعال کردن دوباره", callback_data=f"resresume:{service_id}"))
    kb.add(types.InlineKeyboardButton("🗑 حذف سرویس", callback_data=f"resdel_ask:{service_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="res_customers"))

    render(
        call.message.chat.id,
        f"👤 <b>{svc['username']}</b>\n\n"
        f"وضعیت: {status_label}\n"
        f"📊 مجموع مصرف ثبت‌شده: {_fmt_gb(total_used)} گیگ\n"
        f"📅 ساخته‌شده: {svc['created_at']}\n\n"
        f"🔗 لینک اشتراک:\n<code>{svc['config'] or '---'}</code>",
        kb,
        call.message.message_id
    )


def _svc_panel(svc):
    if not svc["panel_id"]:
        return None
    return db_execute("SELECT * FROM panels WHERE id=?", (svc["panel_id"],), fetchone=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respause:"))
def respause(call):
    service_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)
    svc = db_execute("SELECT * FROM services WHERE id=? AND reseller_id=?", (service_id, user_id), fetchone=True)
    if not svc:
        bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
        return

    panel = _svc_panel(svc)
    if panel and svc["username"]:
        pasarguard_set_status(panel, svc["username"], enabled=False)

    db_execute("UPDATE services SET status='disabled', updated_at=? WHERE id=?", (now(), service_id))
    bot.answer_callback_query(call.id, "⏸ غیرفعال شد.")
    rescust_detail(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("resresume:"))
def resresume(call):
    service_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)
    svc = db_execute("SELECT * FROM services WHERE id=? AND reseller_id=?", (service_id, user_id), fetchone=True)
    if not svc:
        bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
        return

    pool = db_execute(
        "SELECT * FROM reseller_panels WHERE user_id=? AND panel_id=?",
        (user_id, svc["panel_id"]), fetchone=True
    )
    if not pool or (pool["balance"] or 0) <= 0:
        bot.answer_callback_query(call.id, "❌ استخر این پنل موجودی نداره، اول شارژ کن.", show_alert=True)
        return

    panel = _svc_panel(svc)
    if panel and svc["username"]:
        result = pasarguard_set_status(panel, svc["username"], enabled=True)
        if not result.get("success"):
            bot.answer_callback_query(call.id, f"خطا: {result.get('error')}", show_alert=True)
            return

    db_execute("UPDATE services SET status='active', updated_at=? WHERE id=?", (now(), service_id))
    db_execute("UPDATE reseller_panels SET active=1 WHERE id=?", (pool["id"],))
    bot.answer_callback_query(call.id, "▶️ دوباره فعال شد.")
    rescust_detail(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("resdel_ask:"))
def resdel_ask(call):
    service_id = int(call.data.split(":")[1])
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"resdel_go:{service_id}"),
        types.InlineKeyboardButton("❌ انصراف", callback_data=f"rescust:{service_id}"),
    )
    bot.answer_callback_query(call.id)
    render(
        call.message.chat.id,
        "⚠️ مطمئنی می‌خوای این سرویس رو حذف کنی؟ لینک اشتراکش از کار میفته.",
        kb, call.message.message_id
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("resdel_go:"))
def resdel_go(call):
    service_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)
    svc = db_execute("SELECT * FROM services WHERE id=? AND reseller_id=?", (service_id, user_id), fetchone=True)
    if not svc:
        bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
        return

    panel = _svc_panel(svc)
    warning = ""
    if panel and svc["username"]:
        result = pasarguard_delete_service(panel, svc["username"])
        if not result.get("success"):
            warning = f"\n\n⚠️ حذف از پنل انجام نشد: {result.get('error')}"

    db_execute("DELETE FROM services WHERE id=?", (service_id,))
    bot.answer_callback_query(call.id, "🗑 حذف شد.")

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="res_customers"))
    render(call.message.chat.id, f"✅ سرویس حذف شد.{warning}", kb, call.message.message_id)


# ============================================================
# STATS
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "res_stats")
def res_stats(call):
    bot.answer_callback_query(call.id)
    user_id = internal_user_id(call.from_user.id)

    pools = db_execute("SELECT * FROM reseller_panels WHERE user_id=?", (user_id,), fetchall=True) or []
    total_remaining = sum((p["balance"] or 0) for p in pools)
    total_purchased = sum((p["total_purchased"] or 0) for p in pools)

    customers_count = db_execute(
        "SELECT COUNT(*) c FROM services WHERE reseller_id=?",
        (user_id,), fetchone=True
    )["c"]
    active_count = db_execute(
        "SELECT COUNT(*) c FROM services WHERE reseller_id=? AND status='active'",
        (user_id,), fetchone=True
    )["c"]

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))

    render(
        call.message.chat.id,
        "📈 <b>آمار نمایندگی من</b>\n\n"
        f"📦 مجموع حجم خریداری‌شده: {_fmt_gb(total_purchased)} گیگ\n"
        f"📊 مجموع باقیمونده: {_fmt_gb(total_remaining)} گیگ\n"
        f"👥 تعداد مشتری‌ها: {customers_count}\n"
        f"🟢 مشتری‌های فعال: {active_count}",
        kb,
        call.message.message_id
    )
