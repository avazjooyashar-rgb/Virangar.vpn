# ============================================================
# handlers_payment.py
# پرداخت کارت به کارت، کیف پول، آنلاین، تأیید/رد توسط مدیر
# + پنل «مدیریت پرداخت‌ها» (لیست + صفحه‌بندی) به‌جای اسپم پیام
# ============================================================
from telebot import types
from config import bot, SUPER_ADMIN_ID
from database import db_execute, get_setting, now
from models import internal_user_id, is_superadmin, get_user
from pasarguard_api import pasarguard_create_service
from services import create_local_service
from decorators import admin_only
from keyboards import admin_keyboard
from datetime import datetime

PAGE_SIZE = 5  # تعداد پرداخت در هر صفحه لیست مدیریت


# ============================================================
# HELPERS
# ============================================================
def _relative_time(dt_str):
    """تبدیل تاریخ ذخیره‌شده به زمان نسبی مثل '۲ ساعت پیش'."""
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return dt_str
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


def _user_history_stats(user_id, exclude_payment_id=None):
    """سابقه‌ی خرید کاربر: تعداد پرداخت تأییدشده + مجموع مبلغ."""
    row = db_execute(
        """
        SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total
        FROM payments
        WHERE user_id=? AND status='approved'
        """,
        (user_id,),
        fetchone=True
    )
    return row["cnt"] if row else 0, row["total"] if row else 0


def _duplicate_receipt_warning(payment):
    """اگه همین عکس رسید قبلاً برای پرداخت دیگه‌ای استفاده شده باشه، هشدار می‌ده."""
    if not payment["receipt_file_id"]:
        return None
    dup = db_execute(
        """
        SELECT id FROM payments
        WHERE receipt_file_id=? AND id!=?
        LIMIT 1
        """,
        (payment["receipt_file_id"], payment["id"]),
        fetchone=True
    )
    if dup:
        return f"🚨 <b>هشدار: این رسید قبلاً برای پرداخت #{dup['id']} هم ارسال شده!</b>"
    return None


# ============================================================
# MANUAL PAYMENT (plan purchase) - card to card
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("manual:"))
def manual_payment(call):
    parts = call.data.split(":", 2)
    plan_id = int(parts[1])
    username = parts[2] if len(parts) > 2 else None

    plan = db_execute(
        "SELECT * FROM plans WHERE id=? AND active=1",
        (plan_id,),
        fetchone=True
    )
    if not plan:
        bot.answer_callback_query(call.id, "پلن پیدا نشد", show_alert=True)
        return
    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")
    if not card:
        bot.answer_callback_query(
            call.id,
            "پرداخت کارت به کارت فعلاً تنظیم نشده.",
            show_alert=True
        )
        return
    text = (
        "💳 <b>پرداخت کارت به کارت</b>\n\n"
        f"💰 مبلغ: <b>{plan['price']:,} تومان</b>\n\n"
        f"💳 شماره کارت:\n<code>{card}</code>\n\n"
        f"👤 به نام: <b>{holder or '---'}</b>\n\n"
        "بعد از انتقال وجه، تصویر رسید را همینجا ارسال کنید."
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML")
    bot.register_next_step_handler(
        call.message,
        receive_plan_receipt,
        plan_id,
        username
    )


def receive_plan_receipt(message, plan_id, username):
    if not message.photo:
        sent = bot.send_message(message.chat.id, "❌  لطفاً تصویر رسید را ارسال کن.")
        bot.register_next_step_handler(sent, receive_plan_receipt, plan_id, username)
        return
    file_id = message.photo[-1].file_id
    user_id = internal_user_id(message.from_user.id)
    plan = db_execute("SELECT * FROM plans WHERE id=?", (plan_id,), fetchone=True)
    if not plan:
        return
    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method,
     receipt_file_id, receipt_type,
     custom_username,
     status, created_at, updated_at)
    VALUES (?, ?, ?, 'manual', ?, 'photo',
            ?, 'pending', ?, ?)
    """, (
        user_id, plan_id, plan["price"], file_id, username, now(), now()
    ))
    # دیگه پیام خودکار به ادمین ارسال نمی‌شود؛ فقط در دیتابیس pending می‌ماند
    # و از طریق «مدیریت پرداخت‌ها» قابل مشاهده و بررسی است.
    bot.send_message(
        message.chat.id,
        "✅  رسید شما ثبت شد.\n\n"
        "⏳  پرداخت در انتظار بررسی مدیریت است."
    )


# ============================================================
# WALLET PAYMENT (plan purchase) - pay with balance
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("walletpay:"))
def wallet_payment(call):
    parts = call.data.split(":", 2)
    plan_id = int(parts[1])
    username = parts[2] if len(parts) > 2 else None

    plan = db_execute(
        "SELECT * FROM plans WHERE id=? AND active=1",
        (plan_id,),
        fetchone=True
    )
    if not plan:
        bot.answer_callback_query(call.id, "پلن پیدا نشد", show_alert=True)
        return

    user = get_user(call.from_user.id)
    if not user:
        bot.answer_callback_query(call.id, "کاربر پیدا نشد.", show_alert=True)
        return

    if user["balance"] < plan["price"]:
        bot.answer_callback_query(
            call.id,
            f"❌ موجودی کیف پول کافی نیست.\n"
            f"موجودی: {user['balance']:,} | قیمت: {plan['price']:,}",
            show_alert=True
        )
        return

    panel = db_execute(
        "SELECT * FROM panels WHERE id=? AND active=1",
        (plan["panel_id"],),
        fetchone=True
    )
    if not panel:
        bot.answer_callback_query(call.id, "پنل این پلن فعال نیست.", show_alert=True)
        return

    bot.answer_callback_query(call.id, "⏳ در حال ساخت سرویس...")

    result = pasarguard_create_service(
        panel=panel,
        telegram_user=user,
        plan=plan,
        desired_username=username
    )

    if not result["success"]:
        bot.send_message(
            call.message.chat.id,
            "❌ ساخت سرویس ناموفق بود. لطفاً بعداً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.\n\n"
            f"<code>{result['error']}</code>",
            parse_mode="HTML"
        )
        # این یک خطای فنی (نه یک پرداخت جدید در انتظار) است، همچنان به‌صورت
        # مستقیم به سوپرادمین اطلاع داده می‌شود چون نیاز به رسیدگی فوری دارد.
        bot.send_message(
            SUPER_ADMIN_ID,
            "⚠️ پرداخت کیف‌پولی ناموفق بود چون ساخت سرویس PasarGuard خطا داد.\n\n"
            f"User: {user['telegram_id']}\n"
            f"خطا: {result['error']}"
        )
        return

    # کسر از کیف پول
    db_execute("UPDATE users SET balance=balance-? WHERE id=?", (plan["price"], user["id"]))
    db_execute("""
    INSERT INTO transactions
    (user_id, amount, type, description, reference, created_at)
    VALUES (?, ?, 'debit', ?, ?, ?)
    """, (
        user["id"], -plan["price"], f"خرید پلن {plan['name']} (کیف پول)",
        f"plan:{plan_id}", now()
    ))

    service = create_local_service(user=user, plan=plan, panel=panel, result=result)

    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method,
     custom_username, service_id,
     status, created_at, updated_at)
    VALUES (?, ?, ?, 'wallet_purchase', ?, ?, 'approved', ?, ?)
    """, (
        user["id"], plan_id, plan["price"], username, service["id"], now(), now()
    ))

    bot.send_message(
        call.message.chat.id,
        "🎉 <b>پرداخت با موفقیت انجام شد!</b>\n\n"
        "🛡 سرویس شما با موفقیت ساخته شد.\n\n"
        f"📦 پلن: {plan['name']}\n"
        f"⏳  مدت: {plan['duration']} روز\n"
        f"📊 حجم: {plan['volume']} GB\n\n"
        f"🔗 لینک اشتراک:\n"
        f"<code>{service['config']}</code>",
        parse_mode="HTML"
    )


# ============================================================
# PAYMENT MANAGEMENT PANEL (فیلتر تب‌دار + صفحه‌بندی + آمار)
# ورودی به این پنل از منوی سوپرادمین:
#   types.InlineKeyboardButton("💳 پرداخت‌ها", callback_data="paymgmt:pending:0")
# (اگه دکمه‌ی فعلی منوت callback_data یا متن دیگه‌ای داره، بگو تا وصلش کنم)
# ============================================================
STATUS_TABS = [
    ("pending", "🟡 در انتظار"),
    ("approved", "✅ تأییدشده"),
    ("rejected", "❌ ردشده"),
    ("all", "📋 همه"),
]


def _payment_row_label(payment):
    status_icon = {"pending": "🟡", "approved": "✅", "rejected": "❌"}.get(payment["status"], "▫️")
    user = db_execute("SELECT * FROM users WHERE id=?", (payment["user_id"],), fetchone=True)
    uname = f"@{user['username']}" if user and user["username"] else (user["telegram_id"] if user else "?")
    when = _relative_time(payment["created_at"])
    return f"{status_icon} #{payment['id']} | {payment['amount']:,} | {uname} | {when}"


def _today_summary():
    row = db_execute(
        """
        SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as cnt
        FROM payments
        WHERE status='approved' AND date(updated_at)=date('now')
        """,
        fetchone=True
    )
    pending_cnt = db_execute(
        "SELECT COUNT(*) as c FROM payments WHERE status='pending'",
        fetchone=True
    )["c"]
    return row["total"] if row else 0, row["cnt"] if row else 0, pending_cnt


def _build_payment_list_keyboard(status, page):
    where = "" if status == "all" else "WHERE status=?"
    params = () if status == "all" else (status,)

    total = db_execute(
        f"SELECT COUNT(*) as c FROM payments {where}",
        params,
        fetchone=True
    )["c"]

    offset = page * PAGE_SIZE
    rows = db_execute(
        f"""
        SELECT * FROM payments
        {where}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        params + (PAGE_SIZE, offset),
        fetchall=True
    ) or []

    kb = types.InlineKeyboardMarkup()

    # تب‌های فیلتر
    tab_buttons = []
    for tab_key, tab_label in STATUS_TABS:
        label = f"• {tab_label} •" if tab_key == status else tab_label
        tab_buttons.append(types.InlineKeyboardButton(label, callback_data=f"paymgmt:{tab_key}:0"))
    kb.row(*tab_buttons[:2])
    kb.row(*tab_buttons[2:])

    for p in rows:
        kb.add(types.InlineKeyboardButton(_payment_row_label(p), callback_data=f"paydetail:{p['id']}:{status}:{page}"))

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data=f"paymgmt:{status}:{page-1}"))
    if offset + PAGE_SIZE < total:
        nav.append(types.InlineKeyboardButton("بعدی ➡️", callback_data=f"paymgmt:{status}:{page+1}"))
    if nav:
        kb.row(*nav)

    kb.add(types.InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"paymgmt:{status}:{page}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="paymgmt_back"))

    return kb, total, rows


def _render_payment_panel_text(status, page):
    """ساخت متن+کیبورد پنل مدیریت پرداخت. مشترک بین ورودی دکمه و pagination."""
    kb, total, rows = _build_payment_list_keyboard(status, page)

    today_total, today_cnt, pending_cnt = _today_summary()
    status_label = dict(STATUS_TABS).get(status, status)

    header = (
        "💳 <b>مدیریت پرداخت‌ها</b>\n\n"
        f"📊 امروز: <b>{today_total:,}</b> تومان ({today_cnt} تراکنش تأییدشده)\n"
        f"🟡 در انتظار بررسی: <b>{pending_cnt}</b>\n"
        "━━━━━━━━━━━━━\n"
    )

    if total == 0:
        text = header + f"چیزی توی «{status_label}» نیست."
    else:
        text = header + f"نمایش «{status_label}» — {total} مورد، صفحه {page+1}"

    return text, kb


# نقطه ورود از منوی سوپرادمین: دکمه‌ی reply-keyboard «💰 پرداخت‌ها»
@bot.message_handler(func=lambda m: m.text == "💰 پرداخت‌ها")
@admin_only
def open_payment_management(message):
    text, kb = _render_payment_panel_text("pending", 0)
    bot.send_message(message.chat.id, text, reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: call.data == "paymgmt_back")
def payment_management_back(call):
    if not is_superadmin(call.from_user.id):
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(call.message.chat.id, "🏠 بازگشت به منوی اصلی", reply_markup=admin_keyboard())
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("paymgmt:"))
def payment_management_panel(call):
    if not is_superadmin(call.from_user.id):
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return

    _, status, page = call.data.split(":")
    page = int(page)
    text, kb = _render_payment_panel_text(status, page)

    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=kb, parse_mode="HTML")

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("paydetail:"))
def payment_detail(call):
    if not is_superadmin(call.from_user.id):
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return

    _, payment_id, status, page = call.data.split(":")
    payment_id = int(payment_id)

    payment = db_execute("SELECT * FROM payments WHERE id=?", (payment_id,), fetchone=True)
    if not payment:
        bot.answer_callback_query(call.id, "پرداخت پیدا نشد.", show_alert=True)
        return

    user = db_execute("SELECT * FROM users WHERE id=?", (payment["user_id"],), fetchone=True)
    plan = None
    if payment["plan_id"]:
        plan = db_execute("SELECT * FROM plans WHERE id=?", (payment["plan_id"],), fetchone=True)

    username = f"@{user['username']}" if user and user["username"] else "بدون یوزرنیم"
    custom_username = payment["custom_username"] if "custom_username" in payment.keys() else None

    hist_cnt, hist_total = _user_history_stats(payment["user_id"])
    trust_line = (
        f"⭐️ سابقه: {hist_cnt} خرید تأییدشده قبلی | مجموع {hist_total:,} تومان"
        if hist_cnt > 0 else "🆕 اولین خرید این کاربر"
    )

    dup_warning = _duplicate_receipt_warning(payment)

    text = (
        "💳 <b>جزئیات پرداخت</b>\n\n"
        f"🆔 Payment: <code>{payment['id']}</code>\n"
        f"👤 کاربر: {username}\n"
        f"🆔 Telegram ID: <code>{user['telegram_id'] if user else '---'}</code>\n"
        f"💰 مبلغ: {payment['amount']:,} تومان\n"
        f"📦 پلن: {plan['name'] if plan else '---'}\n"
        f"🏷 نام سرویس: {custom_username or '---'}\n"
        f"📌 روش: {payment['method']}\n"
        f"🕒 {_relative_time(payment['created_at'])}\n\n"
        f"{trust_line}"
    )
    if dup_warning:
        text = dup_warning + "\n\n" + text

    kb = types.InlineKeyboardMarkup()
    if payment["status"] == "pending":
        kb.row(
            types.InlineKeyboardButton("✅  تأیید", callback_data=f"payapprove:{payment['id']}:{status}:{page}"),
            types.InlineKeyboardButton("❌  رد", callback_data=f"payreject:{payment['id']}:{status}:{page}")
        )
    kb.add(types.InlineKeyboardButton("⬅️ بازگشت به لیست", callback_data=f"paymgmt:{status}:{page}"))

    if payment["receipt_file_id"]:
        try:
            bot.send_photo(call.message.chat.id, payment["receipt_file_id"], caption="🧾 رسید پرداخت")
        except Exception:
            pass

    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=kb, parse_mode="HTML")

    bot.answer_callback_query(call.id)


# ============================================================
# APPROVE
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("payapprove:"))
def approve_payment(call):
    if not is_superadmin(call.from_user.id):
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return

    parts = call.data.split(":")
    payment_id = int(parts[1])
    status = parts[2] if len(parts) > 2 else "pending"
    page = parts[3] if len(parts) > 3 else "0"

    payment = db_execute("SELECT * FROM payments WHERE id=?", (payment_id,), fetchone=True)
    if not payment or payment["status"] != "pending":
        bot.answer_callback_query(call.id, "این پرداخت قبلاً بررسی شده.", show_alert=True)
        return

    # Wallet topup
    if payment["method"] == "wallet":
        user = db_execute("SELECT * FROM users WHERE id=?", (payment["user_id"],), fetchone=True)
        db_execute("UPDATE users SET balance=balance+? WHERE id=?", (payment["amount"], payment["user_id"]))
        db_execute("""
        INSERT INTO transactions
        (user_id, amount, type, description, reference, created_at)
        VALUES (?, ?, 'credit', ?, ?, ?)
        """, (
            payment["user_id"], payment["amount"], "شارژ کیف پول",
            f"payment:{payment_id}", now()
        ))
        db_execute("UPDATE payments SET status='approved', updated_at=? WHERE id=?", (now(), payment_id))
        if user:
            bot.send_message(
                user["telegram_id"],
                f"✅  پرداخت تأیید شد.\n\n"
                f"💰 مبلغ <b>{payment['amount']:,}</b> تومان "
                f"به کیف پول شما اضافه شد.",
                parse_mode="HTML"
            )
        bot.answer_callback_query(call.id, "کیف پول شارژ شد ✅ ")
        payment_management_panel(_fake_call(call, f"paymgmt:{status}:{page}"))
        return

    # VPN service (manual/card payment)
    plan = db_execute("SELECT * FROM plans WHERE id=?", (payment["plan_id"],), fetchone=True)
    user = db_execute("SELECT * FROM users WHERE id=?", (payment["user_id"],), fetchone=True)
    if not plan or not user:
        bot.answer_callback_query(call.id, "اطلاعات پرداخت ناقص است.", show_alert=True)
        return
    panel = None
    if plan["panel_id"]:
        panel = db_execute("SELECT * FROM panels WHERE id=? AND active=1", (plan["panel_id"],), fetchone=True)
    if not panel:
        panel = db_execute("""
        SELECT * FROM panels
        WHERE active=1
        ORDER BY assigned_sales ASC, id ASC
        LIMIT 1
        """, fetchone=True)
    if not panel:
        bot.answer_callback_query(call.id, "هیچ پنل فعالی برای ساخت سرویس وجود ندارد.", show_alert=True)
        return

    custom_username = payment["custom_username"] if "custom_username" in payment.keys() else None

    result = pasarguard_create_service(
        panel=panel,
        telegram_user=user,
        plan=plan,
        desired_username=custom_username
    )
    if not result["success"]:
        bot.answer_callback_query(call.id, "ساخت سرویس انجام نشد.", show_alert=True)
        bot.send_message(
            SUPER_ADMIN_ID,
            "⚠️ پرداخت تأیید نشد چون ساخت سرویس PasarGuard موفق نبود.\n\n"
            f"Payment: {payment_id}\n"
            f"خطا: {result['error']}"
        )
        return
    service = create_local_service(user=user, plan=plan, panel=panel, result=result)
    db_execute("""
    UPDATE payments
    SET status='approved', service_id=?, updated_at=?
    WHERE id=?
    """, (service["id"], now(), payment_id))
    bot.send_message(
        user["telegram_id"],
        "🎉 <b>پرداخت شما تأیید شد!</b>\n\n"
        "🛡 سرویس شما با موفقیت ساخته شد.\n\n"
        f"📦 پلن: {plan['name']}\n"
        f"⏳  مدت: {plan['duration']} روز\n"
        f"📊 حجم: {plan['volume']} GB\n\n"
        f"🔗 لینک اشتراک:\n"
        f"<code>{service['config']}</code>",
        parse_mode="HTML"
    )
    bot.answer_callback_query(call.id, "پرداخت و سرویس تأیید شد ✅")
    payment_management_panel(_fake_call(call, f"paymgmt:{status}:{page}"))


# ============================================================
# REJECT
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("payreject:"))
def reject_payment(call):
    if not is_superadmin(call.from_user.id):
        return

    parts = call.data.split(":")
    payment_id = int(parts[1])
    status = parts[2] if len(parts) > 2 else "pending"
    page = parts[3] if len(parts) > 3 else "0"

    payment = db_execute("SELECT * FROM payments WHERE id=?", (payment_id,), fetchone=True)
    if not payment or payment["status"] != "pending":
        bot.answer_callback_query(call.id, "این پرداخت قبلاً بررسی شده.", show_alert=True)
        return
    db_execute("UPDATE payments SET status='rejected', updated_at=? WHERE id=?", (now(), payment_id))
    user = db_execute("SELECT * FROM users WHERE id=?", (payment["user_id"],), fetchone=True)
    if user:
        bot.send_message(
            user["telegram_id"],
            "❌  رسید پرداخت شما رد شد.\n\n"
            "در صورت اشتباه، دوباره اقدام کنید."
        )
    bot.answer_callback_query(call.id, "پرداخت رد شد ❌ ")
    payment_management_panel(_fake_call(call, f"paymgmt:{status}:{page}"))


def _fake_call(call, new_data):
    """برای بازگشت به لیست بعد از تأیید/رد، یک آبجکت call با data جدید می‌سازیم."""
    call.data = new_data
    return call


# ============================================================
# ONLINE PAYMENT (stub)
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("online:"))
def online_payment(call):
    provider = get_setting("gateway_provider", "")
    if not provider:
        bot.answer_callback_query(call.id, "درگاه پرداخت تنظیم نشده.", show_alert=True)
        return
    bot.send_message(
        call.message.chat.id,
        "🌐 درگاه آنلاین فعال است، اما اتصال نهایی "
        "به API درگاه انتخابی نیاز به مشخصات همان درگاه دارد."
    )
