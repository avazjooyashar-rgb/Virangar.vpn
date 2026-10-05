# ============================================================
# admin_reseller.py  [نسخه‌ی اصلاح‌شده]
# پنل سوپرادمین برای نمایندگی:
#   - مدیریت پلن‌های نمایندگی (نام، پنل مبدا، حجم، قیمت)
#   - لیست نماینده‌ها، استخر هر کدوم، و تنظیم دستی موجودی
#
# تغییرات این نسخه:
#   - هندلر انتخاب پنل (ares:pnpanel) اول به تلگرام جواب میده،
#     بعد کار دیتابیس رو انجام میده و هر خطا رو تو چت نشون میده
#   - return_lastrowid حذف شد؛ آیدی پلن با SELECT گرفته میشه
#   - INSERT فقط روی ستون‌هایی انجام میشه که تو جدول وجود دارن
#   - حذف پلن، گزینه‌های حجمیِ اون رو هم پاک می‌کنه
# ============================================================

import traceback

from telebot import types

from config import bot
from database import db_execute, now
from decorators import admin_only, admin_only_call
from keyboards import admin_keyboard
import chat_clean as cc


_state = {}  # chat_id -> dict (فقط برای فلوی ساخت/ویرایش پلن نمایندگی)


def _fmt_gb(value):
    value = value or 0
    return int(value) if float(value) == int(value) else round(value, 2)


def render(chat_id, text, kb, message_id=None):
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="HTML")
            return message_id
        except Exception:
            pass
    sent = cc.show(chat_id, text, key="admin_menu", reply_markup=kb, parse_mode="HTML")
    return sent.message_id if sent else None


def _back_markup(cb, label="🔙 بازگشت"):
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton(label, callback_data=cb))
    return m


def _report_error(chat_id, where, exc):
    """خطا رو تو لاگ سرور چاپ می‌کنه و متنش رو تو چت نشون میده."""
    traceback.print_exc()
    try:
        bot.send_message(
            chat_id,
            f"⚠️ خطا ({where}):\n<code>{type(exc).__name__}: {exc}</code>",
            parse_mode="HTML"
        )
    except Exception:
        pass


# ============================================================
# ENTRY
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🤝 مدیریت نمایندگان")
@admin_only
def admin_reseller_entry(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    cc.drop(message)
    render_main_menu(message.chat.id)


def render_main_menu(chat_id, message_id=None):
    resellers_count = db_execute(
        "SELECT COUNT(DISTINCT user_id) c FROM reseller_panels", fetchone=True
    )["c"]
    plans_count = db_execute(
        "SELECT COUNT(*) c FROM reseller_plans WHERE active=1", fetchone=True
    )["c"]
    total_remaining = db_execute(
        "SELECT COALESCE(SUM(balance),0) t FROM reseller_panels", fetchone=True
    )["t"]

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💎 پلن‌های نمایندگی", callback_data="ares:plans"))
    kb.add(types.InlineKeyboardButton("👥 لیست نماینده‌ها", callback_data="ares:list:0"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="adm_back"))

    text = (
        "🤝 <b>مدیریت نمایندگی</b>\n\n"
        f"💎 پلن‌های فعال: <b>{plans_count}</b>\n"
        f"👥 تعداد نماینده: <b>{resellers_count}</b>\n"
        f"📊 مجموع حجم باقیمانده‌ی همه: <b>{_fmt_gb(total_remaining)} GB</b>"
    )
    render(chat_id, text, kb, message_id)


@bot.callback_query_handler(func=lambda c: c.data == "ares:menu")
@admin_only_call
def cb_ares_menu(call):
    bot.answer_callback_query(call.id)
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _state.pop(call.message.chat.id, None)
    render_main_menu(call.message.chat.id, call.message.message_id)


# ============================================================
# PLAN LIST
# ============================================================

def render_plan_list(chat_id, message_id=None):
    plans = db_execute("""
    SELECT reseller_plans.*, panels.name AS panel_name
    FROM reseller_plans
    LEFT JOIN panels ON panels.id = reseller_plans.panel_id
    ORDER BY reseller_plans.id DESC
    """, fetchall=True) or []

    kb = types.InlineKeyboardMarkup()
    for p in plans:
        icon = "🟢" if p["active"] else "🔴"
        kb.add(types.InlineKeyboardButton(
            f"{icon} {p['name']} | {p['panel_name'] or '---'}",
            callback_data=f"ares:plan:{p['id']}"
        ))
    kb.add(types.InlineKeyboardButton("➕ افزودن پلن جدید", callback_data="ares:plan_new"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="ares:menu"))

    text = "💎 <b>پلن‌های نمایندگی</b>\n\n" + ("روی هرکدوم بزن برای ویرایش:" if plans else "هنوز پلنی نساختی.")
    render(chat_id, text, kb, message_id)


@bot.callback_query_handler(func=lambda c: c.data == "ares:plans")
@admin_only_call
def cb_ares_plans(call):
    bot.answer_callback_query(call.id)
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _state.pop(call.message.chat.id, None)
    render_plan_list(call.message.chat.id, call.message.message_id)


# ============================================================
# PLAN DETAIL / EDIT
# ============================================================

def _plan_tiers(plan_id):
    return db_execute(
        "SELECT * FROM reseller_plan_tiers WHERE plan_id=? ORDER BY sort_order, volume_gb",
        (plan_id,), fetchall=True
    ) or []


def render_plan_detail(chat_id, plan_id, message_id=None):
    p = db_execute("""
    SELECT reseller_plans.*, panels.name AS panel_name
    FROM reseller_plans
    LEFT JOIN panels ON panels.id = reseller_plans.panel_id
    WHERE reseller_plans.id=?
    """, (plan_id,), fetchone=True)

    if not p:
        render(chat_id, "❌ این پلن دیگه وجود نداره.", _back_markup("ares:plans"), message_id)
        return

    tiers = _plan_tiers(plan_id)
    custom_on = bool(p["price_per_gb"] and p["price_per_gb"] > 0)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✏️ نام", callback_data=f"ares:pedit:name:{plan_id}"))
    kb.add(types.InlineKeyboardButton("🔁 تغییر پنل", callback_data=f"ares:pedit:panel:{plan_id}"))

    for t in tiers:
        kb.row(
            types.InlineKeyboardButton(
                f"📦 {_fmt_gb(t['volume_gb'])}GB — {t['price']:,} تومان",
                callback_data=f"ares:tier_noop:{t['id']}"
            ),
            types.InlineKeyboardButton("🗑", callback_data=f"ares:tier_del_ask:{t['id']}:{plan_id}"),
        )
    kb.add(types.InlineKeyboardButton("➕ افزودن حجم آماده", callback_data=f"ares:tier_new:{plan_id}"))

    custom_label = (
        f"💬 حجم دلخواه: فعال ({p['price_per_gb']:,} ت/گیگ، حداقل {_fmt_gb(p['custom_min_gb'] or 300)}GB)"
        if custom_on else "💬 حجم دلخواه: غیرفعال"
    )
    kb.add(types.InlineKeyboardButton(custom_label, callback_data=f"ares:custom_set:{plan_id}"))
    if custom_on:
        kb.add(types.InlineKeyboardButton("🚫 غیرفعال کردن حجم دلخواه", callback_data=f"ares:custom_off:{plan_id}"))

    kb.add(types.InlineKeyboardButton(
        "🔴 غیرفعال کردن کل پلن" if p["active"] else "🟢 فعال کردن کل پلن",
        callback_data=f"ares:ptoggle:{plan_id}"
    ))
    kb.add(types.InlineKeyboardButton("🗑 حذف پلن", callback_data=f"ares:pdel_ask:{plan_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="ares:plans"))

    lines = [
        f"💎 <b>{p['name']}</b>\n",
        f"وضعیت: {'🟢 فعال' if p['active'] else '🔴 غیرفعال'}",
        f"🖥 پنل: {p['panel_name'] or '---'}",
        "⏳ بدون محدودیت زمانی\n",
    ]
    if not tiers and not custom_on:
        lines.append("⚠️ هنوز هیچ گزینه‌ی خریدی (حجم آماده یا دلخواه) نداره؛ نماینده چیزی برای انتخاب نمی‌بینه.")
    else:
        lines.append(f"📦 {len(tiers)} گزینه‌ی حجم آماده تعریف شده.")
        lines.append("💬 حجم دلخواه " + ("فعاله." if custom_on else "غیرفعاله."))

    render(chat_id, "\n".join(lines), kb, message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:tier_noop:"))
@admin_only_call
def cb_ares_tier_noop(call):
    bot.answer_callback_query(call.id, "برای حذف، روی 🗑 کنارش بزن.")


# ---------------- ADD TIER ----------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:tier_new:"))
@admin_only_call
def cb_ares_tier_new(call):
    bot.answer_callback_query(call.id)
    plan_id = int(call.data.split(":")[2])
    chat_id = call.message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    _state[chat_id] = {"flow": "tier_new", "plan_id": plan_id, "data": {}}
    render(chat_id, "📊 حجم این گزینه رو به گیگابایت بفرست (فقط عدد، مثلاً 750):",
           _back_markup(f"ares:plan:{plan_id}"), call.message.message_id)
    bot.register_next_step_handler_by_chat_id(chat_id, _tier_new_volume)


def _tier_new_volume(message):
    chat_id = message.chat.id
    cc.drop(message)
    st = _state.get(chat_id)
    if not st or st.get("flow") != "tier_new":
        return
    screen_id = cc.get_screen(chat_id, "admin_menu")
    plan_id = st["plan_id"]
    try:
        value = float((message.text or "").strip().replace(",", "."))
        if value <= 0:
            raise ValueError
    except ValueError:
        render(chat_id, "❌ فقط عدد بزرگ‌تر از صفر بفرست:", _back_markup(f"ares:plan:{plan_id}"), screen_id)
        bot.register_next_step_handler_by_chat_id(chat_id, _tier_new_volume)
        return
    st["data"]["volume_gb"] = value
    render(chat_id, "💰 قیمت این گزینه رو به تومان بفرست (فقط عدد):", _back_markup(f"ares:plan:{plan_id}"), screen_id)
    bot.register_next_step_handler_by_chat_id(chat_id, _tier_new_price)


def _tier_new_price(message):
    chat_id = message.chat.id
    cc.drop(message)
    st = _state.get(chat_id)
    if not st or st.get("flow") != "tier_new":
        return
    screen_id = cc.get_screen(chat_id, "admin_menu")
    plan_id = st["plan_id"]
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        render(chat_id, "❌ فقط عدد بزرگ‌تر از صفر بفرست:", _back_markup(f"ares:plan:{plan_id}"), screen_id)
        bot.register_next_step_handler_by_chat_id(chat_id, _tier_new_price)
        return

    try:
        db_execute("""
        INSERT INTO reseller_plan_tiers (plan_id, volume_gb, price, sort_order, created_at)
        VALUES (?, ?, ?, 0, ?)
        """, (plan_id, st["data"]["volume_gb"], int(text), now()))
    except Exception as e:
        _state.pop(chat_id, None)
        _report_error(chat_id, "افزودن حجم آماده", e)
        return

    _state.pop(chat_id, None)
    render_plan_detail(chat_id, plan_id, screen_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:tier_del_ask:"))
@admin_only_call
def cb_ares_tier_del_ask(call):
    bot.answer_callback_query(call.id)
    _, _, tier_id, plan_id = call.data.split(":")
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ بله", callback_data=f"ares:tier_del_go:{tier_id}:{plan_id}"),
        types.InlineKeyboardButton("❌ نه", callback_data=f"ares:plan:{plan_id}")
    )
    render(call.message.chat.id, "این گزینه‌ی حجم حذف بشه؟", kb, call.message.message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:tier_del_go:"))
@admin_only_call
def cb_ares_tier_del_go(call):
    bot.answer_callback_query(call.id, "🗑 حذف شد.")
    _, _, tier_id, plan_id = call.data.split(":")
    db_execute("DELETE FROM reseller_plan_tiers WHERE id=?", (int(tier_id),))
    render_plan_detail(call.message.chat.id, int(plan_id), call.message.message_id)


# ---------------- CUSTOM VOLUME (price per GB + minimum) ----------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:custom_off:"))
@admin_only_call
def cb_ares_custom_off(call):
    bot.answer_callback_query(call.id, "✅ حجم دلخواه غیرفعال شد.")
    plan_id = int(call.data.split(":")[2])
    db_execute("UPDATE reseller_plans SET price_per_gb=0 WHERE id=?", (plan_id,))
    render_plan_detail(call.message.chat.id, plan_id, call.message.message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:custom_set:"))
@admin_only_call
def cb_ares_custom_set(call):
    bot.answer_callback_query(call.id)
    plan_id = int(call.data.split(":")[2])
    chat_id = call.message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    _state[chat_id] = {"flow": "custom_set", "plan_id": plan_id, "data": {}}
    render(
        chat_id,
        "💬 برای «حجم دلخواه»، قیمت هر گیگ رو به تومان بفرست (فقط عدد):",
        _back_markup(f"ares:plan:{plan_id}"), call.message.message_id
    )
    bot.register_next_step_handler_by_chat_id(chat_id, _custom_set_price)


def _custom_set_price(message):
    chat_id = message.chat.id
    cc.drop(message)
    st = _state.get(chat_id)
    if not st or st.get("flow") != "custom_set":
        return
    screen_id = cc.get_screen(chat_id, "admin_menu")
    plan_id = st["plan_id"]
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        render(chat_id, "❌ فقط عدد بزرگ‌تر از صفر بفرست:", _back_markup(f"ares:plan:{plan_id}"), screen_id)
        bot.register_next_step_handler_by_chat_id(chat_id, _custom_set_price)
        return
    st["data"]["price_per_gb"] = int(text)
    render(
        chat_id,
        "📏 حداقل حجم مجاز برای خرید دلخواه رو به گیگ بفرست (مثلاً 300):",
        _back_markup(f"ares:plan:{plan_id}"), screen_id
    )
    bot.register_next_step_handler_by_chat_id(chat_id, _custom_set_min)


def _custom_set_min(message):
    chat_id = message.chat.id
    cc.drop(message)
    st = _state.get(chat_id)
    if not st or st.get("flow") != "custom_set":
        return
    screen_id = cc.get_screen(chat_id, "admin_menu")
    plan_id = st["plan_id"]
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        render(chat_id, "❌ فقط عدد بزرگ‌تر از صفر بفرست:", _back_markup(f"ares:plan:{plan_id}"), screen_id)
        bot.register_next_step_handler_by_chat_id(chat_id, _custom_set_min)
        return

    try:
        db_execute(
            "UPDATE reseller_plans SET price_per_gb=?, custom_min_gb=? WHERE id=?",
            (st["data"]["price_per_gb"], int(text), plan_id)
        )
    except Exception as e:
        _state.pop(chat_id, None)
        _report_error(chat_id, "حجم دلخواه", e)
        return

    _state.pop(chat_id, None)
    render_plan_detail(chat_id, plan_id, screen_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:plan:"))
@admin_only_call
def cb_ares_plan_detail(call):
    bot.answer_callback_query(call.id)
    plan_id = int(call.data.split(":")[2])
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _state.pop(call.message.chat.id, None)
    render_plan_detail(call.message.chat.id, plan_id, call.message.message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:ptoggle:"))
@admin_only_call
def cb_ares_ptoggle(call):
    plan_id = int(call.data.split(":")[2])
    p = db_execute("SELECT active FROM reseller_plans WHERE id=?", (plan_id,), fetchone=True)
    if not p:
        bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
        return
    bot.answer_callback_query(call.id, "✅ تغییر کرد.")
    db_execute("UPDATE reseller_plans SET active=? WHERE id=?", (0 if p["active"] else 1, plan_id))
    render_plan_detail(call.message.chat.id, plan_id, call.message.message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:pdel_ask:"))
@admin_only_call
def cb_ares_pdel_ask(call):
    bot.answer_callback_query(call.id)
    plan_id = int(call.data.split(":")[2])
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"ares:pdel_go:{plan_id}"),
        types.InlineKeyboardButton("❌ نه", callback_data=f"ares:plan:{plan_id}")
    )
    render(
        call.message.chat.id,
        "⚠️ حذف پلن فقط جلوی خرید جدید از روش رو می‌گیره؛ استخرهایی که قبلاً از این پلن پر شدن دست‌نخورده می‌مونن.\n\nمطمئنی؟",
        kb, call.message.message_id
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:pdel_go:"))
@admin_only_call
def cb_ares_pdel_go(call):
    bot.answer_callback_query(call.id, "🗑 حذف شد.")
    plan_id = int(call.data.split(":")[2])
    try:
        db_execute("DELETE FROM reseller_plan_tiers WHERE plan_id=?", (plan_id,))
        db_execute("DELETE FROM reseller_plans WHERE id=?", (plan_id,))
        render_plan_list(call.message.chat.id, call.message.message_id)
    except Exception as e:
        _report_error(call.message.chat.id, "حذف پلن", e)


# ---------------- EDIT FIELDS (name) ----------------

_FIELD_PROMPTS = {
    "name": "✏️ اسم جدید پلن رو بفرست:",
}


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:pedit:") and c.data.split(":")[2] != "panel")
@admin_only_call
def cb_ares_pedit_start(call):
    _, _, field, plan_id = call.data.split(":")
    plan_id = int(plan_id)
    chat_id = call.message.chat.id

    if field not in _FIELD_PROMPTS:
        bot.answer_callback_query(call.id, "فیلد نامعتبر.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    bot.clear_step_handler_by_chat_id(chat_id)
    render(chat_id, _FIELD_PROMPTS[field], _back_markup(f"ares:plan:{plan_id}"), call.message.message_id)
    bot.register_next_step_handler_by_chat_id(chat_id, _pedit_save, field, plan_id)


def _pedit_save(message, field, plan_id):
    chat_id = message.chat.id
    cc.drop(message)
    text = (message.text or "").strip()
    screen_id = cc.get_screen(chat_id, "admin_menu")

    if field == "name":
        if not text:
            render(chat_id, "❌ نام خالیه. دوباره بفرست:", _back_markup(f"ares:plan:{plan_id}"), screen_id)
            bot.register_next_step_handler_by_chat_id(chat_id, _pedit_save, field, plan_id)
            return
        db_execute("UPDATE reseller_plans SET name=? WHERE id=?", (text[:60], plan_id))

    render_plan_detail(chat_id, plan_id, screen_id)


# ---------------- EDIT / PICK PANEL ----------------

def _panel_pick_markup(cb_prefix, extra=""):
    panels = db_execute("SELECT * FROM panels WHERE active=1 ORDER BY name", fetchall=True) or []
    kb = types.InlineKeyboardMarkup()
    for p in panels:
        kb.add(types.InlineKeyboardButton(p["name"], callback_data=f"{cb_prefix}:{p['id']}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=extra or "ares:plans"))
    return kb, bool(panels)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:pedit:panel:"))
@admin_only_call
def cb_ares_pedit_panel(call):
    bot.answer_callback_query(call.id)
    plan_id = int(call.data.split(":")[3])
    kb, has_panels = _panel_pick_markup(f"ares:ppanel:{plan_id}", extra=f"ares:plan:{plan_id}")
    text = "🔁 پنل مبدا جدید رو انتخاب کن:" if has_panels else "📭 هیچ پنل فعالی نداری."
    render(call.message.chat.id, text, kb, call.message.message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:ppanel:"))
@admin_only_call
def cb_ares_ppanel_set(call):
    bot.answer_callback_query(call.id, "✅ پنل عوض شد.")
    _, _, plan_id, panel_id = call.data.split(":")
    db_execute("UPDATE reseller_plans SET panel_id=? WHERE id=?", (int(panel_id), int(plan_id)))
    render_plan_detail(call.message.chat.id, int(plan_id), call.message.message_id)


# ---------------- NEW PLAN WIZARD ----------------

@bot.callback_query_handler(func=lambda c: c.data == "ares:plan_new")
@admin_only_call
def cb_ares_plan_new(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    _state[chat_id] = {"flow": "rplan_new", "data": {}}
    render(chat_id, "✏️ اسم پلن رو بفرست (مثلاً «مولتی‌لوکیشن ۵۰۰ گیگ»):", _back_markup("ares:plans"), call.message.message_id)
    bot.register_next_step_handler_by_chat_id(chat_id, _new_plan_name)


def _check_new_flow(chat_id):
    st = _state.get(chat_id)
    return st if st and st.get("flow") == "rplan_new" else None


def _new_plan_name(message):
    chat_id = message.chat.id
    cc.drop(message)
    st = _check_new_flow(chat_id)
    if not st:
        return
    name = (message.text or "").strip()
    screen_id = cc.get_screen(chat_id, "admin_menu")
    if not name:
        render(chat_id, "❌ اسم خالیه. دوباره بفرست:", _back_markup("ares:plans"), screen_id)
        bot.register_next_step_handler_by_chat_id(chat_id, _new_plan_name)
        return
    st["data"]["name"] = name[:60]

    kb, has_panels = _panel_pick_markup("ares:pnpanel")
    if not has_panels:
        render(chat_id, "📭 اول باید حداقل یه پنل فعال داشته باشی.", _back_markup("ares:plans"), screen_id)
        _state.pop(chat_id, None)
        return
    render(chat_id, "🖥 این پلن از کدوم پنل حجم بده؟", kb, screen_id)


def _reseller_plans_columns():
    """اسم ستون‌های واقعیِ جدول reseller_plans رو برمی‌گردونه (یا None اگه نشد)."""
    try:
        rows = db_execute("PRAGMA table_info(reseller_plans)", fetchall=True) or []
        cols = {r["name"] for r in rows}
        return cols or None
    except Exception:
        return None


def _insert_reseller_plan(name, panel_id):
    """
    پلن جدید رو می‌سازه و فقط ستون‌هایی رو پر می‌کنه که تو جدول هستن.
    آیدی پلن رو با SELECT برمی‌گردونه.
    """
    values = {
        "name": name,
        "price": 0,
        "capacity": 0,
        "duration": 0,
        "active": 1,
        "panel_id": panel_id,
        "volume_gb": 0,
        "created_at": now(),
    }
    existing = _reseller_plans_columns()
    if existing:
        values = {k: v for k, v in values.items() if k in existing}

    cols = list(values.keys())
    placeholders = ", ".join("?" for _ in cols)
    db_execute(
        f"INSERT INTO reseller_plans ({', '.join(cols)}) VALUES ({placeholders})",
        tuple(values[c] for c in cols)
    )

    row = db_execute(
        "SELECT id FROM reseller_plans WHERE name=? AND panel_id=? ORDER BY id DESC LIMIT 1",
        (name, panel_id), fetchone=True
    )
    return row["id"] if row else None


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:pnpanel:"))
@admin_only_call
def cb_ares_pnpanel(call):
    chat_id = call.message.chat.id
    st = _check_new_flow(chat_id)
    if not st:
        bot.answer_callback_query(call.id, "⛔ این مرحله منقضی شده.", show_alert=True)
        return

    # اول به تلگرام جواب بده تا دکمه گیر نکنه، حتی اگه بعدش خطا بیاد
    bot.answer_callback_query(call.id, "⏳ در حال ساخت پلن...")

    try:
        panel_id = int(call.data.split(":")[2])
        data = st["data"]

        new_id = _insert_reseller_plan(data["name"], panel_id)
        _state.pop(chat_id, None)

        if new_id:
            render_plan_detail(chat_id, new_id, call.message.message_id)
        else:
            render_plan_list(chat_id, call.message.message_id)
    except Exception as e:
        _report_error(chat_id, "ساخت پلن نمایندگی", e)


# ============================================================
# RESELLERS LIST
# ============================================================

RES_PAGE_SIZE = 8


def render_reseller_list(chat_id, page, message_id=None):
    rows = db_execute("""
    SELECT reseller_panels.user_id, users.telegram_id, users.username,
           COALESCE(SUM(reseller_panels.balance), 0) AS total_balance,
           COUNT(DISTINCT reseller_panels.id) AS pools
    FROM reseller_panels
    LEFT JOIN users ON users.id = reseller_panels.user_id
    GROUP BY reseller_panels.user_id
    ORDER BY total_balance DESC
    """, fetchall=True) or []

    total = len(rows)
    start = page * RES_PAGE_SIZE
    page_rows = rows[start:start + RES_PAGE_SIZE]

    kb = types.InlineKeyboardMarkup()
    for r in page_rows:
        label = f"@{r['username']}" if r["username"] else str(r["telegram_id"])
        kb.add(types.InlineKeyboardButton(
            f"👤 {label} | {_fmt_gb(r['total_balance'])}GB | {r['pools']} پنل",
            callback_data=f"ares:rv:{r['user_id']}:{page}"
        ))

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data=f"ares:list:{page-1}"))
    if start + RES_PAGE_SIZE < total:
        nav.append(types.InlineKeyboardButton("بعدی ➡️", callback_data=f"ares:list:{page+1}"))
    if nav:
        kb.row(*nav)

    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="ares:menu"))

    text = f"👥 <b>نماینده‌ها</b>\n\n{total} نفر" if rows else "📭 هنوز هیچ نماینده‌ای حجم نخریده."
    render(chat_id, text, kb, message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:list:"))
@admin_only_call
def cb_ares_list(call):
    bot.answer_callback_query(call.id)
    page = int(call.data.split(":")[2])
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    render_reseller_list(call.message.chat.id, page, call.message.message_id)


# ============================================================
# RESELLER DETAIL (pools + manual adjust + customers count)
# ============================================================

def render_reseller_detail(chat_id, reseller_user_id, back_page, message_id=None):
    user = db_execute("SELECT * FROM users WHERE id=?", (reseller_user_id,), fetchone=True)
    pools = db_execute("""
    SELECT reseller_panels.*, panels.name AS panel_name
    FROM reseller_panels
    LEFT JOIN panels ON panels.id = reseller_panels.panel_id
    WHERE reseller_panels.user_id=?
    ORDER BY reseller_panels.id
    """, (reseller_user_id,), fetchall=True) or []

    customers = db_execute(
        "SELECT COUNT(*) c FROM services WHERE reseller_id=?", (reseller_user_id,), fetchone=True
    )["c"]
    active_customers = db_execute(
        "SELECT COUNT(*) c FROM services WHERE reseller_id=? AND status='active'", (reseller_user_id,), fetchone=True
    )["c"]

    label = f"@{user['username']}" if user and user["username"] else (user["telegram_id"] if user else "---")

    lines = [
        f"👤 <b>نماینده: {label}</b>\n",
        f"🆔 Telegram ID: <code>{user['telegram_id'] if user else '---'}</code>",
        f"👥 مشتری‌ها: {active_customers} فعال از {customers} کل\n",
        "🖥 <b>استخرها:</b>"
    ]
    kb = types.InlineKeyboardMarkup()
    for pool in pools:
        used = (pool["total_purchased"] or 0) - (pool["balance"] or 0)
        lines.append(
            f"\n🔹 {pool['panel_name'] or '---'}\n"
            f"   باقیمانده: {_fmt_gb(pool['balance'])} GB از {_fmt_gb(pool['total_purchased'])} GB خریداری‌شده\n"
            f"   مصرف‌شده: {_fmt_gb(used)} GB | {'🟢 فعال' if pool['active'] else '🔴 غیرفعال (تموم‌شده)'}"
        )
        kb.row(
            types.InlineKeyboardButton(f"➕ افزودن دستی ({pool['panel_name']})", callback_data=f"ares:padj:{pool['id']}:add"),
            types.InlineKeyboardButton(f"➖ کم کردن دستی ({pool['panel_name']})", callback_data=f"ares:padj:{pool['id']}:sub"),
        )

    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data=f"ares:list:{back_page}"))

    render(chat_id, "\n".join(lines), kb, message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:rv:"))
@admin_only_call
def cb_ares_rv(call):
    bot.answer_callback_query(call.id)
    _, _, reseller_user_id, back_page = call.data.split(":")
    render_reseller_detail(call.message.chat.id, int(reseller_user_id), int(back_page), call.message.message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:padj:") and not c.data.startswith("ares:padj_cancel:"))
@admin_only_call
def cb_ares_padj_start(call):
    bot.answer_callback_query(call.id)
    _, _, pool_id, direction = call.data.split(":")
    pool_id = int(pool_id)
    chat_id = call.message.chat.id

    bot.clear_step_handler_by_chat_id(chat_id)
    _state[chat_id] = {"flow": "radj", "pool_id": pool_id, "direction": direction}

    prompt = "➕ چند گیگ اضافه بشه؟ (فقط عدد)" if direction == "add" else "➖ چند گیگ کم بشه؟ (فقط عدد)"
    render(chat_id, prompt, _back_markup(f"ares:padj_cancel:{pool_id}"), call.message.message_id)
    bot.register_next_step_handler_by_chat_id(chat_id, _padj_save)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:padj_cancel:"))
@admin_only_call
def cb_ares_padj_cancel(call):
    bot.answer_callback_query(call.id)
    pool_id = int(call.data.split(":")[2])
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _state.pop(call.message.chat.id, None)
    pool = db_execute("SELECT user_id FROM reseller_panels WHERE id=?", (pool_id,), fetchone=True)
    if pool:
        render_reseller_detail(call.message.chat.id, pool["user_id"], 0, call.message.message_id)


def _padj_save(message):
    chat_id = message.chat.id
    cc.drop(message)
    st = _state.get(chat_id)
    if not st or st.get("flow") != "radj":
        return

    screen_id = cc.get_screen(chat_id, "admin_menu")
    text = (message.text or "").strip().replace(",", ".")
    try:
        value = float(text)
        if value <= 0:
            raise ValueError
    except ValueError:
        render(chat_id, "❌ فقط عدد بزرگ‌تر از صفر بفرست:", _back_markup(f"ares:padj_cancel:{st['pool_id']}"), screen_id)
        bot.register_next_step_handler_by_chat_id(chat_id, _padj_save)
        return

    pool = db_execute("SELECT * FROM reseller_panels WHERE id=?", (st["pool_id"],), fetchone=True)
    if not pool:
        _state.pop(chat_id, None)
        render(chat_id, "❌ این استخر دیگه وجود نداره.", _back_markup("ares:menu"), screen_id)
        return

    if st["direction"] == "add":
        new_balance = (pool["balance"] or 0) + value
        new_total = (pool["total_purchased"] or 0) + value
    else:
        new_balance = max(0, (pool["balance"] or 0) - value)
        new_total = pool["total_purchased"] or 0

    db_execute(
        "UPDATE reseller_panels SET balance=?, total_purchased=?, active=1, updated_at=? WHERE id=?",
        (new_balance, new_total, now(), pool["id"])
    )

    _state.pop(chat_id, None)
    render_reseller_detail(chat_id, pool["user_id"], 0, screen_id)
