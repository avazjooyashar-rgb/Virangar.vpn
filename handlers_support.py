# ============================================================
# handlers_support.py
# پشتیبانی و تیکت‌های کاربر + پنل مدیریت کامل پشتیبانی برای ادمین
# ============================================================

import html

from telebot import types

from config import bot, SUPER_ADMIN_ID
from database import db_execute, get_setting, now
from models import get_user, is_admin, internal_user_id


def is_support_staff(tg_id):
    """
    هم ادمین‌های ثبت‌شده در جدول admins، هم SUPER_ADMIN_ID
    (که ممکن است در آن جدول ثبت نشده باشد) دسترسی مدیریت
    پشتیبانی دارند.
    """
    if SUPER_ADMIN_ID and str(tg_id) == str(SUPER_ADMIN_ID):
        return True
    return is_admin(tg_id)


STATUS_LABELS = {
    "open": "🟢 باز (منتظر پاسخ)",
    "answered": "💬 پاسخ داده‌شده",
    "closed": "🔒 بسته‌شده",
}

PAGE_SIZE = 15


def esc(text):
    return html.escape(text or "")


def get_owner_telegram_id(internal_id):
    row = db_execute("SELECT telegram_id FROM users WHERE id=?", (internal_id,), fetchone=True)
    return row["telegram_id"] if row else None


def get_ticket(ticket_id):
    return db_execute("SELECT * FROM tickets WHERE id=?", (ticket_id,), fetchone=True)


def get_ticket_messages(ticket_id):
    return db_execute("""
    SELECT * FROM ticket_messages
    WHERE ticket_id=?
    ORDER BY id ASC
    """, (ticket_id,), fetchall=True) or []


def touch_ticket(ticket_id, status=None):
    if status:
        db_execute("UPDATE tickets SET status=?, updated_at=? WHERE id=?", (status, now(), ticket_id))
    else:
        db_execute("UPDATE tickets SET updated_at=? WHERE id=?", (now(), ticket_id))


def add_message(ticket_id, sender_telegram_id, text):
    db_execute("""
    INSERT INTO ticket_messages
    (ticket_id, sender_id, message, created_at)
    VALUES (?, ?, ?, ?)
    """, (ticket_id, sender_telegram_id, text or "", now()))


def safe_edit(chat_id, message_id, text, kb):
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
        return True
    except Exception:
        return False


def render(chat_id, text, kb, message_id=None):
    if message_id and safe_edit(chat_id, message_id, text, kb):
        return
    bot.send_message(chat_id, text, reply_markup=kb)


# ============================================================
# ============  USER SIDE  ===================================
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🆘 پشتیبانی" and not is_support_staff(m.from_user.id))
def user_support_entry(message):
    render_user_menu(message.chat.id)


def render_user_menu(chat_id, message_id=None):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎫 تیکت جدید", callback_data="sup:new"))
    kb.add(types.InlineKeyboardButton("📂 تیکت‌های من", callback_data="sup:mine"))

    support_username = get_setting("support_username", "").strip()
    if support_username:
        username = support_username[1:] if support_username.startswith("@") else support_username
        kb.add(types.InlineKeyboardButton("👨‍💻 ارتباط مستقیم", url=f"https://t.me/{username}"))

    render(
        chat_id,
        "🆘 <b>مرکز پشتیبانی</b>\n\n"
        "برای ارتباط با پشتیبانی تیکت ایجاد کن یا تیکت‌های قبلیت رو ببین.",
        kb,
        message_id
    )


@bot.callback_query_handler(func=lambda call: call.data == "sup:menu")
def sup_menu_cb(call):
    bot.answer_callback_query(call.id)
    render_user_menu(call.message.chat.id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "sup:new")
def sup_new(call):
    bot.answer_callback_query(call.id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="sup:cancel_new"))

    try:
        bot.edit_message_text(
            "🎫 <b>تیکت جدید</b>\n\nموضوع یا متن مشکل خودت رو بنویس و بفرست:",
            call.message.chat.id, call.message.message_id, reply_markup=kb
        )
    except Exception:
        bot.send_message(call.message.chat.id, "🎫 موضوع یا متن مشکل خودت رو بنویس و بفرست:", reply_markup=kb)

    bot.register_next_step_handler(call.message, create_ticket)


@bot.callback_query_handler(func=lambda call: call.data == "sup:cancel_new")
def sup_cancel_new(call):
    bot.answer_callback_query(call.id)
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    render_user_menu(call.message.chat.id, call.message.message_id)


def create_ticket(message):
    if not (message.text or "").strip():
        msg = bot.send_message(message.chat.id, "❌ متن خالیه. یه توضیح برای مشکلت بفرست:")
        bot.register_next_step_handler(msg, create_ticket)
        return

    user_id = internal_user_id(message.from_user.id)

    db_execute("""
    INSERT INTO tickets
    (user_id, subject, status, created_at, updated_at)
    VALUES (?, ?, 'open', ?, ?)
    """, (user_id, message.text[:60], now(), now()))

    ticket = db_execute("""
    SELECT * FROM tickets
    WHERE user_id=?
    ORDER BY id DESC LIMIT 1
    """, (user_id,), fetchone=True)

    add_message(ticket["id"], message.from_user.id, message.text)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به پشتیبانی", callback_data="sup:menu"))

    bot.send_message(
        message.chat.id,
        f"✅ تیکت <b>#{ticket['id']}</b> ثبت شد.\n\n"
        "پشتیبانی به‌زودی پاسخ می‌ده. جواب همینجا برات ارسال میشه.",
        reply_markup=kb
    )

    if SUPER_ADMIN_ID:
        akb = types.InlineKeyboardMarkup()
        akb.row(
            types.InlineKeyboardButton("✍️ پاسخ", callback_data=f"asup:reply:{ticket['id']}"),
            types.InlineKeyboardButton("📂 مشاهده", callback_data=f"asup:view:{ticket['id']}"),
        )
        bot.send_message(
            SUPER_ADMIN_ID,
            f"🎫 <b>تیکت جدید #{ticket['id']}</b>\n\n"
            f"👤 Telegram ID: <code>{message.from_user.id}</code>\n"
            f"📝 {esc(message.text)}",
            reply_markup=akb
        )


@bot.callback_query_handler(func=lambda call: call.data == "sup:mine")
def sup_mine(call):
    bot.answer_callback_query(call.id)
    render_user_ticket_list(call.from_user.id, call.message.chat.id, call.message.message_id)


def render_user_ticket_list(from_telegram_id, chat_id, message_id=None):
    user_id = internal_user_id(from_telegram_id)

    tickets = db_execute("""
    SELECT * FROM tickets
    WHERE user_id=?
    ORDER BY id DESC
    LIMIT 20
    """, (user_id,), fetchall=True)

    kb = types.InlineKeyboardMarkup()

    if not tickets:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="sup:menu"))
        render(chat_id, "📭 هنوز تیکتی ثبت نکردی.", kb, message_id)
        return

    for t in tickets:
        label = f"#{t['id']} · {t['subject'][:25]} · {STATUS_LABELS.get(t['status'], t['status'])}"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"sup:view:{t['id']}"))

    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="sup:menu"))

    render(chat_id, "📂 <b>تیکت‌های من</b>\n\nروی هرکدوم بزن تا مکالمه رو ببینی:", kb, message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("sup:view:"))
def sup_view(call):
    ticket_id = int(call.data.split(":")[2])
    ticket = get_ticket(ticket_id)

    if not ticket:
        bot.answer_callback_query(call.id, "❌ تیکت پیدا نشد.", show_alert=True)
        return

    owner_id = internal_user_id(call.from_user.id)
    if ticket["user_id"] != owner_id:
        bot.answer_callback_query(call.id, "❌ این تیکت متعلق به شما نیست.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    render_user_ticket_view(ticket_id, call.message.chat.id, call.message.message_id)


def render_user_ticket_view(ticket_id, chat_id, message_id=None):
    ticket = get_ticket(ticket_id)
    if not ticket:
        return

    owner_tg_id = get_owner_telegram_id(ticket["user_id"])
    messages = get_ticket_messages(ticket_id)

    lines = [
        f"🎫 <b>تیکت #{ticket['id']}</b> — {STATUS_LABELS.get(ticket['status'], ticket['status'])}\n"
    ]

    for m in messages[-15:]:
        sender = "👤 شما" if str(m["sender_id"]) == str(owner_tg_id) else "👨‍💻 پشتیبانی"
        lines.append(f"{sender}:\n{esc(m['message'])}\n")

    kb = types.InlineKeyboardMarkup()

    if ticket["status"] != "closed":
        kb.add(types.InlineKeyboardButton("✍️ ارسال پیام جدید", callback_data=f"sup:reply:{ticket_id}"))
    else:
        kb.add(types.InlineKeyboardButton("🔒 این تیکت بسته شده — تیکت جدید بزن", callback_data="sup:new"))

    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="sup:mine"))

    render(chat_id, "\n".join(lines), kb, message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("sup:reply:"))
def sup_reply_start(call):
    ticket_id = int(call.data.split(":")[2])
    ticket = get_ticket(ticket_id)

    if not ticket or ticket["status"] == "closed":
        bot.answer_callback_query(call.id, "❌ این تیکت دیگه باز نیست.", show_alert=True)
        return

    bot.answer_callback_query(call.id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"sup:view:{ticket_id}"))

    try:
        bot.edit_message_text(
            f"✍️ پیامت رو برای تیکت #{ticket_id} بفرست:",
            call.message.chat.id, call.message.message_id, reply_markup=kb
        )
    except Exception:
        bot.send_message(call.message.chat.id, f"✍️ پیامت رو برای تیکت #{ticket_id} بفرست:", reply_markup=kb)

    bot.register_next_step_handler(call.message, user_reply_save, ticket_id)


def user_reply_save(message, ticket_id):
    if not (message.text or "").strip():
        msg = bot.send_message(message.chat.id, "❌ متن خالیه. دوباره بفرست:")
        bot.register_next_step_handler(msg, user_reply_save, ticket_id)
        return

    ticket = get_ticket(ticket_id)
    if not ticket:
        bot.send_message(message.chat.id, "❌ این تیکت دیگه وجود نداره.")
        return

    add_message(ticket_id, message.from_user.id, message.text)
    touch_ticket(ticket_id, status="open")  # منتظر پاسخ پشتیبانی

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به تیکت", callback_data=f"sup:view:{ticket_id}"))
    bot.send_message(message.chat.id, "✅ پیامت ارسال شد.", reply_markup=kb)

    if SUPER_ADMIN_ID:
        akb = types.InlineKeyboardMarkup()
        akb.row(
            types.InlineKeyboardButton("✍️ پاسخ", callback_data=f"asup:reply:{ticket_id}"),
            types.InlineKeyboardButton("📂 مشاهده", callback_data=f"asup:view:{ticket_id}"),
        )
        bot.send_message(
            SUPER_ADMIN_ID,
            f"💬 <b>پیام جدید در تیکت #{ticket_id}</b>\n\n"
            f"👤 Telegram ID: <code>{message.from_user.id}</code>\n"
            f"📝 {esc(message.text)}",
            reply_markup=akb
        )


# ============================================================
# ============  ADMIN SIDE  ===================================
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🆘 پشتیبانی" and is_support_staff(m.from_user.id))
def admin_support_entry(message):
    render_admin_menu(message.chat.id)


def render_admin_menu(chat_id, message_id=None):
    open_count = db_execute(
        "SELECT COUNT(*) c FROM tickets WHERE status IN ('open')", fetchone=True
    )["c"]

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"📥 تیکت‌های باز ({open_count})", callback_data="asup:list:open"))
    kb.add(types.InlineKeyboardButton("📁 همه تیکت‌ها", callback_data="asup:list:all"))

    render(chat_id, "🛠 <b>مدیریت پشتیبانی</b>\n\nیکی از گزینه‌ها رو انتخاب کن:", kb, message_id)


@bot.callback_query_handler(func=lambda call: call.data == "asup:menu")
def asup_menu_cb(call):
    if not is_support_staff(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    render_admin_menu(call.message.chat.id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("asup:list:"))
def asup_list(call):
    if not is_support_staff(call.from_user.id):
        return

    scope = call.data.split(":")[2]
    bot.answer_callback_query(call.id)
    render_admin_ticket_list(scope, call.message.chat.id, call.message.message_id)


def render_admin_ticket_list(scope, chat_id, message_id=None):
    if scope == "open":
        tickets = db_execute("""
        SELECT * FROM tickets WHERE status IN ('open') ORDER BY id DESC LIMIT ?
        """, (PAGE_SIZE,), fetchall=True)
        title = "📥 <b>تیکت‌های باز</b>"
    else:
        tickets = db_execute("""
        SELECT * FROM tickets ORDER BY id DESC LIMIT ?
        """, (PAGE_SIZE,), fetchall=True)
        title = "📁 <b>همه تیکت‌ها (۱۵ مورد آخر)</b>"

    kb = types.InlineKeyboardMarkup()

    if not tickets:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="asup:menu"))
        render(chat_id, f"{title}\n\n📭 موردی پیدا نشد.", kb, message_id)
        return

    for t in tickets:
        label = f"#{t['id']} · {t['subject'][:25]} · {STATUS_LABELS.get(t['status'], t['status'])}"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"asup:view:{t['id']}"))

    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="asup:menu"))

    render(chat_id, title, kb, message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("asup:view:"))
def asup_view(call):
    if not is_support_staff(call.from_user.id):
        return

    ticket_id = int(call.data.split(":")[2])
    bot.answer_callback_query(call.id)
    render_admin_ticket_view(ticket_id, call.message.chat.id, call.message.message_id)


def render_admin_ticket_view(ticket_id, chat_id, message_id=None):
    ticket = get_ticket(ticket_id)
    if not ticket:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="asup:menu"))
        render(chat_id, "❌ تیکت پیدا نشد.", kb, message_id)
        return

    owner_tg_id = get_owner_telegram_id(ticket["user_id"])
    messages = get_ticket_messages(ticket_id)

    lines = [
        f"🎫 <b>تیکت #{ticket['id']}</b> — {STATUS_LABELS.get(ticket['status'], ticket['status'])}\n"
        f"👤 Telegram ID: <code>{owner_tg_id}</code>\n"
    ]

    for m in messages[-15:]:
        sender = "👤 کاربر" if str(m["sender_id"]) == str(owner_tg_id) else "👨‍💻 شما"
        lines.append(f"{sender}:\n{esc(m['message'])}\n")

    kb = types.InlineKeyboardMarkup()

    if ticket["status"] != "closed":
        kb.row(
            types.InlineKeyboardButton("✍️ پاسخ", callback_data=f"asup:reply:{ticket_id}"),
            types.InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"asup:close:{ticket_id}"),
        )
    else:
        kb.add(types.InlineKeyboardButton("🔓 بازگشایی تیکت", callback_data=f"asup:reopen:{ticket_id}"))

    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="asup:list:open"))

    render(chat_id, "\n".join(lines), kb, message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("asup:reply:"))
def asup_reply_start(call):
    if not is_support_staff(call.from_user.id):
        return

    ticket_id = int(call.data.split(":")[2])
    ticket = get_ticket(ticket_id)

    if not ticket:
        bot.answer_callback_query(call.id, "❌ تیکت پیدا نشد.", show_alert=True)
        return

    if ticket["status"] == "closed":
        bot.answer_callback_query(call.id, "❌ این تیکت بسته شده. اول بازش کن.", show_alert=True)
        return

    bot.answer_callback_query(call.id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"asup:view:{ticket_id}"))

    try:
        bot.edit_message_text(
            f"✍️ پاسخت رو برای تیکت #{ticket_id} بنویس و بفرست:",
            call.message.chat.id, call.message.message_id, reply_markup=kb
        )
    except Exception:
        bot.send_message(call.message.chat.id, f"✍️ پاسخت رو برای تیکت #{ticket_id} بنویس و بفرست:", reply_markup=kb)

    bot.register_next_step_handler(call.message, admin_reply_save, ticket_id)


def admin_reply_save(message, ticket_id):
    if not (message.text or "").strip():
        msg = bot.send_message(message.chat.id, "❌ متن خالیه. دوباره بفرست:")
        bot.register_next_step_handler(msg, admin_reply_save, ticket_id)
        return

    ticket = get_ticket(ticket_id)
    if not ticket:
        bot.send_message(message.chat.id, "❌ این تیکت دیگه وجود نداره.")
        return

    add_message(ticket_id, message.from_user.id, message.text)
    touch_ticket(ticket_id, status="answered")

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به تیکت", callback_data=f"asup:view:{ticket_id}"))
    bot.send_message(message.chat.id, "✅ پاسخ ارسال شد.", reply_markup=kb)

    owner_tg_id = get_owner_telegram_id(ticket["user_id"])
    if owner_tg_id:
        ukb = types.InlineKeyboardMarkup()
        ukb.add(types.InlineKeyboardButton("📂 مشاهده تیکت", callback_data=f"sup:view:{ticket_id}"))
        try:
            bot.send_message(
                owner_tg_id,
                f"💬 <b>پاسخ جدید برای تیکت #{ticket_id}</b>\n\n{esc(message.text)}",
                reply_markup=ukb
            )
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("asup:close:"))
def asup_close(call):
    if not is_support_staff(call.from_user.id):
        return

    ticket_id = int(call.data.split(":")[2])
    touch_ticket(ticket_id, status="closed")

    bot.answer_callback_query(call.id, "🔒 تیکت بسته شد.")
    render_admin_ticket_view(ticket_id, call.message.chat.id, call.message.message_id)

    ticket = get_ticket(ticket_id)
    owner_tg_id = get_owner_telegram_id(ticket["user_id"]) if ticket else None
    if owner_tg_id:
        try:
            bot.send_message(owner_tg_id, f"🔒 تیکت #{ticket_id} توسط پشتیبانی بسته شد.")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("asup:reopen:"))
def asup_reopen(call):
    if not is_support_staff(call.from_user.id):
        return

    ticket_id = int(call.data.split(":")[2])
    touch_ticket(ticket_id, status="open")

    bot.answer_callback_query(call.id, "🔓 تیکت بازگشایی شد.")
    render_admin_ticket_view(ticket_id, call.message.chat.id, call.message.message_id)
