# ============================================================
# admin_broadcast.py
# ارسال پیام همگانی (با دکمه‌های سفارشی + قابلیت حذف از همه)
# + تنظیمات عضویت اجباری
#
# منطق کلی:
#   - کل مسیر هر بخش روی «یک پیام واحد» با edit_message_text پیش می‌ره.
#   - پیام‌هایی که خود ادمین برای وارد کردن مقدار می‌فرسته، بلافاصله
#     بعد از پردازش پاک میشن.
#   - زنجیره‌ی بازگشت: فقط مرحله‌ی اول (گرفتن متن پیام) دکمه‌ی
#     «بازگشت به منوی مدیریت» داره. همه‌ی مراحل بعدی فقط یک دکمه‌ی
#     «🔙 بازگشت» دارن که دقیقاً به مرحله‌ی قبل از خودشون برمی‌گردن.
#   - هر جا از یه مرحله خارج/کنسل میشیم، next_step_handler همون چت رو
#     هم پاک می‌کنیم تا هیچ‌وقت پیام بعدی (مثلاً /start) رو قورت نده.
# ============================================================

import html
import json
import logging
import os
import threading
import time
from datetime import datetime

from telebot import types

from config import bot
from database import db_execute, get_setting, set_setting
from decorators import admin_only, admin_only_call
from keyboards import admin_keyboard
from force_join import MENU_SHORTCUTS
import chat_clean as cc


# state هر ادمین: chat_id -> dict
# fj  -> تنظیمات عضویت اجباری
# bc  -> ارسال همگانی
_state = {}

# سوابق پیام‌های همگانی روی فایل ذخیره میشه (با ری‌استارت ربات هم از بین نمیره)
# هر آیتم: {"id", "ts", "text", "sent", "failed", "recipients": [[chat_id, msg_id], ...], "deleted"}
_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "broadcast_history.json")
_HISTORY_KEEP = 20
_hist_lock = threading.Lock()


def _hist_load():
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _hist_save(items):
    try:
        tmp = _HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, _HISTORY_FILE)
    except Exception as e:
        logging.warning("Broadcast history save: %s", e)


def _hist_add(text, recipients, sent, failed):
    with _hist_lock:
        items = _hist_load()
        new_id = max([i.get("id", 0) for i in items], default=0) + 1
        items.append({
            "id": new_id,
            "ts": datetime.now().strftime("%m/%d %H:%M"),
            "text": text,
            "sent": sent,
            "failed": failed,
            "recipients": [list(r) for r in recipients],
            "deleted": False,
        })
        _hist_save(items[-_HISTORY_KEEP:])
        return new_id


def _hist_get(bcid):
    for i in _hist_load():
        if i.get("id") == bcid:
            return i
    return None


def _hist_update(bcid, **fields):
    with _hist_lock:
        items = _hist_load()
        for i in items:
            if i.get("id") == bcid:
                i.update(fields)
        _hist_save(items)


def _ensure_bc_state(call):
    """اگه ربات ری‌استارت شده یا state پریده، از روی همین پیام دوباره می‌سازیم."""
    chat_id = call.message.chat.id
    st = _state.get(chat_id)
    if not st or st.get("flow") != "bc":
        st = {"flow": "bc", "text": None, "rows": [[]]}
        _state[chat_id] = st
    st["msg_id"] = call.message.message_id
    return st

_bot_username = None


def _get_bot_username():
    global _bot_username
    if _bot_username is None:
        try:
            _bot_username = bot.get_me().username or None
        except Exception:
            _bot_username = None
    return _bot_username or ""


def _safe_delete(message):
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass


def _check_state(call, flow):
    st = _state.get(call.message.chat.id)
    if not st or st.get("flow") != flow:
        bot.answer_callback_query(
            call.id,
            "⛔ این مرحله منقضی شده، دوباره از منو وارد شو.",
            show_alert=True
        )
        return False
    return True


def _fmt_duration(seconds):
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    if m:
        return f"{m} دقیقه و {s} ثانیه"
    return f"{s} ثانیه"


def _go_admin_menu(call):
    chat_id = call.message.chat.id

    bot.clear_step_handler_by_chat_id(chat_id)

    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass

    _state.pop(chat_id, None)

    cc.show(
        chat_id,
        "🏠 منوی مدیریت",
        key="admin_menu",
        reply_markup=admin_keyboard()
    )

    bot.answer_callback_query(call.id)


def _clean_before_flow(message):
    """قبل از شروع یه بخش جدید از منوی ادمین: پیام دکمه‌ی خود ادمین،
    صفحه‌ی مرحله‌ی قبلی و پیام «منوی مدیریت» رو پاک می‌کنیم."""
    chat_id = message.chat.id
    cc.drop(message)
    old = _state.pop(chat_id, None)
    if old and old.get("msg_id"):
        cc.safe_delete(chat_id, old["msg_id"])
    cc.drop_screen(chat_id, "admin_menu")


@bot.callback_query_handler(func=lambda c: c.data in ("adm_back", "bc_cancel"))
@admin_only_call
def cb_back_to_admin(call):
    _go_admin_menu(call)


# ============================================================
# FORCE JOIN SETTINGS
# ============================================================

def _fj_text():
    enabled = get_setting("force_join_enabled", "0")
    channel = get_setting("force_join_channel", "").strip()
    url = get_setting("force_join_url", "").strip()
    name = get_setting("force_join_button_text", "").strip() or "📢 عضویت در کانال"

    msg_preview = get_setting("force_join_message_text", "").strip()
    if not msg_preview:
        msg_preview = "(پیش‌فرض جذاب داخلی)"
    elif len(msg_preview) > 60:
        msg_preview = msg_preview[:60] + "…"

    return (
        "📢 <b>تنظیمات عضویت اجباری</b>\n\n"
        f"وضعیت: {'✅ فعال' if enabled == '1' else '❌ غیرفعال'}\n"
        f"آیدی کانال: <code>{channel or '---'}</code>\n"
        f"لینک کانال: {url or '---'}\n"
        f"متن دکمه: {name}\n"
        f"متن پیام به کاربر: {msg_preview}\n\n"
        "برای تغییر هرکدوم روی دکمه‌ی مربوطه بزن."
    )


def _fj_menu_markup():
    enabled = get_setting("force_join_enabled", "0")

    m = types.InlineKeyboardMarkup()
    m.row(
        types.InlineKeyboardButton(
            "🔴 غیرفعال کردن" if enabled == "1" else "🟢 فعال کردن",
            callback_data="fj_toggle"
        )
    )
    m.row(types.InlineKeyboardButton("🆔 تنظیم آیدی کانال", callback_data="fj_set_channel"))
    m.row(types.InlineKeyboardButton("🔗 تنظیم لینک کانال", callback_data="fj_set_url"))
    m.row(types.InlineKeyboardButton("✏️ تنظیم متن دکمه", callback_data="fj_set_name"))
    m.row(types.InlineKeyboardButton("📝 تنظیم متن پیام", callback_data="fj_set_message"))
    m.row(types.InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="adm_back"))
    return m


def _fj_back_markup():
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="fj_menu"))
    return m


def _fj_render(chat_id):
    st = _state.get(chat_id)
    if not st:
        return
    try:
        bot.edit_message_text(
            _fj_text(), chat_id, st["msg_id"],
            reply_markup=_fj_menu_markup(), parse_mode="HTML"
        )
    except Exception:
        pass


@bot.message_handler(func=lambda m: m.text == "📢 عضویت اجباری")
@admin_only
def admin_force_join(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    _clean_before_flow(message)
    sent = bot.send_message(
        message.chat.id, _fj_text(),
        reply_markup=_fj_menu_markup(), parse_mode="HTML"
    )
    _state[message.chat.id] = {"flow": "fj", "msg_id": sent.message_id}
    cc.track(message.chat.id, sent.message_id, "admin_menu")


@bot.callback_query_handler(func=lambda c: c.data == "fj_menu")
@admin_only_call
def cb_fj_menu(call):
    if not _check_state(call, "fj"):
        return
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _fj_render(call.message.chat.id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "fj_toggle")
@admin_only_call
def cb_fj_toggle(call):
    if not _check_state(call, "fj"):
        return

    enabled = get_setting("force_join_enabled", "0")
    channel = get_setting("force_join_channel", "").strip()

    if enabled != "1" and not channel:
        bot.answer_callback_query(call.id, "⚠️ اول آیدی کانال رو تنظیم کن.", show_alert=True)
        return

    set_setting("force_join_enabled", "0" if enabled == "1" else "1")
    _fj_render(call.message.chat.id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "fj_set_channel")
@admin_only_call
def cb_fj_set_channel(call):
    if not _check_state(call, "fj"):
        return
    chat_id = call.message.chat.id
    bot.edit_message_text(
        "🆔 آیدی عددی یا یوزرنیم کانال رو بفرست.\n"
        "مثال: <code>@mychannel</code> یا <code>-1001234567890</code>",
        chat_id, call.message.message_id,
        reply_markup=_fj_back_markup(), parse_mode="HTML"
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler_by_chat_id(chat_id, _fj_channel_received)


def _fj_channel_received(message):
    chat_id = message.chat.id
    st = _state.get(chat_id)
    _safe_delete(message)
    if not st or st.get("flow") != "fj":
        return
    set_setting("force_join_channel", message.text.strip())
    _fj_render(chat_id)


@bot.callback_query_handler(func=lambda c: c.data == "fj_set_url")
@admin_only_call
def cb_fj_set_url(call):
    if not _check_state(call, "fj"):
        return
    chat_id = call.message.chat.id
    bot.edit_message_text(
        "🔗 لینک کانال رو بفرست (باید با http شروع بشه):",
        chat_id, call.message.message_id,
        reply_markup=_fj_back_markup()
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler_by_chat_id(chat_id, _fj_url_received)


def _fj_url_received(message):
    chat_id = message.chat.id
    st = _state.get(chat_id)
    _safe_delete(message)
    if not st or st.get("flow") != "fj":
        return

    url = message.text.strip()
    if not url.startswith("http"):
        try:
            bot.edit_message_text(
                "⚠️ لینک معتبر نیست (باید با http شروع بشه). دوباره بفرست:",
                chat_id, st["msg_id"], reply_markup=_fj_back_markup()
            )
        except Exception:
            pass
        bot.register_next_step_handler_by_chat_id(chat_id, _fj_url_received)
        return

    set_setting("force_join_url", url)
    _fj_render(chat_id)


@bot.callback_query_handler(func=lambda c: c.data == "fj_set_name")
@admin_only_call
def cb_fj_set_name(call):
    if not _check_state(call, "fj"):
        return
    chat_id = call.message.chat.id
    bot.edit_message_text(
        "✏️ متن دکمه‌ی عضویت رو بفرست (همونی که کاربر می‌بینه):",
        chat_id, call.message.message_id,
        reply_markup=_fj_back_markup()
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler_by_chat_id(chat_id, _fj_name_received)


def _fj_name_received(message):
    chat_id = message.chat.id
    st = _state.get(chat_id)
    _safe_delete(message)
    if not st or st.get("flow") != "fj":
        return
    set_setting("force_join_button_text", message.text.strip())
    _fj_render(chat_id)


@bot.callback_query_handler(func=lambda c: c.data == "fj_set_message")
@admin_only_call
def cb_fj_set_message(call):
    if not _check_state(call, "fj"):
        return
    chat_id = call.message.chat.id
    bot.edit_message_text(
        "📝 متنی که به کاربرِ غیرعضو نشون داده میشه رو بفرست.\n"
        "می‌تونی از تگ‌های HTML مثل &lt;b&gt; هم استفاده کنی.\n\n"
        "برای برگشتن به متن پیش‌فرضِ جذاب، فقط بنویس: -",
        chat_id, call.message.message_id,
        reply_markup=_fj_back_markup()
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler_by_chat_id(chat_id, _fj_message_received)


def _fj_message_received(message):
    chat_id = message.chat.id
    st = _state.get(chat_id)
    _safe_delete(message)
    if not st or st.get("flow") != "fj":
        return
    text = message.text.strip()
    set_setting("force_join_message_text", "" if text == "-" else text)
    _fj_render(chat_id)


# ============================================================
# BROADCAST
#
# زنجیره‌ی مراحل:
#   1) متن پیام            -> بازگشت = منوی مدیریت
#   2) مدیریت/پیش‌نمایش    -> بازگشت = مرحله ۱ (ویرایش متن)
#   3) متن دکمه            -> بازگشت = مرحله ۲
#   4) نوع دکمه            -> بازگشت = مرحله ۳
#   5) مقدار دکمه (لینک/پارامتر) -> بازگشت = مرحله ۴
#   6) پیش‌نمایش نهایی     -> بازگشت = مرحله ۲
# ============================================================

def _bc_buttons_desc(rows):
    lines = []
    for i, row in enumerate(rows, 1):
        if not row:
            continue
        lines.append(f"ردیف {i}: " + " | ".join(b["text"] for b in row))
    return "\n".join(lines) if lines else "— (بدون دکمه)"


def _bc_users_count():
    users = db_execute("SELECT telegram_id FROM users WHERE is_blocked=0", fetchall=True)
    return len(users) if users else 0


# ---------- مرحله ۱: گرفتن متن پیام ----------

def _bc_ask_text(chat_id, message_id):
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="bc_hub"))
    try:
        bot.edit_message_text(
            "📢 <b>پیام همگانی جدید</b>\n\nمتنی که می‌خوای برای همه ارسال بشه رو بفرست:",
            chat_id, message_id, reply_markup=m, parse_mode="HTML"
        )
    except Exception:
        pass
    bot.register_next_step_handler_by_chat_id(chat_id, _bc_text_received)


def _bc_hub_markup():
    m = types.InlineKeyboardMarkup()
    m.row(types.InlineKeyboardButton("📝 نوشتن پیام جدید", callback_data="bc_new"))
    hist = _hist_load()
    if hist:
        m.row(types.InlineKeyboardButton(
            f"🗂 پیام‌های قبلی / حذف از همه ({len(hist)})", callback_data="bc_history"
        ))
    m.row(types.InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="bc_cancel"))
    return m


def _bc_render_hub(chat_id, message_id):
    try:
        bot.edit_message_text(
            "📢 <b>ارسال همگانی</b>\n\nچیکار می‌خوای بکنی؟",
            chat_id, message_id, reply_markup=_bc_hub_markup(), parse_mode="HTML"
        )
    except Exception:
        pass


@bot.message_handler(func=lambda m: m.text == "📢 ارسال همگانی")
@admin_only
def broadcast_entry(message):
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    _clean_before_flow(message)

    sent = bot.send_message(
        chat_id,
        "📢 <b>ارسال همگانی</b>\n\nچیکار می‌خوای بکنی؟",
        reply_markup=_bc_hub_markup(), parse_mode="HTML"
    )
    _state[chat_id] = {"flow": "bc", "msg_id": sent.message_id, "text": None, "rows": [[]]}
    cc.track(chat_id, sent.message_id, "admin_menu")


@bot.callback_query_handler(func=lambda c: c.data == "bc_hub")
@admin_only_call
def cb_bc_hub(call):
    _ensure_bc_state(call)
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _bc_render_hub(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "bc_new")
@admin_only_call
def cb_bc_new(call):
    st = _ensure_bc_state(call)
    chat_id = call.message.chat.id
    st["text"] = None
    st["rows"] = [[]]
    _bc_ask_text(chat_id, call.message.message_id)
    bot.answer_callback_query(call.id)


def _bc_preview_of(text, length=35):
    text = (text or "").strip().replace("\n", " ")
    return (text[:length] + "…") if len(text) > length else (text or "—")


@bot.callback_query_handler(func=lambda c: c.data == "bc_history")
@admin_only_call
def cb_bc_history(call):
    _ensure_bc_state(call)
    chat_id = call.message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)

    hist = _hist_load()
    if not hist:
        bot.answer_callback_query(call.id, "چیزی برای نمایش نیست.", show_alert=True)
        return

    m = types.InlineKeyboardMarkup()
    for rec in sorted(hist, key=lambda r: r.get("id", 0), reverse=True):
        mark = "✅" if rec.get("deleted") else "🕒"
        label = f"{mark} {rec.get('ts', '')} · {_bc_preview_of(rec.get('text'), 22)} ({rec.get('sent', 0)})"
        m.row(types.InlineKeyboardButton(label, callback_data=f"bc_hist_view:{rec['id']}"))
    m.row(types.InlineKeyboardButton("🔙 بازگشت", callback_data="bc_hub"))

    try:
        bot.edit_message_text(
            "🗂 <b>پیام‌های همگانی قبلی</b>\n\n🕒 = فعال  |  ✅ = حذف شده\nهر کدوم رو بزنی می‌تونی از همه حذفش کنی.",
            chat_id, call.message.message_id, reply_markup=m, parse_mode="HTML"
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bc_hist_view:"))
@admin_only_call
def cb_bc_hist_view(call):
    _ensure_bc_state(call)
    bcid = int(call.data.split(":", 1)[1])
    rec = _hist_get(bcid)

    if not rec:
        bot.answer_callback_query(call.id, "⛔ این پیام دیگه در دسترس نیست.", show_alert=True)
        return

    _bc_render_broadcast_item(call.message.chat.id, call.message.message_id, bcid, rec)
    bot.answer_callback_query(call.id)


def _bc_text_received(message):
    chat_id = message.chat.id
    st = _state.get(chat_id)
    _safe_delete(message)
    if not st or st.get("flow") != "bc":
        return
    st["text"] = message.text
    _bc_render_manage(chat_id)


@bot.callback_query_handler(func=lambda c: c.data == "bc_edit_text")
@admin_only_call
def cb_bc_edit_text(call):
    _ensure_bc_state(call)
    chat_id = call.message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    _bc_ask_text(chat_id, call.message.message_id)
    bot.answer_callback_query(call.id)


# ---------- مرحله ۲: مدیریت متن/دکمه‌ها ----------

def _bc_render_manage(chat_id):
    st = _state.get(chat_id)
    if not st:
        return

    count = _bc_users_count()

    text = (
        "🚀 <b>ساخت پیام همگانی</b>\n\n"
        f"{html.escape(st['text'] or '')}\n\n"
        f"🔘 دکمه‌ها:\n{_bc_buttons_desc(st['rows'])}\n\n"
        f"👥 گیرنده‌ها در حال حاضر: {count} نفر"
    )

    m = types.InlineKeyboardMarkup()
    m.row(types.InlineKeyboardButton("➕ افزودن دکمه (همین ردیف)", callback_data="bc_add"))
    if any(st["rows"]):
        m.row(types.InlineKeyboardButton("⬇️ افزودن دکمه در ردیف جدید", callback_data="bc_add_newrow"))
    m.row(types.InlineKeyboardButton("👁 پیش‌نمایش نهایی و ارسال", callback_data="bc_preview"))
    m.row(types.InlineKeyboardButton("🔙 بازگشت (ویرایش متن پیام)", callback_data="bc_edit_text"))

    try:
        bot.edit_message_text(text, chat_id, st["msg_id"], reply_markup=m, parse_mode="HTML")
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == "bc_manage")
@admin_only_call
def cb_bc_manage(call):
    if not _check_state(call, "bc"):
        return
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _bc_render_manage(call.message.chat.id)
    bot.answer_callback_query(call.id)


# ---------- مرحله ۳: متن دکمه ----------

def _bc_ask_label(chat_id, message_id):
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="bc_manage"))
    try:
        bot.edit_message_text(
            "✏️ متن دکمه رو بفرست:",
            chat_id, message_id, reply_markup=m
        )
    except Exception:
        pass
    bot.register_next_step_handler_by_chat_id(chat_id, _bc_label_received)


@bot.callback_query_handler(func=lambda c: c.data in ("bc_add", "bc_add_newrow"))
@admin_only_call
def cb_bc_add(call):
    if not _check_state(call, "bc"):
        return

    chat_id = call.message.chat.id
    st = _state[chat_id]

    if call.data == "bc_add_newrow":
        st["rows"].append([])
    elif not st["rows"]:
        st["rows"] = [[]]

    _bc_ask_label(chat_id, call.message.message_id)
    bot.answer_callback_query(call.id)


def _bc_label_received(message):
    chat_id = message.chat.id
    st = _state.get(chat_id)
    _safe_delete(message)
    if not st or st.get("flow") != "bc":
        return

    st["_tmp_label"] = message.text.strip()[:60]
    _bc_show_type_menu(chat_id, st["msg_id"])


# ---------- مرحله ۴: نوع دکمه ----------

def _bc_show_type_menu(chat_id, message_id):
    m = types.InlineKeyboardMarkup()
    m.row(types.InlineKeyboardButton("🔗 لینک", callback_data="bc_type_url"))
    m.row(types.InlineKeyboardButton("🚀 استارت ربات", callback_data="bc_type_start"))
    m.row(types.InlineKeyboardButton("🧭 میان‌بر به بخش ربات (مثلاً خرید VPN)", callback_data="bc_type_menu"))
    m.row(types.InlineKeyboardButton("✅ چک عضویت کانال", callback_data="bc_type_check"))
    m.row(types.InlineKeyboardButton("🔙 بازگشت", callback_data="bc_back_to_label"))
    try:
        bot.edit_message_text("نوع دکمه رو انتخاب کن:", chat_id, message_id, reply_markup=m)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == "bc_back_to_label")
@admin_only_call
def cb_bc_back_to_label(call):
    if not _check_state(call, "bc"):
        return
    chat_id = call.message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    _bc_ask_label(chat_id, call.message.message_id)
    bot.answer_callback_query(call.id)


# ---------- مرحله ۵: مقدار دکمه ----------

def _bc_value_back_markup():
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="bc_back_to_type"))
    return m


@bot.callback_query_handler(func=lambda c: c.data == "bc_back_to_type")
@admin_only_call
def cb_bc_back_to_type(call):
    if not _check_state(call, "bc"):
        return
    chat_id = call.message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    _bc_show_type_menu(chat_id, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "bc_type_url")
@admin_only_call
def cb_bc_type_url(call):
    if not _check_state(call, "bc"):
        return
    chat_id = call.message.chat.id
    bot.edit_message_text(
        "🔗 لینک (URL) دکمه رو بفرست:",
        chat_id, call.message.message_id,
        reply_markup=_bc_value_back_markup()
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler_by_chat_id(chat_id, _bc_url_received)


def _bc_url_received(message):
    chat_id = message.chat.id
    st = _state.get(chat_id)
    _safe_delete(message)
    if not st or st.get("flow") != "bc":
        return

    url = message.text.strip()
    if not url.startswith("http"):
        try:
            bot.edit_message_text(
                "⚠️ لینک معتبر نیست (باید با http شروع بشه). دوباره بفرست:",
                chat_id, st["msg_id"], reply_markup=_bc_value_back_markup()
            )
        except Exception:
            pass
        bot.register_next_step_handler_by_chat_id(chat_id, _bc_url_received)
        return

    st["rows"][-1].append({
        "text": st.pop("_tmp_label", "دکمه"),
        "type": "url",
        "value": url
    })
    _bc_render_manage(chat_id)


@bot.callback_query_handler(func=lambda c: c.data == "bc_type_start")
@admin_only_call
def cb_bc_type_start(call):
    if not _check_state(call, "bc"):
        return
    chat_id = call.message.chat.id
    bot.edit_message_text(
        "🚀 اگه می‌خوای دکمه با پارامتر خاص (دیپ‌لینک) باز بشه، پارامتر رو بفرست.\n"
        "اگه نمی‌خوای، فقط بنویس: -\n"
        "(بدون پارامتر، دکمه مستقیم همون /start رو تو همون چت اجرا می‌کنه)",
        chat_id, call.message.message_id,
        reply_markup=_bc_value_back_markup()
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler_by_chat_id(chat_id, _bc_start_received)


def _bc_start_received(message):
    chat_id = message.chat.id
    st = _state.get(chat_id)
    _safe_delete(message)
    if not st or st.get("flow") != "bc":
        return

    param = message.text.strip()
    param = "" if param == "-" else param

    st["rows"][-1].append({
        "text": st.pop("_tmp_label", "دکمه"),
        "type": "start",
        "value": param
    })
    _bc_render_manage(chat_id)


@bot.callback_query_handler(func=lambda c: c.data == "bc_type_menu")
@admin_only_call
def cb_bc_type_menu(call):
    if not _check_state(call, "bc"):
        return
    m = types.InlineKeyboardMarkup()
    for idx, label in enumerate(MENU_SHORTCUTS):
        m.row(types.InlineKeyboardButton(label, callback_data=f"bc_menu_pick:{idx}"))
    m.row(types.InlineKeyboardButton("🔙 بازگشت", callback_data="bc_back_to_type"))
    try:
        bot.edit_message_text(
            "🧭 کاربر با زدن این دکمه مستقیم وارد کدوم بخش بشه؟",
            call.message.chat.id, call.message.message_id, reply_markup=m
        )
    except Exception:
        pass
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bc_menu_pick:"))
@admin_only_call
def cb_bc_menu_pick(call):
    if not _check_state(call, "bc"):
        return
    chat_id = call.message.chat.id
    st = _state[chat_id]

    try:
        idx = int(call.data.split(":", 1)[1])
        MENU_SHORTCUTS[idx]
    except Exception:
        bot.answer_callback_query(call.id, "⛔ گزینه نامعتبر", show_alert=True)
        return

    st["rows"][-1].append({
        "text": st.pop("_tmp_label", "دکمه"),
        "type": "menu",
        "value": idx
    })
    _bc_render_manage(chat_id)
    bot.answer_callback_query(call.id, "✅ اضافه شد")


@bot.callback_query_handler(func=lambda c: c.data == "bc_type_check")
@admin_only_call
def cb_bc_type_check(call):
    if not _check_state(call, "bc"):
        return
    chat_id = call.message.chat.id
    st = _state[chat_id]

    st["rows"][-1].append({
        "text": st.pop("_tmp_label", "دکمه"),
        "type": "check_join",
        "value": "check_join"
    })
    _bc_render_manage(chat_id)
    bot.answer_callback_query(call.id, "✅ اضافه شد")


def _bc_build_user_markup(rows):
    rows = [r for r in rows if r]
    if not rows:
        return None

    username = _get_bot_username()
    m = types.InlineKeyboardMarkup()

    for row in rows:
        btns = []
        for b in row:
            if b["type"] == "url":
                btns.append(types.InlineKeyboardButton(b["text"], url=b["value"]))
            elif b["type"] == "start":
                if b["value"] and username:
                    # دیپ‌لینک با پارامتر: ربات با /start <param> باز میشه
                    url = f"https://t.me/{username}?start={b['value']}"
                    btns.append(types.InlineKeyboardButton(b["text"], url=url))
                else:
                    # بدون پارامتر: همون /start رو مستقیم تو همون چت اجرا می‌کنه
                    btns.append(types.InlineKeyboardButton(b["text"], callback_data="go_start"))
            elif b["type"] == "menu":
                btns.append(types.InlineKeyboardButton(b["text"], callback_data=f"go_menu:{b['value']}"))
            elif b["type"] == "check_join":
                btns.append(types.InlineKeyboardButton(b["text"], callback_data="check_join"))
        if btns:
            m.row(*btns)

    return m


# ---------- مرحله ۶: پیش‌نمایش نهایی ----------

@bot.callback_query_handler(func=lambda c: c.data == "bc_preview")
@admin_only_call
def cb_bc_preview(call):
    if not _check_state(call, "bc"):
        return
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _bc_render_preview(call.message.chat.id)
    bot.answer_callback_query(call.id)


def _bc_render_preview(chat_id):
    st = _state.get(chat_id)
    if not st:
        return

    user_markup = _bc_build_user_markup(st["rows"])

    confirm = types.InlineKeyboardMarkup()
    if user_markup:
        for row in user_markup.keyboard:
            confirm.row(*row)

    confirm.row(types.InlineKeyboardButton("✅ تایید و ارسال برای همه", callback_data="bc_confirm"))
    confirm.row(types.InlineKeyboardButton("🔙 بازگشت", callback_data="bc_manage"))

    count = _bc_users_count()
    eta = _fmt_duration(count * 0.04)

    text = (
        "👁 <b>پیش‌نمایش نهایی</b>\n\n"
        f"{html.escape(st['text'] or '')}\n\n"
        f"👥 گیرنده‌ها: {count} نفر\n"
        f"⏱ زمان تقریبی ارسال: {eta}\n\n"
        "این دقیقاً همون چیزیه که کاربرا می‌بینن. ارسال بشه؟"
    )

    try:
        bot.edit_message_text(text, chat_id, st["msg_id"], reply_markup=confirm, parse_mode="HTML")
    except Exception:
        pass


def _bc_render_broadcast_item(chat_id, message_id, bcid, rec, just_sent=False):
    remaining = len(rec.get("recipients") or [])
    deleted = rec.get("deleted")

    m = types.InlineKeyboardMarkup()
    if remaining and not deleted:
        m.row(types.InlineKeyboardButton("🗑 حذف این پیام از همه", callback_data=f"bc_del_ask:{bcid}"))
    if just_sent:
        m.row(types.InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="bc_cancel"))
    else:
        m.row(types.InlineKeyboardButton("🔙 بازگشت", callback_data="bc_history"))

    title = "✅ <b>ارسال انجام شد</b>" if just_sent else f"📨 <b>پیام همگانی #{bcid}</b>"
    status = "✅ از همه حذف شده" if deleted else f"🕒 فعال | قابل حذف برای {remaining} نفر"

    try:
        bot.edit_message_text(
            f"{title}\n\n"
            f"{html.escape(rec.get('text') or '')}\n\n"
            f"📅 {rec.get('ts', '')}\n"
            f"موفق: {rec.get('sent', 0)} | ناموفق: {rec.get('failed', 0)}\n"
            f"{status}",
            chat_id, message_id, reply_markup=m, parse_mode="HTML"
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == "bc_confirm")
@admin_only_call
def cb_bc_confirm(call):
    if not _check_state(call, "bc"):
        return

    chat_id = call.message.chat.id
    st = _state[chat_id]
    bot.answer_callback_query(call.id, "⏳ در حال ارسال...")

    users = db_execute("SELECT telegram_id FROM users WHERE is_blocked=0", fetchall=True)
    user_markup = _bc_build_user_markup(st["rows"])

    sent = 0
    failed = 0
    recipients = []

    for user in users:
        try:
            msg = bot.send_message(user["telegram_id"], st["text"], reply_markup=user_markup)
            recipients.append((user["telegram_id"], msg.message_id))
            sent += 1
            time.sleep(0.04)
        except Exception:
            failed += 1

    bcid = _hist_add(st["text"], recipients, sent, failed)
    _bc_render_broadcast_item(chat_id, st["msg_id"], bcid, _hist_get(bcid), just_sent=True)

    st["text"] = None
    st["rows"] = [[]]
    bot.clear_step_handler_by_chat_id(chat_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bc_del_ask:"))
@admin_only_call
def cb_bc_del_ask(call):
    bcid = int(call.data.split(":", 1)[1])
    rec = _hist_get(bcid)

    if not rec or rec.get("deleted") or not rec.get("recipients"):
        bot.answer_callback_query(call.id, "⛔ این پیام قبلاً حذف شده یا در دسترس نیست.", show_alert=True)
        return

    m = types.InlineKeyboardMarkup()
    m.row(
        types.InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"bc_del_go:{bcid}"),
        types.InlineKeyboardButton("❌ نه", callback_data=f"bc_del_no:{bcid}")
    )

    try:
        bot.edit_message_text(
            f"⚠️ مطمئنی می‌خوای این پیام رو از چت {len(rec['recipients'])} نفری که "
            "براشون رفته حذف کنی؟\n\nاین عمل قابل بازگشت نیست.\n"
            "(تلگرام فقط تا حدود ۴۸ ساعت بعد از ارسال اجازه‌ی حذف میده)",
            call.message.chat.id, call.message.message_id, reply_markup=m
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bc_del_no:"))
@admin_only_call
def cb_bc_del_no(call):
    bcid = int(call.data.split(":", 1)[1])
    rec = _hist_get(bcid)

    if not rec:
        bot.answer_callback_query(call.id, "⛔ این پیام دیگه در دسترس نیست.", show_alert=True)
        return

    _bc_render_broadcast_item(call.message.chat.id, call.message.message_id, bcid, rec)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bc_del_go:"))
@admin_only_call
def cb_bc_del_go(call):
    bcid = int(call.data.split(":", 1)[1])
    rec = _hist_get(bcid)
    chat_id = call.message.chat.id

    if not rec or rec.get("deleted") or not rec.get("recipients"):
        bot.answer_callback_query(call.id, "⛔ این پیام دیگه در دسترس نیست.", show_alert=True)
        return

    bot.answer_callback_query(call.id, "⏳ در حال حذف...")

    deleted = 0
    left = []

    for uid, mid in rec["recipients"]:
        try:
            bot.delete_message(uid, mid)
            deleted += 1
            time.sleep(0.03)
        except Exception:
            left.append([uid, mid])

    # اونایی که حذف نشدن نگه داشته میشن تا بشه دوباره تلاش کرد
    _hist_update(bcid, recipients=left, deleted=(not left))

    m = types.InlineKeyboardMarkup()
    if left:
        m.row(types.InlineKeyboardButton("🔁 تلاش دوباره برای باقی‌مونده‌ها", callback_data=f"bc_del_ask:{bcid}"))
    m.row(types.InlineKeyboardButton("🔙 بازگشت به فهرست", callback_data="bc_history"))

    try:
        bot.edit_message_text(
            f"🗑 <b>حذف انجام شد</b>\n\nحذف‌شده: {deleted}\nحذف‌نشده: {len(left)}\n\n"
            "حذف‌نشده‌ها معمولاً کسایی‌ان که ربات رو بلاک کردن یا از ارسال بیشتر از ۴۸ ساعت گذشته.",
            chat_id, call.message.message_id, reply_markup=m, parse_mode="HTML"
        )
    except Exception:
        pass
