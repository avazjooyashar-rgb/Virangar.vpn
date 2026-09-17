# ============================================================
# handlers_payment.py
# پرداخت کارت به کارت، آنلاین، تأیید/رد توسط مدیر
# ============================================================

from telebot import types

from config import bot, SUPER_ADMIN_ID
from database import db_execute, get_setting, now
from models import internal_user_id, is_superadmin
from pasarguard import pasarguard_create_service
from services import create_local_service


# ============================================================
# MANUAL PAYMENT (plan purchase)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("manual:"))
def manual_payment(call):
    plan_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT * FROM plans WHERE id=? AND active=1",
        (plan_id,),
        fetchone=True
    )

    if not plan:
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

    bot.send_message(call.message.chat.id, text)

    bot.register_next_step_handler(
        call.message,
        receive_plan_receipt,
        plan_id
    )


def receive_plan_receipt(message, plan_id):
    if not message.photo:
        bot.send_message(message.chat.id, "❌ لطفاً تصویر رسید را ارسال کن.")
        bot.register_next_step_handler(message, receive_plan_receipt, plan_id)
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
     status, created_at, updated_at)
    VALUES (?, ?, ?, 'manual', ?, 'photo',
            'pending', ?, ?)
    """, (
        user_id, plan_id, plan["price"], file_id, now(), now()
    ))

    payment = db_execute("""
    SELECT * FROM payments
    WHERE user_id=? AND plan_id=? AND status='pending'
    ORDER BY id DESC LIMIT 1
    """, (user_id, plan_id), fetchone=True)

    notify_admin_payment(payment)

    bot.send_message(
        message.chat.id,
        "✅ رسید شما ثبت شد.\n\n"
        "⏳ پرداخت در انتظار بررسی مدیریت است."
    )


# ============================================================
# ADMIN NOTIFICATION
# ============================================================

def notify_admin_payment(payment):
    if not payment or not SUPER_ADMIN_ID:
        return

    user = db_execute("SELECT * FROM users WHERE id=?", (payment["user_id"],), fetchone=True)

    plan = None
    if payment["plan_id"]:
        plan = db_execute("SELECT * FROM plans WHERE id=?", (payment["plan_id"],), fetchone=True)

    username = f"@{user['username']}" if user and user["username"] else "بدون یوزرنیم"

    text = (
        "💳 <b>درخواست پرداخت جدید</b>\n\n"
        f"🆔 Payment: <code>{payment['id']}</code>\n"
        f"👤 کاربر: {username}\n"
        f"🆔 Telegram ID: <code>{user['telegram_id']}</code>\n"
        f"💰 مبلغ: {payment['amount']:,} تومان\n"
        f"📦 پلن: {plan['name'] if plan else '---'}\n"
        f"📌 روش: {payment['method']}"
    )

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ تأیید", callback_data=f"payapprove:{payment['id']}"),
        types.InlineKeyboardButton("❌ رد", callback_data=f"payreject:{payment['id']}")
    )

    bot.send_message(SUPER_ADMIN_ID, text, reply_markup=kb)

    if payment["receipt_file_id"]:
        try:
            bot.send_photo(
                SUPER_ADMIN_ID,
                payment["receipt_file_id"],
                caption="🧾 رسید پرداخت"
            )
        except Exception:
            pass


# ============================================================
# APPROVE
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("payapprove:"))
def approve_payment(call):
    if not is_superadmin(call.from_user.id):
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return

    payment_id = int(call.data.split(":")[1])

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
                f"✅ پرداخت تأیید شد.\n\n"
                f"💰 مبلغ <b>{payment['amount']:,}</b> تومان "
                f"به کیف پول شما اضافه شد."
            )

        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.answer_callback_query(call.id, "کیف پول شارژ شد ✅")
        return

    # VPN service
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

    # Real PasarGuard service creation requires the actual PasarGuard API endpoint/schema.
    result = pasarguard_create_service(panel=panel, telegram_user=user, plan=plan)

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
        f"⏳ مدت: {plan['duration']} روز\n"
        f"📊 حجم: {plan['volume']} GB\n\n"
        f"🔗 لینک اشتراک:\n"
        f"<code>{service['config']}</code>"
    )

    bot.answer_callback_query(call.id, "پرداخت و سرویس تأیید شد ✅")


# ============================================================
# REJECT
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("payreject:"))
def reject_payment(call):
    if not is_superadmin(call.from_user.id):
        return

    payment_id = int(call.data.split(":")[1])

    payment = db_execute("SELECT * FROM payments WHERE id=?", (payment_id,), fetchone=True)

    if not payment or payment["status"] != "pending":
        bot.answer_callback_query(call.id, "این پرداخت قبلاً بررسی شده.", show_alert=True)
        return

    db_execute("UPDATE payments SET status='rejected', updated_at=? WHERE id=?", (now(), payment_id))

    user = db_execute("SELECT * FROM users WHERE id=?", (payment["user_id"],), fetchone=True)

    if user:
        bot.send_message(
            user["telegram_id"],
            "❌ رسید پرداخت شما رد شد.\n\n"
            "در صورت اشتباه، دوباره اقدام کنید."
        )

    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.answer_callback_query(call.id, "پرداخت رد شد ❌")


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
