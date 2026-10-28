# ============================================================
# handlers_payment.py  [نسخه‌ی کامل با تایید خودکار کارت‌به‌کارت]
# پرداخت کارت به کارت (مبلغ یکتا + تایید خودکار با پیامک بانک)،
# کیف پول، آنلاین، تأیید/رد توسط مدیر + پنل «مدیریت پرداخت‌ها»
#
# نیازمندی: pip install "qrcode[pil]" fastapi uvicorn
# ============================================================
import io
import threading
import traceback
import uuid
from html import escape as _esc

from telebot import types
from config import bot, SUPER_ADMIN_ID
from database import db_execute, get_setting, now
from models import internal_user_id, is_superadmin, get_user
from pasarguard_api import pasarguard_create_service
from services import create_local_service
from decorators import admin_only
from keyboards import admin_keyboard, user_keyboard
from datetime import datetime
import chat_clean as cc
from auto_confirm import make_unique_amount

try:
    import qrcode
except ImportError:  # اگه نصب نبود، لینک فقط به‌صورت متن فرستاده میشه
    qrcode = None

PAGE_SIZE = 5  # تعداد پرداخت در هر صفحه لیست مدیریت
RECEIPT_TIMEOUT_SECONDS = 15 * 60  # مهلت ارسال رسید کارت به کارت

# chat_id -> {"token", "message_id", "timer", "plan_id", "username", "payment_id"}
_receipt_wait = {}
_wait_lock = threading.Lock()

# جلوگیری از تایید هم‌زمان یک پرداخت (دکمه‌ی ادمین + تایید خودکار)
_approve_lock = threading.Lock()


# ============================================================
# سازگاری با ماژول‌های دیگر (مثل handlers_wallet.py)
# ============================================================
def notify_admin_payment(payment):
    return


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


def _edit(chat_id, message_id, text, kb):
    """پیام رو ادیت می‌کنه؛ اگه نشد پیام جدید می‌فرسته. شناسه‌ی پیام نهایی رو برمی‌گردونه."""
    if message_id:
        try:
            bot.edit_message_text(
                text, chat_id, message_id,
                reply_markup=kb, parse_mode="HTML"
            )
            return message_id
        except Exception as e:
            if "message is not modified" in str(e):
                return message_id
    sent = cc.show(chat_id, text, reply_markup=kb, parse_mode="HTML")
    return sent.message_id if sent else None


def _home_kb(extra_buttons=None):
    """کیبورد شیشه‌ای با دکمه‌ی منوی اصلی (و دکمه‌های اضافه‌ی بالاش)."""
    kb = types.InlineKeyboardMarkup()
    for text, cb in (extra_buttons or []):
        kb.add(types.InlineKeyboardButton(text, callback_data=cb))
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))
    return kb


def _qr_bio(link):
    if not qrcode or not link:
        return None
    try:
        img = qrcode.make(link)
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        return bio
    except Exception:
        traceback.print_exc()
        return None


def send_service_delivery(chat_id, title, plan, config):
    """
    تحویل سرویس به کاربر: یک پیام واحد که بالاش QR کد و پایینش لینک اشتراکه.
    """
    link = config or ""
    caption = (
        f"{title}\n\n"
        "🛡 سرویس شما با موفقیت ساخته شد.\n\n"
        f"📦 پلن: {plan['name']}\n"
        f"⏳ مدت: {plan['duration']} روز\n"
        f"📊 حجم: {plan['volume']} GB\n\n"
        "🔗 لینک اشتراک:\n"
        f"<code>{_esc(link) if link else '---'}</code>"
    )
    kb = _home_kb()

    bio = _qr_bio(link)
    if bio:
        try:
            if len(caption) <= 1000:
                bot.send_photo(
                    chat_id, bio, caption=caption,
                    parse_mode="HTML", reply_markup=kb
                )
                return
            bot.send_photo(chat_id, bio, caption="📱 QR کد اشتراک")
        except Exception:
            traceback.print_exc()

    bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)


# ============================================================
# مهلت ۱۵ دقیقه‌ای ارسال رسید
# ============================================================
def _cancel_receipt_wait(chat_id):
    with _wait_lock:
        wait = _receipt_wait.pop(chat_id, None)
    if wait and wait.get("timer"):
        wait["timer"].cancel()
    return wait


def _our_step_pending(chat_id):
    """
    چک می‌کنه هنوز منتظر رسید همین مرحله هستیم یا کاربر رفته جای دیگه
    (اگه نتونیم تشخیص بدیم، True برمی‌گردونه تا مهلت اعمال بشه).
    """
    try:
        handlers = bot.next_step_backend.handlers.get(chat_id) or []
    except Exception:
        return True
    for h in handlers:
        cb = getattr(h, "callback", None)
        if cb is None and isinstance(h, dict):
            cb = h.get("callback")
        if cb is None:
            return True
        if cb is receive_plan_receipt:
            return True
    return False


def _expire_receipt_wait(chat_id, token):
    with _wait_lock:
        wait = _receipt_wait.get(chat_id)
        if not wait or wait["token"] != token:
            return
        _receipt_wait.pop(chat_id, None)

    # کاربر مرحله رو ترک کرده؛ به صفحه‌ی فعلیش دست نمی‌زنیم
    if not _our_step_pending(chat_id):
        return

    bot.clear_step_handler_by_chat_id(chat_id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔄 شروع دوباره", callback_data="buy_back_home"))
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))
    text = (
        "⏰ <b>مهلت پرداخت تموم شد</b>\n\n"
        "برای ادامه‌ی خرید باید مراحل رو از اول شروع کنی."
    )
    try:
        bot.edit_message_text(
            text, chat_id, wait["message_id"],
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        try:
            bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            traceback.print_exc()


def finish_receipt_screen(internal_uid):
    """بعد از تأیید پرداخت: انتظار رسید لغو و صفحه‌ی کارت‌به‌کارت کاربر بسته میشه."""
    user = db_execute("SELECT * FROM users WHERE id=?", (internal_uid,), fetchone=True)
    if not user:
        return
    chat_id = user["telegram_id"]
    wait = _cancel_receipt_wait(chat_id)
    bot.clear_step_handler_by_chat_id(chat_id)
    if wait and wait.get("message_id"):
        try:
            bot.edit_message_text(
                "✅ <b>پرداخت دریافت شد.</b>", chat_id, wait["message_id"],
                parse_mode="HTML", reply_markup=_home_kb()
            )
        except Exception:
            pass


# ============================================================
# MANUAL PAYMENT (plan purchase) - card to card
# ============================================================
def _receipt_screen_text(plan, pay_amount, error=None):
    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")
    text = ""
    if error:
        text += f"{error}\n\n"
    text += (
        "💳 <b>پرداخت کارت به کارت</b>\n\n"
        f"💰 مبلغ دقیق: <b>{pay_amount:,} تومان</b>\n"
        "⚠️ <b>دقیقاً همین مبلغ</b> رو واریز کن (با همین چند تومن آخر) "
        "تا پرداخت خودکار تأیید بشه.\n\n"
        f"💳 شماره کارت:\n<code>{card}</code>\n\n"
        f"👤 به نام: <b>{holder or '---'}</b>\n\n"
        "✅ بعد از واریز، تأیید خودکار انجام میشه.\n"
        "📸 اگه تا چند دقیقه تأیید نشد، تصویر رسید رو همینجا بفرست.\n"
        "⏰ مهلت: <b>۱۵ دقیقه</b>"
    )
    return text


def _receipt_cancel_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="paycancel"))
    return kb


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
    if not card:
        bot.answer_callback_query(
            call.id,
            "پرداخت کارت به کارت فعلاً تنظیم نشده.",
            show_alert=True
        )
        return

    chat_id = call.message.chat.id

    # مبلغ یکتا
    pay_amount = make_unique_amount(plan["price"])
    if pay_amount is None:
        bot.answer_callback_query(
            call.id, "فعلاً شلوغه، چند دقیقه دیگه دوباره تلاش کن.", show_alert=True
        )
        return

    bot.answer_callback_query(call.id)

    # هر انتظار قبلی (اگه بود) لغو بشه
    _cancel_receipt_wait(chat_id)
    bot.clear_step_handler_by_chat_id(chat_id)

    # پرداخت‌های در انتظارِ قبلیِ همین کاربر منقضی بشن، بعد پرداخت جدید ثبت میشه
    user_id = internal_user_id(call.from_user.id)
    db_execute(
        "UPDATE payments SET status='expired', updated_at=? "
        "WHERE user_id=? AND status='awaiting'",
        (now(), user_id)
    )
    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, unique_amount, method,
     custom_username, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, 'manual', ?, 'awaiting', ?, ?)
    """, (
        user_id, plan_id, plan["price"], pay_amount, username, now(), now()
    ))
    payment_id = db_execute(
        "SELECT id FROM payments WHERE user_id=? AND status='awaiting' "
        "ORDER BY id DESC LIMIT 1",
        (user_id,), fetchone=True
    )["id"]

    # همون پیام روش پرداخت به صفحه‌ی کارت به کارت تبدیل میشه
    message_id = _edit(
        chat_id, call.message.message_id,
        _receipt_screen_text(plan, pay_amount), _receipt_cancel_kb()
    )

    token = uuid.uuid4().hex
    timer = threading.Timer(
        RECEIPT_TIMEOUT_SECONDS, _expire_receipt_wait, args=(chat_id, token)
    )
    timer.daemon = True
    with _wait_lock:
        _receipt_wait[chat_id] = {
            "token": token,
            "message_id": message_id,
            "timer": timer,
            "plan_id": plan_id,
            "username": username,
            "payment_id": payment_id,
        }
    timer.start()

    bot.register_next_step_handler_by_chat_id(
        chat_id, receive_plan_receipt, plan_id, username, payment_id
    )


@bot.callback_query_handler(func=lambda call: call.data == "paycancel")
def payment_cancel(call):
    """بازگشت از صفحه‌ی ارسال رسید به انتخاب روش پرداخت."""
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    wait = _cancel_receipt_wait(chat_id)
    bot.clear_step_handler_by_chat_id(chat_id)

    # مبلغ یکتای این صفحه آزاد بشه
    if wait and wait.get("payment_id"):
        db_execute(
            "UPDATE payments SET status='expired', updated_at=? "
            "WHERE id=? AND status='awaiting'",
            (now(), wait["payment_id"])
        )

    from handlers_shop import show_payment_methods, show_panels

    plan = None
    if wait and wait.get("plan_id"):
        plan = db_execute(
            "SELECT * FROM plans WHERE id=? AND active=1",
            (wait["plan_id"],), fetchone=True
        )
    if plan and wait.get("username"):
        show_payment_methods(
            chat_id, call.from_user.id, plan, wait["username"],
            call.message.message_id
        )
    else:
        show_panels(chat_id, call.message.message_id)


def receive_plan_receipt(message, plan_id, username, payment_id):
    chat_id = message.chat.id
    cc.drop(message)  # عکس/پیام کاربر از چت پاک بشه (file_id معتبر می‌مونه)

    wait = _receipt_wait.get(chat_id)
    screen_id = wait["message_id"] if wait else cc.get_screen(chat_id)

    payment = db_execute("SELECT * FROM payments WHERE id=?", (payment_id,), fetchone=True)
    plan = db_execute("SELECT * FROM plans WHERE id=?", (plan_id,), fetchone=True)
    if not payment or not plan:
        _cancel_receipt_wait(chat_id)
        _edit(chat_id, screen_id, "❌ این سفارش دیگر معتبر نیست.", _home_kb())
        return

    if payment["status"] == "approved":
        _cancel_receipt_wait(chat_id)
        _edit(chat_id, screen_id, "✅ پرداختت قبلاً تأیید شده.", _home_kb())
        return

    if not message.photo:
        _edit(
            chat_id, screen_id,
            _receipt_screen_text(
                plan, payment["unique_amount"] or payment["amount"],
                error="❌ <b>لطفاً تصویر رسید را ارسال کن.</b>"
            ),
            _receipt_cancel_kb()
        )
        bot.register_next_step_handler_by_chat_id(
            chat_id, receive_plan_receipt, plan_id, username, payment_id
        )
        return

    # رسید رسید؛ تایمر لغو بشه
    _cancel_receipt_wait(chat_id)

    db_execute(
        "UPDATE payments SET receipt_file_id=?, receipt_type='photo', "
        "status='pending', updated_at=? WHERE id=? AND status='awaiting'",
        (message.photo[-1].file_id, now(), payment_id)
    )
    _edit(
        chat_id, screen_id,
        "✅ <b>رسید شما ثبت شد.</b>\n\n"
        "⏳ اگه واریز با مبلغ دقیق انجام شده باشه خودکار تأیید میشه، "
        "وگرنه مدیریت بررسی می‌کنه.",
        _home_kb()
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
        cc.show(
            call.message.chat.id,
            "❌ ساخت سرویس ناموفق بود. لطفاً بعداً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.\n\n"
            f"<code>{result['error']}</code>",
            key="err",
            parse_mode="HTML"
        )
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

    cc.drop_screen(call.message.chat.id)
    cc.safe_delete(call.message.chat.id, call.message.message_id)
    send_service_delivery(
        call.message.chat.id,
        "🎉 <b>پرداخت با موفقیت انجام شد!</b>",
        plan,
        service["config"]
    )


# ============================================================
# PAYMENT MANAGEMENT PANEL (فیلتر تب‌دار + صفحه‌بندی + آمار)
# ============================================================
STATUS_TABS = [
    ("pending", "🟡 در انتظار"),
    ("approved", "✅ تأییدشده"),
    ("rejected", "❌ ردشده"),
    ("all", "📋 همه"),
]


def _payment_row_label(payment):
    status_icon = {
        "pending": "🟡", "approved": "✅", "rejected": "❌",
        "awaiting": "⏳", "expired": "⌛"
    }.get(payment["status"], "▫️")
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


@bot.message_handler(func=lambda m: m.text == "💰 پرداخت‌ها")
@admin_only
def open_payment_management(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    cc.drop(message)
    text, kb = _render_payment_panel_text("pending", 0)
    cc.show(message.chat.id, text, key="admin_menu", reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: call.data == "paymgmt_back")
def payment_management_back(call):
    if not is_superadmin(call.from_user.id):
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return
    if not cc.is_screen(call.message.chat.id, call.message.message_id, "admin_menu"):
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
    cc.show(
        call.message.chat.id,
        "🏠 بازگشت به منوی اصلی",
        key="admin_menu",
        reply_markup=admin_keyboard()
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("paymgmt:"))
def payment_management_panel(call):
    if not is_superadmin(call.from_user.id):
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return

    _, status, page = call.data.split(":")
    page = int(page)
    text, kb = _render_payment_panel_text(status, page)

    cc.drop_screen(call.message.chat.id, "admin_receipt")

    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            cc.safe_delete(call.message.chat.id, call.message.message_id)
            cc.show(call.message.chat.id, text, key="admin_menu", reply_markup=kb, parse_mode="HTML")

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

    payment_type = payment["type"] if "type" in payment.keys() else "purchase"
    type_label_map = {
        "purchase": "🛒 خرید سرویس جدید",
        "renew": "🔄 تمدید سرویس",
        "increase": "📈 افزایش حجم",
        "wallet": "💰 شارژ کیف پول",
        "reseller": "🤝 شارژ استخر نمایندگی",
    }
    type_label = type_label_map.get(payment_type, payment_type)

    extra_line = ""
    if payment_type == "renew":
        extra_line = f"⏳ روزهای اضافه‌شونده: {payment['extra_days']}\n"
    elif payment_type == "increase":
        extra_line = f"➕ حجم اضافه‌شونده: {payment['extra_volume']} GB\n"

    reseller_plan = None
    if payment_type == "reseller":
        rp_id = payment["reseller_plan_id"] if "reseller_plan_id" in payment.keys() else None
        if rp_id:
            reseller_plan = db_execute("SELECT * FROM reseller_plans WHERE id=?", (rp_id,), fetchone=True)

    if reseller_plan:
        plan_line = f"📦 پلن نمایندگی: {reseller_plan['name']} ({reseller_plan['volume_gb']} GB)\n"
    else:
        plan_line = f"📦 پلن: {plan['name'] if plan else '---'}\n"

    unique_line = ""
    if "unique_amount" in payment.keys() and payment["unique_amount"]:
        unique_line = f"🎯 مبلغ یکتای واریزی: {payment['unique_amount']:,} تومان\n"

    text = (
        "💳 <b>جزئیات پرداخت</b>\n\n"
        f"🆔 Payment: <code>{payment['id']}</code>\n"
        f"🏷 نوع: {type_label}\n"
        f"👤 کاربر: {username}\n"
        f"🆔 Telegram ID: <code>{user['telegram_id'] if user else '---'}</code>\n"
        f"💰 مبلغ: {payment['amount']:,} تومان\n"
        f"{unique_line}"
        f"{plan_line}"
        f"{extra_line}"
        f"🏷 نام سرویس: {custom_username or '---'}\n"
        f"📌 روش: {payment['method']}\n"
        f"📍 وضعیت: {payment['status']}\n"
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

    cc.drop_screen(call.message.chat.id, "admin_receipt")
    if payment["receipt_file_id"]:
        try:
            photo_msg = bot.send_photo(call.message.chat.id, payment["receipt_file_id"], caption="🧾 رسید پرداخت")
            cc.track(call.message.chat.id, photo_msg.message_id, "admin_receipt")
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
# APPROVE  (هسته‌ی مشترک: دکمه‌ی ادمین + تایید خودکار با پیامک)
# ============================================================
def approve_payment_core(payment_id):
    """
    پرداخت رو تأیید و اعمال می‌کنه. خروجی: (ok, info)
    فقط برای پرداخت‌های pending یا awaiting کار می‌کنه و با قفل از
    تایید دوباره جلوگیری می‌کنه.
    """
    with _approve_lock:
        payment = db_execute("SELECT * FROM payments WHERE id=?", (payment_id,), fetchone=True)
        if not payment or payment["status"] not in ("pending", "awaiting"):
            return False, "این پرداخت قبلاً بررسی شده."

        payment_type = payment["type"] if "type" in payment.keys() else "purchase"

        # تمدید سرویس / افزایش حجم
        if payment_type in ("renew", "increase"):
            from handlers_renewal import apply_manual_renew_or_increase
            ok, info = apply_manual_renew_or_increase(payment)
            if not ok:
                return False, info
            db_execute("UPDATE payments SET status='approved', updated_at=? WHERE id=?", (now(), payment_id))
            return True, "ok"

        # شارژ استخر حجم نمایندگی
        if payment_type == "reseller":
            from handlers_reseller import apply_reseller_topup
            ok, info = apply_reseller_topup(payment)
            if not ok:
                return False, info
            db_execute("UPDATE payments SET status='approved', updated_at=? WHERE id=?", (now(), payment_id))
            return True, "ok"

        user = db_execute("SELECT * FROM users WHERE id=?", (payment["user_id"],), fetchone=True)

        # شارژ کیف پول (فقط مبلغ پایه، نه مبلغ یکتا)
        if payment["method"] == "wallet":
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
                    parse_mode="HTML",
                    reply_markup=_home_kb()
                )
            return True, "ok"

        # سرویس VPN
        plan = db_execute("SELECT * FROM plans WHERE id=?", (payment["plan_id"],), fetchone=True)
        if not plan or not user:
            return False, "اطلاعات پرداخت ناقص است."
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
            return False, "هیچ پنل فعالی برای ساخت سرویس وجود ندارد."

        custom_username = payment["custom_username"] if "custom_username" in payment.keys() else None

        result = pasarguard_create_service(
            panel=panel,
            telegram_user=user,
            plan=plan,
            desired_username=custom_username
        )
        if not result["success"]:
            return False, f"ساخت سرویس PasarGuard ناموفق بود: {result['error']}"

        service = create_local_service(user=user, plan=plan, panel=panel, result=result)
        db_execute("""
        UPDATE payments
        SET status='approved', service_id=?, updated_at=?
        WHERE id=?
        """, (service["id"], now(), payment_id))

        send_service_delivery(
            user["telegram_id"],
            "🎉 <b>پرداخت شما تأیید شد!</b>",
            plan,
            service["config"]
        )
        return True, "ok"


@bot.callback_query_handler(func=lambda call: call.data.startswith("payapprove:"))
def approve_payment(call):
    if not is_superadmin(call.from_user.id):
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return

    parts = call.data.split(":")
    payment_id = int(parts[1])
    status = parts[2] if len(parts) > 2 else "pending"
    page = parts[3] if len(parts) > 3 else "0"

    ok, info = approve_payment_core(payment_id)
    if not ok:
        bot.answer_callback_query(call.id, f"خطا: {info}", show_alert=True)
        if "ساخت سرویس" in str(info):
            bot.send_message(
                SUPER_ADMIN_ID,
                "⚠️ پرداخت تأیید نشد چون ساخت سرویس موفق نبود.\n\n"
                f"Payment: {payment_id}\nخطا: {info}"
            )
        return

    row = db_execute("SELECT user_id FROM payments WHERE id=?", (payment_id,), fetchone=True)
    if row:
        finish_receipt_screen(row["user_id"])
    bot.answer_callback_query(call.id, "✅ تأیید شد.")
    payment_management_panel(_fake_call(call, f"paymgmt:{status}:{page}"))


# ============================================================
# REJECT
# ============================================================
def _reject_buttons(payment):
    """دکمه‌های پیام ردشدن بر اساس نوع پرداخت."""
    payment_type = payment["type"] if "type" in payment.keys() else "purchase"
    if payment["method"] == "wallet" or payment_type == "wallet":
        return []
    if payment_type in ("renew", "increase"):
        return [("🛡 سرویس‌های من", "services_back")]
    if payment_type == "reseller":
        return [("🤝 پنل نمایندگی", "res_menu")]
    return [("🔄 خرید دوباره", "buy_back_home")]


@bot.callback_query_handler(func=lambda call: call.data.startswith("payreject:"))
def reject_payment(call):
    if not is_superadmin(call.from_user.id):
        return

    parts = call.data.split(":")
    payment_id = int(parts[1])
    status = parts[2] if len(parts) > 2 else "pending"
    page = parts[3] if len(parts) > 3 else "0"

    with _approve_lock:
        payment = db_execute("SELECT * FROM payments WHERE id=?", (payment_id,), fetchone=True)
        if not payment or payment["status"] != "pending":
            bot.answer_callback_query(call.id, "این پرداخت قبلاً بررسی شده.", show_alert=True)
            return
        db_execute("UPDATE payments SET status='rejected', updated_at=? WHERE id=?", (now(), payment_id))

    user = db_execute("SELECT * FROM users WHERE id=?", (payment["user_id"],), fetchone=True)
    if user:
        bot.send_message(
            user["telegram_id"],
            "❌ <b>رسید پرداخت شما رد شد.</b>\n\n"
            "در صورت اشتباه، دوباره اقدام کنید.",
            parse_mode="HTML",
            reply_markup=_home_kb(_reject_buttons(payment))
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
    cc.show(
        call.message.chat.id,
        "🌐 درگاه آنلاین فعال است، اما اتصال نهایی "
        "به API درگاه انتخابی نیاز به مشخصات همان درگاه دارد.",
        key="err"
    )
