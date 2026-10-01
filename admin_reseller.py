# ============================================================
# admin_reseller.py
# پنل سوپرادمین برای نمایندگی:
#   - مدیریت پلن‌های نمایندگی (نام، پنل مبدا، حجم، قیمت)
#   - لیست نماینده‌ها، استخر هر کدوم، و تنظیم دستی موجودی
# دکمه‌ی «🤝 نمایندگان» تو کیبورد ادمین از قبل بود ولی هندلر نداشت؛
# این فایل همون دکمه رو فعال می‌کنه.
# ============================================================

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


# ============================================================
# ENTRY
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🤝 نمایندگان")
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
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    render_main_menu(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)


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
            f"{icon} {p['name']} | {_fmt_gb(p['volume_gb'])}GB | {p['price']:,}",
            callback_data=f"ares:plan:{p['id']}"
        ))
    kb.add(types.InlineKeyboardButton("➕ افزودن پلن جدید", callback_data="ares:plan_new"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="ares:menu"))

    text = "💎 <b>پلن‌های نمایندگی</b>\n\n" + ("روی هرکدوم بزن برای ویرایش:" if plans else "هنوز پلنی نساختی.")
    render(chat_id, text, kb, message_id)


@bot.callback_query_handler(func=lambda c: c.data == "ares:plans")
@admin_only_call
def cb_ares_plans(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    render_plan_list(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)


# ============================================================
# PLAN DETAIL / EDIT
# ============================================================

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

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✏️ نام", callback_data=f"ares:pedit:name:{plan_id}"),
        types.InlineKeyboardButton("✏️ حجم", callback_data=f"ares:pedit:volume:{plan_id}"),
        types.InlineKeyboardButton("✏️ قیمت", callback_data=f"ares:pedit:price:{plan_id}"),
    )
    kb.add(types.InlineKeyboardButton("🔁 تغییر پنل", callback_data=f"ares:pedit:panel:{plan_id}"))
    kb.add(types.InlineKeyboardButton(
        "🔴 غیرفعال کردن" if p["active"] else "🟢 فعال کردن",
        callback_data=f"ares:ptoggle:{plan_id}"
    ))
    kb.add(types.InlineKeyboardButton("🗑 حذف پلن", callback_data=f"ares:pdel_ask:{plan_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="ares:plans"))

    text = (
        f"💎 <b>{p['name']}</b>\n\n"
        f"وضعیت: {'🟢 فعال' if p['active'] else '🔴 غیرفعال'}\n"
        f"🖥 پنل: {p['panel_name'] or '---'}\n"
        f"📊 حجم: {_fmt_gb(p['volume_gb'])} GB\n"
        f"💰 قیمت: {p['price']:,} تومان\n"
        "⏳ بدون محدودیت زمانی"
    )
    render(chat_id, text, kb, message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:plan:"))
@admin_only_call
def cb_ares_plan_detail(call):
    plan_id = int(call.data.split(":")[2])
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    render_plan_detail(call.message.chat.id, plan_id, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:ptoggle:"))
@admin_only_call
def cb_ares_ptoggle(call):
    plan_id = int(call.data.split(":")[2])
    p = db_execute("SELECT active FROM reseller_plans WHERE id=?", (plan_id,), fetchone=True)
    if not p:
        bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
        return
    db_execute("UPDATE reseller_plans SET active=? WHERE id=?", (0 if p["active"] else 1, plan_id))
    render_plan_detail(call.message.chat.id, plan_id, call.message.message_id)
    bot.answer_callback_query(call.id, "✅ تغییر کرد.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:pdel_ask:"))
@admin_only_call
def cb_ares_pdel_ask(call):
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
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:pdel_go:"))
@admin_only_call
def cb_ares_pdel_go(call):
    plan_id = int(call.data.split(":")[2])
    db_execute("DELETE FROM reseller_plans WHERE id=?", (plan_id,))
    bot.answer_callback_query(call.id, "🗑 حذف شد.")
    render_plan_list(call.message.chat.id, call.message.message_id)


# ---------------- EDIT FIELDS (name/volume/price) ----------------

_FIELD_PROMPTS = {
    "name": "✏️ اسم جدید پلن رو بفرست:",
    "volume": "📊 حجم جدید رو به گیگابایت بفرست (فقط عدد):",
    "price": "💰 قیمت جدید رو به تومان بفرست (فقط عدد):",
}


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:pedit:") and c.data.split(":")[2] != "panel")
@admin_only_call
def cb_ares_pedit_start(call):
    _, _, field, plan_id = call.data.split(":")
    plan_id = int(plan_id)
    chat_id = call.message.chat.id

    render(chat_id, _FIELD_PROMPTS[field], _back_markup(f"ares:plan:{plan_id}"), call.message.message_id)
    bot.answer_callback_query(call.id)
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

    elif field == "volume":
        try:
            value = float(text.replace(",", "."))
            if value <= 0:
                raise ValueError
        except ValueError:
            render(chat_id, "❌ فقط عدد بزرگ‌تر از صفر بفرست:", _back_markup(f"ares:plan:{plan_id}"), screen_id)
            bot.register_next_step_handler_by_chat_id(chat_id, _pedit_save, field, plan_id)
            return
        db_execute("UPDATE reseller_plans SET volume_gb=? WHERE id=?", (value, plan_id))

    elif field == "price":
        if not text.isdigit() or int(text) <= 0:
            render(chat_id, "❌ فقط عدد بزرگ‌تر از صفر بفرست:", _back_markup(f"ares:plan:{plan_id}"), screen_id)
            bot.register_next_step_handler_by_chat_id(chat_id, _pedit_save, field, plan_id)
            return
        db_execute("UPDATE reseller_plans SET price=? WHERE id=?", (int(text), plan_id))

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
    plan_id = int(call.data.split(":")[3])
    kb, has_panels = _panel_pick_markup(f"ares:ppanel:{plan_id}", extra=f"ares:plan:{plan_id}")
    text = "🔁 پنل مبدا جدید رو انتخاب کن:" if has_panels else "📭 هیچ پنل فعالی نداری."
    render(call.message.chat.id, text, kb, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:ppanel:"))
@admin_only_call
def cb_ares_ppanel_set(call):
    _, _, plan_id, panel_id = call.data.split(":")
    db_execute("UPDATE reseller_plans SET panel_id=? WHERE id=?", (int(panel_id), int(plan_id)))
    bot.answer_callback_query(call.id, "✅ پنل عوض شد.")
    render_plan_detail(call.message.chat.id, int(plan_id), call.message.message_id)


# ---------------- NEW PLAN WIZARD ----------------

@bot.callback_query_handler(func=lambda c: c.data == "ares:plan_new")
@admin_only_call
def cb_ares_plan_new(call):
    chat_id = call.message.chat.id
    _state[chat_id] = {"flow": "rplan_new", "data": {}}
    render(chat_id, "✏️ اسم پلن رو بفرست (مثلاً «مولتی‌لوکیشن ۵۰۰ گیگ»):", _back_markup("ares:plans"), call.message.message_id)
    bot.answer_callback_query(call.id)
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


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:pnpanel:"))
@admin_only_call
def cb_ares_pnpanel(call):
    chat_id = call.message.chat.id
    st = _check_new_flow(chat_id)
    if not st:
        bot.answer_callback_query(call.id, "⛔ این مرحله منقضی شده.", show_alert=True)
        return
    panel_id = int(call.data.split(":")[2])
    st["data"]["panel_id"] = panel_id

    render(chat_id, "📊 حجم این پلن رو به گیگابایت بفرست (فقط عدد، مثلاً 500):", _back_markup("ares:plans"), call.message.message_id)
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler_by_chat_id(chat_id, _new_plan_volume)


def _new_plan_volume(message):
    chat_id = message.chat.id
    cc.drop(message)
    st = _check_new_flow(chat_id)
    if not st:
        return
    screen_id = cc.get_screen(chat_id, "admin_menu")
    try:
        value = float((message.text or "").strip().replace(",", "."))
        if value <= 0:
            raise ValueError
    except ValueError:
        render(chat_id, "❌ فقط عدد بزرگ‌تر از صفر بفرست:", _back_markup("ares:plans"), screen_id)
        bot.register_next_step_handler_by_chat_id(chat_id, _new_plan_volume)
        return

    st["data"]["volume_gb"] = value
    render(chat_id, "💰 قیمت این پلن رو به تومان بفرست (فقط عدد):", _back_markup("ares:plans"), screen_id)
    bot.register_next_step_handler_by_chat_id(chat_id, _new_plan_price)


def _new_plan_price(message):
    chat_id = message.chat.id
    cc.drop(message)
    st = _check_new_flow(chat_id)
    if not st:
        return
    screen_id = cc.get_screen(chat_id, "admin_menu")
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        render(chat_id, "❌ فقط عدد بزرگ‌تر از صفر بفرست:", _back_markup("ares:plans"), screen_id)
        bot.register_next_step_handler_by_chat_id(chat_id, _new_plan_price)
        return

    data = st["data"]
    db_execute("""
    INSERT INTO reseller_plans
    (name, price, capacity, duration, active, panel_id, volume_gb, created_at)
    VALUES (?, ?, 0, 0, 1, ?, ?, ?)
    """, (data["name"], int(text), data["panel_id"], data["volume_gb"], now()))

    _state.pop(chat_id, None)
    render_plan_list(chat_id, screen_id)


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
    page = int(call.data.split(":")[2])
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    render_reseller_list(call.message.chat.id, page, call.message.message_id)
    bot.answer_callback_query(call.id)


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
    _, _, reseller_user_id, back_page = call.data.split(":")
    render_reseller_detail(call.message.chat.id, int(reseller_user_id), int(back_page), call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:padj:"))
@admin_only_call
def cb_ares_padj_start(call):
    _, _, pool_id, direction = call.data.split(":")
    pool_id = int(pool_id)
    chat_id = call.message.chat.id

    _state[chat_id] = {"flow": "radj", "pool_id": pool_id, "direction": direction}

    prompt = "➕ چند گیگ اضافه بشه؟ (فقط عدد)" if direction == "add" else "➖ چند گیگ کم بشه؟ (فقط عدد)"
    render(chat_id, prompt, _back_markup(f"ares:padj_cancel:{pool_id}"), call.message.message_id)
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler_by_chat_id(chat_id, _padj_save)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ares:padj_cancel:"))
@admin_only_call
def cb_ares_padj_cancel(call):
    pool_id = int(call.data.split(":")[2])
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _state.pop(call.message.chat.id, None)
    pool = db_execute("SELECT user_id FROM reseller_panels WHERE id=?", (pool_id,), fetchone=True)
    bot.answer_callback_query(call.id)
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
