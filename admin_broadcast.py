# ============================================================
# admin_broadcast.py
# ارسال پیام همگانی (با دکمه‌های سفارشی) + تنظیمات عضویت اجباری
#
# منطق کلی:
#   - کل مسیر هر بخش روی «یک پیام واحد» با edit_message_text پیش می‌ره،
#     یعنی هیچ پیام جدیدی برای مراحل ساخته نمیشه و صفحه شلوغ نمیشه.
#   - پیام‌هایی که خود ادمین برای وارد کردن مقدار (متن/آیدی/لینک و ...)
#     می‌فرسته، بلافاصله بعد از پردازش پاک میشن.
#   - فقط وقتی که با «بازگشت به منوی مدیریت» خارج میشیم، پیام مرحله
#     پاک شده و منوی ری‌پلای مدیریت (که یه کیبورد متفاوته) فرستاده میشه.
# ============================================================

import time

from telebot import types

from config import bot
from database import db_execute, get_setting, set_setting
from decorators import admin_only, admin_only_call
from keyboards import admin_keyboard


# state هر ادمین: chat_id -> dict
# fj  -> تنظیمات عضویت اجباری
# bc  -> ارسال همگانی
_state = {}

_bot_username = None


def _get_bot_username():
    global _bot_username
    if _bot_username is None:
        try:
            _bot_username = bot.get_me().username
        except Exception:
            _bot_username = ""
    return _bot_username


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


def _go_admin_menu(call):
    chat_id = call.message.chat.id

    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass

    _state.pop(chat_id, None)

    bot.send_message(
        chat_id,
        "🏠 منوی مدیریت",
        reply_markup=admin_keyboard()
    )

    bot.answer_callback_query(call.id)


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

    return (
        "📢 <b>تنظیمات عضویت اجباری</b>\n\n"
        f"وضعیت: {'✅ فعال' if enabled == '1' else '❌ غیرفعال'}\n"
        f"آیدی کانال: <code>{channel or '---'}</code>\n"
        f"لینک کانال: {url or '---'}\n"
        f"متن دکمه: {name}\n\n"
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
    sent = bot.send_message(
        message.chat.id, _fj_text(),
        reply_markup=_fj_menu_markup(), parse_mode="HTML"
    )
    _state[message.chat.id] = {"flow": "fj", "msg_id": sent.message_id}


@bot.callback_query_handler(func=lambda c: c.data == "fj_menu")
@admin_only_call
def cb_fj_menu(call):
    if not _check_state(call, "fj"):
        return
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


# ============================================================
# BROADCAST
# ============================================================

def _bc_buttons_desc(rows):
    lines = []
    for i, row in enumerate(rows, 1):
        if not row:
            continue
        lines.append(f"ردیف {i}: " + " | ".join(b["text"] for b in row))
    return "\n".join(lines) if lines else "— (بدون دکمه)"


def _bc_back_to_manage_markup():
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="bc_manage"))
    return m


def _bc_render_manage(chat_id):
    st = _state.get(chat_id)
    if not st:
        return

    text = (
        "📢 <b>ارسال پیام همگانی</b>\n\n"
        f"{st['text']}\n\n"
        f"دکمه‌ها:\n{_bc_buttons_desc(st['rows'])}"
    )

    m = types.InlineKeyboardMarkup()
    m.row(types.InlineKeyboardButton("➕ افزودن دکمه (همین ردیف)", callback_data="bc_add"))
    if any(st["rows"]):
        m.row(types.InlineKeyboardButton("⬇️ افزودن دکمه در ردیف جدید", callback_data="bc_add_newrow"))
    m.row(types.InlineKeyboardButton("👁 پیش‌نمایش نهایی و ارسال", callback_data="bc_preview"))
    m.row(types.InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="bc_cancel"))

    try:
        bot.edit_message_text(text, chat_id, st["msg_id"], reply_markup=m, parse_mode="HTML")
    except Exception:
        pass


@bot.message_handler(func=lambda m: m.text == "📢 ارسال همگانی")
@admin_only
def broadcast_entry(message):
    chat_id = message.chat.id
    sent = bot.send_message(
        chat_id, "📢 متن پیام همگانی رو بفرست:",
        reply_markup=_bc_cancel_markup()
    )
    _state[chat_id] = {"flow": "bc", "msg_id": sent.message_id, "text": None, "rows": [[]]}
    bot.register_next_step_handler_by_chat_id(chat_id, _bc_text_received)


def _bc_cancel_markup():
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="bc_cancel"))
    return m


def _bc_text_received(message):
    chat_id = message.chat.id
    st = _state.get(chat_id)
    _safe_delete(message)
    if not st or st.get("flow") != "bc":
        return
    st["text"] = message.text
    _bc_render_manage(chat_id)


@bot.callback_query_handler(func=lambda c: c.data == "bc_manage")
@admin_only_call
def cb_bc_manage(call):
    if not _check_state(call, "bc"):
        return
    _bc_render_manage(call.message.chat.id)
    bot.answer_callback_query(call.id)


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

    bot.edit_message_text(
        "✏️ متن دکمه رو بفرست:",
        chat_id, call.message.message_id,
        reply_markup=_bc_back_to_manage_markup()
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler_by_chat_id(chat_id, _bc_label_received)


def _bc_label_received(message):
    chat_id = message.chat.id
    st = _state.get(chat_id)
    _safe_delete(message)
    if not st or st.get("flow") != "bc":
        return

    st["_tmp_label"] = message.text.strip()[:60]

    m = types.InlineKeyboardMarkup()
    m.row(types.InlineKeyboardButton("🔗 لینک", callback_data="bc_type_url"))
    m.row(types.InlineKeyboardButton("🚀 استارت ربات", callback_data="bc_type_start"))
    m.row(types.InlineKeyboardButton("✅ چک عضویت کانال", callback_data="bc_type_check"))
    m.row(types.InlineKeyboardButton("🔙 بازگشت", callback_data="bc_manage"))

    try:
        bot.edit_message_text("نوع دکمه رو انتخاب کن:", chat_id, st["msg_id"], reply_markup=m)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == "bc_type_url")
@admin_only_call
def cb_bc_type_url(call):
    if not _check_state(call, "bc"):
        return
    chat_id = call.message.chat.id
    bot.edit_message_text(
        "🔗 لینک (URL) دکمه رو بفرست:",
        chat_id, call.message.message_id,
        reply_markup=_bc_back_to_manage_markup()
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
                chat_id, st["msg_id"], reply_markup=_bc_back_to_manage_markup()
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
        "🚀 پارامتر start رو بفرست.\n"
        "اگه نمی‌خوای پارامتر خاصی بذاری، فقط بنویس: -",
        chat_id, call.message.message_id,
        reply_markup=_bc_back_to_manage_markup()
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
                if b["value"]:
                    url = f"https://t.me/{username}?start={b['value']}"
                else:
                    url = f"https://t.me/{username}"
                btns.append(types.InlineKeyboardButton(b["text"], url=url))
            elif b["type"] == "check_join":
                btns.append(types.InlineKeyboardButton(b["text"], callback_data="check_join"))
        if btns:
            m.row(*btns)

    return m


@bot.callback_query_handler(func=lambda c: c.data == "bc_preview")
@admin_only_call
def cb_bc_preview(call):
    if not _check_state(call, "bc"):
        return
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
    confirm.row(types.InlineKeyboardButton("✏️ ویرایش دکمه‌ها", callback_data="bc_manage"))
    confirm.row(types.InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="bc_cancel"))

    text = (
        "👁 <b>پیش‌نمایش نهایی</b>\n\n"
        f"{st['text']}\n\n"
        "این دقیقاً همون چیزیه که کاربرا می‌بینن. ارسال بشه؟"
    )

    try:
        bot.edit_message_text(text, chat_id, st["msg_id"], reply_markup=confirm, parse_mode="HTML")
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

    for user in users:
        try:
            bot.send_message(user["telegram_id"], st["text"], reply_markup=user_markup)
            sent += 1
            time.sleep(0.04)
        except Exception:
            failed += 1

    result_markup = types.InlineKeyboardMarkup()
    result_markup.add(types.InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="bc_cancel"))

    try:
        bot.edit_message_text(
            f"✅ ارسال انجام شد.\nموفق: {sent}\nناموفق: {failed}",
            chat_id, st["msg_id"], reply_markup=result_markup
        )
    except Exception:
        pass

    st["text"] = None
    st["rows"] = [[]]
