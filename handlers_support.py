# ============================================================
# handlers_support.py
# پشتیبانی و تیکت‌های کاربر + پنل مدیریت کامل پشتیبانی برای ادمین
# ============================================================

import html
from datetime import datetime

from telebot import types

from config import bot, SUPER_ADMIN_ID
from database import db_execute, get_setting, now
from models import get_user, is_admin, internal_user_id
from keyboards import user_keyboard, admin_keyboard


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


def relative_time(dt_str):
    """تبدیل تاریخ ذخیره‌شده به زمان نسبی مثل '۲ ساعت پیش'."""
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return dt_str or "-"
    diff = datetime.utcnow() - dt
    seconds = diff.total_seconds()
    if seconds < 60:
        return "چند لحظه پیش"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} دقیقه پیش"
    hours = int(seconds // 3600)
    if hours < 24:
        return f"{hours} ساعت پیش"
    days = int(seconds // 86400)
    if days == 1:
        return "دیروز"
    if days < 7:
        return f"{days} روز پیش"
    return dt.strftime("%Y-%m-%d")


def hours_since(dt_str):
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return 0
    return (datetime.utcnow() - dt).total_seconds() / 3600


def last_message_preview(ticket_id, limit=40):
    row = db_execute("""
    SELECT message FROM ticket_messages
    WHERE ticket_id=?
    ORDER BY id DESC LIMIT 1
    """, (ticket_id,), fetchone=True)
    if not row or not row["message"]:
        return "-"
    text = row["message"].strip().replace("\n", " ")
    return text[:limit] + ("…" if len(text) > limit else "")


# ============================================================
# ============  USER SIDE  ===================================
# ============================================================

# نکته مهم: این دکمه («🆘 پشتیبانی») فقط توی منوی کاربر وجود داره.
# قبلاً بر اساس نقش کاربر (ادمین/غیرادمین) تصمیم می‌گرفت کدوم فلو
# اجرا بشه، که باعث می‌شد سوپرادمین وقتی از طریق «🏠 منوی کاربر»
# وارد منوی کاربر می‌شه و این دکمه رو می‌زنه، به‌جای فرم ثبت تیکت،
# پنل مدیریت پشتیبانی براش باز بشه. حالا این دکمه همیشه (برای هرکسی
# که می‌زندش، حتی سوپرادمین) فرم کاربر رو باز می‌کنه.
@bot.message_handler(func=lambda m: m.text == "🆘 پشتیبانی")
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

    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="sup:back_main"))

    render(
        chat_id,
        "🆘 <b>مرکز پشتیبانی</b>\n\n"
        "برای ارتباط با پشتیبانی تیکت ایجاد کن یا تیکت‌های قبلیت رو ببین.",
        kb,
        message_id
    )


@bot.callback_query_handler(func=lambda call: call.data == "sup:back_main")
def sup_back_main(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(call.message.chat.id, "🏠 بازگشت به منوی اصلی", reply_markup=user_keyboard())


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

# این دکمه («🎫 مدیریت تیکت‌ها») فقط توی منوی سوپرادمین هست
# (جدا از دکمه‌ی «🆘 پشتیبانی» که مخصوص کاربرهاست) — برای همین
# دیگه نیازی به چک نقش رو متن دکمه نیست، خود دکمه فقط تو کیبورد
# ادمین وجود داره. با این حال چک is_support_staff رو برای امنیت
# بیشتر نگه می‌داریم (اگه یه‌جای دیگه هم صدا زده بشه).
@bot.message_handler(func=lambda m: m.text == "🎫 مدیریت تیکت‌ها" and is_support_staff(m.from_user.id))
def admin_support_entry(message):
    render_admin_menu(message.chat.id)


def render_admin_menu(chat_id, message_id=None):
    open_count = db_execute(
        "SELECT COUNT(*) c FROM tickets WHERE status='open'", fetchone=True
    )["c"]
    answered_count = db_execute(
        "SELECT COUNT(*) c FROM tickets WHERE status='answered'", fetchone=True
    )["c"]
    closed_count = db_execute(
        "SELECT COUNT(*) c FROM tickets WHERE status='closed'", fetchone=True
    )["c"]

    # قدیمی‌ترین تیکت باز که هنوز جواب نگرفته (برای هشدار)
    oldest_open = db_execute("""
    SELECT updated_at FROM tickets WHERE status='open'
    ORDER BY updated_at ASC LIMIT 1
    """, fetchone=True)

    warning = ""
    if oldest_open:
        hrs = hours_since(oldest_open["updated_at"])
        if hrs >= 24:
            warning = f"\n🚨 یه تیکت بیش از {int(hrs // 24)} روزه بی‌پاسخ مونده!"
        elif hrs >= 3:
            warning = f"\n⏰ یه تیکت {int(hrs)} ساعته بی‌پاسخ مونده."

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🟢 نیاز به پاسخ ({open_count})", callback_data="asup:list:open:0"))
    kb.add(types.InlineKeyboardButton(f"💬 پاسخ‌داده‌شده ({answered_count})", callback_data="asup:list:answered:0"))
    kb.add(types.InlineKeyboardButton(f"🔒 بسته‌شده ({closed_count})", callback_data="asup:list:closed:0"))
    kb.add(types.InlineKeyboardButton("📁 همه تیکت‌ها", callback_data="asup:list:all:0"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="asup:back_main"))

    render(
        chat_id,
        "🛠 <b>مدیریت پشتیبانی</b>\n\n"
        f"🟢 نیاز به پاسخ: <b>{open_count}</b>\n"
        f"💬 پاسخ‌داده‌شده: <b>{answered_count}</b>\n"
        f"🔒 بسته‌شده: <b>{closed_count}</b>"
        f"{warning}",
        kb, message_id
    )


@bot.callback_query_handler(func=lambda call: call.data == "asup:back_main")
def asup_back_main(call):
    if not is_support_staff(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(call.message.chat.id, "🏠 بازگشت به منوی اصلی", reply_markup=admin_keyboard())


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

    parts = call.data.split(":")
    scope = parts[2]
    page = int(parts[3]) if len(parts) > 3 else 0
    bot.answer_callback_query(call.id)
    render_admin_ticket_list(scope, page, call.message.chat.id, call.message.message_id)


TICKET_PAGE_SIZE = 6


def render_admin_ticket_list(scope, page, chat_id, message_id=None):
    scope_titles = {
        "open": "🟢 تیکت‌های نیازمند پاسخ",
        "answered": "💬 تیکت‌های پاسخ‌داده‌شده",
        "closed": "🔒 تیکت‌های بسته‌شده",
        "all": "📁 همه تیکت‌ها",
    }
    title = scope_titles.get(scope, "تیکت‌ها")

    where = "" if scope == "all" else "WHERE status=?"
    params = () if scope == "all" else (scope,)

    total = db_execute(f"SELECT COUNT(*) c FROM tickets {where}", params, fetchone=True)["c"]

    offset = page * TICKET_PAGE_SIZE
    tickets = db_execute(f"""
    SELECT * FROM tickets {where}
    ORDER BY
        CASE status WHEN 'open' THEN 0 WHEN 'answered' THEN 1 ELSE 2 END,
        updated_at ASC
    LIMIT ? OFFSET ?
    """, params + (TICKET_PAGE_SIZE, offset), fetchall=True) or []

    kb = types.InlineKeyboardMarkup()

    if not tickets:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="asup:menu"))
        render(chat_id, f"{title}\n\n📭 موردی پیدا نشد.", kb, message_id)
        return

    for t in tickets:
        preview = last_message_preview(t["id"], limit=25)
        overdue = ""
        if t["status"] == "open" and hours_since(t["updated_at"]) >= 3:
            overdue = "⏰ "
        label = f"{overdue}#{t['id']} · {preview} · {relative_time(t['updated_at'])}"
        kb.add(types.InlineKeyboardButton(label[:64], callback_data=f"asup:view:{t['id']}:{scope}:{page}"))

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data=f"asup:list:{scope}:{page-1}"))
    if offset + TICKET_PAGE_SIZE < total:
        nav.append(types.InlineKeyboardButton("بعدی ➡️", callback_data=f"asup:list:{scope}:{page+1}"))
    if nav:
        kb.row(*nav)

    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منو", callback_data="asup:menu"))

    render(chat_id, f"{title}\n\n{total} مورد، صفحه {page+1}", kb, message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("asup:view:"))
def asup_view(call):
    if not is_support_staff(call.from_user.id):
        return

    parts = call.data.split(":")
    ticket_id = int(parts[2])
    scope = parts[3] if len(parts) > 3 else "open"
    page = parts[4] if len(parts) > 4 else "0"
    bot.answer_callback_query(call.id)
    render_admin_ticket_view(ticket_id, call.message.chat.id, call.message.message_id, scope, page)


def render_admin_ticket_view(ticket_id, chat_id, message_id=None, scope="open", page="0"):
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
        f"🕒 آخرین فعالیت: {relative_time(ticket['updated_at'])}\n"
    ]

    for m in messages[-15:]:
        sender = "👤 کاربر" if str(m["sender_id"]) == str(owner_tg_id) else "👨‍💻 شما"
        lines.append(f"{sender}:\n{esc(m['message'])}\n")

    kb = types.InlineKeyboardMarkup()

    if ticket["status"] != "closed":
        kb.row(
            types.InlineKeyboardButton("✍️ پاسخ", callback_data=f"asup:reply:{ticket_id}:{scope}:{page}"),
            types.InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"asup:close:{ticket_id}:{scope}:{page}"),
        )
    else:
        kb.add(types.InlineKeyboardButton("🔓 بازگشایی تیکت", callback_data=f"asup:reopen:{ticket_id}:{scope}:{page}"))

    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data=f"asup:list:{scope}:{page}"))

    render(chat_id, "\n".join(lines), kb, message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("asup:reply:"))
def asup_reply_start(call):
    if not is_support_staff(call.from_user.id):
        return

    parts = call.data.split(":")
    ticket_id = int(parts[2])
    scope = parts[3] if len(parts) > 3 else "open"
    page = parts[4] if len(parts) > 4 else "0"
    ticket = get_ticket(ticket_id)

    if not ticket:
        bot.answer_callback_query(call.id, "❌ تیکت پیدا نشد.", show_alert=True)
        return

    if ticket["status"] == "closed":
        bot.answer_callback_query(call.id, "❌ این تیکت بسته شده. اول بازش کن.", show_alert=True)
        return

    bot.answer_callback_query(call.id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"asup:view:{ticket_id}:{scope}:{page}"))

    try:
        bot.edit_message_text(
            f"✍️ پاسخت رو برای تیکت #{ticket_id} بنویس و بفرست:",
            call.message.chat.id, call.message.message_id, reply_markup=kb
        )
    except Exception:
        bot.send_message(call.message.chat.id, f"✍️ پاسخت رو برای تیکت #{ticket_id} بنویس و بفرست:", reply_markup=kb)

    bot.register_next_step_handler(call.message, admin_reply_save, ticket_id, scope, page)


def admin_reply_save(message, ticket_id, scope="open", page="0"):
    if not (message.text or "").strip():
        msg = bot.send_message(message.chat.id, "❌ متن خالیه. دوباره بفرست:")
        bot.register_next_step_handler(msg, admin_reply_save, ticket_id, scope, page)
        return

    ticket = get_ticket(ticket_id)
    if not ticket:
        bot.send_message(message.chat.id, "❌ این تیکت دیگه وجود نداره.")
        return

    add_message(ticket_id, message.from_user.id, message.text)
    touch_ticket(ticket_id, status="answered")

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به تیکت", callback_data=f"asup:view:{ticket_id}:{scope}:{page}"))
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

    parts = call.data.split(":")
    ticket_id = int(parts[2])
    scope = parts[3] if len(parts) > 3 else "open"
    page = parts[4] if len(parts) > 4 else "0"
    touch_ticket(ticket_id, status="closed")

    bot.answer_callback_query(call.id, "🔒 تیکت بسته شد.")
    render_admin_ticket_view(ticket_id, call.message.chat.id, call.message.message_id, scope, page)

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

    parts = call.data.split(":")
    ticket_id = int(parts[2])
    scope = parts[3] if len(parts) > 3 else "open"
    page = parts[4] if len(parts) > 4 else "0"
    touch_ticket(ticket_id, status="open")

    bot.answer_callback_query(call.id, "🔓 تیکت بازگشایی شد.")
    render_admin_ticket_view(ticket_id, call.message.chat.id, call.message.message_id, scope, page)
