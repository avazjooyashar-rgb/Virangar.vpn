# ============================================================
# handlers/payment_flow.py
# اطلاع‌رسانی پرداخت جدید به مدیر + تأیید/رد پرداخت
# (هسته‌ی مشترک بین خرید VPN و شارژ کیف پول)
# ============================================================

from telebot import types

from config import bot, SUPER_ADMIN_ID
from db import db_execute, now
from admins import is_superadmin
from pasarguard import pasarguard_create_service, create_local_service


def notify_admin_payment(payment):
    if not payment or not SUPER_ADMIN_ID:
        return

    user = db_execute(
        "SELECT * FROM users WHERE id=?",
        (payment["user_id"],),
        fetchone=True
    )

    plan = None
    if payment["plan_id"]:
        plan = db_execute(
            "SELECT * FROM plans WHERE id=?",
            (payment["plan_id"],),
            fetchone=True
        )

    username = (
        f"@{user['username']}"
        if user and user["username"]
        else "بدون یوزرنیم"
    )

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
        types.InlineKeyboardButton(
            "✅ تأیید", callback_data=f"payapprove:{payment['id']}"
        ),
        types.InlineKeyboardButton(
            "❌ رد", callback_data=f"payreject:{payment['id']}"
        )
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("payapprove:"))
def approve_payment(call):
    if not is_superadmin(call.from_user.id):
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return

    payment_id = int(call.data.split(":")[1])

    payment = db_execute(
        "SELECT * FROM payments WHERE id=?",
        (payment_id,),
        fetchone=True
    )

    if not payment or payment["status"] != "pending":
        bot.answer_callback_query(
            call.id, "این پرداخت قبلاً بررسی شده.", show_alert=True
        )
        return

    # ---------------- Wallet topup ----------------
    if payment["method"] == "wallet":
        user = db_execute(
            "SELECT * FROM users WHERE id=?",
            (payment["user_id"],),
            fetchone=True
        )

        db_execute(
            "UPDATE users SET balance=balance+? WHERE id=?",
            (payment["amount"], payment["user_id"])
        )

        db_execute("""
        INSERT INTO transactions
        (user_id, amount, type, description, reference, created_at)
        VALUES (?, ?, 'credit', ?, ?, ?)
        """, (
            payment["user_id"],
            payment["amount"],
            "شارژ کیف پول",
            f"payment:{payment_id}",
            now()
        ))

        db_execute(
            "UPDATE payments SET status='approved', updated_at=? WHERE id=?",
            (now(), payment_id)
        )

        if user:
            bot.send_message(
                user["telegram_id"],
                f"✅ پرداخت تأیید شد.\n\n"
                f"💰 مبلغ <b>{payment['amount']:,}</b> تومان "
                f"به کیف پول شما اضافه شد."
            )

        bot.edit_message_reply_markup(
            call.message.chat.id, call.message.message_id, reply_markup=None
        )

        bot.answer_callback_query(call.id, "کیف پول شارژ شد ✅")
        return

    # ---------------- VPN service ----------------
    plan = db_execute(
        "SELECT * FROM plans WHERE id=?",
        (payment["plan_id"],),
        fetchone=True
    )

    user = db_execute(
        "SELECT * FROM users WHERE id=?",
        (payment["user_id"],),
        fetchone=True
    )

    if not plan or not user:
        bot.answer_callback_query(
            call.id, "اطلاعات پرداخت ناقص است.", show_alert=True
        )
        return

    panel = None
    if plan["panel_id"]:
        panel = db_execute(
            "SELECT * FROM panels WHERE id=? AND active=1",
            (plan["panel_id"],),
            fetchone=True
        )

    if not panel:
        panel = db_execute("""
        SELECT * FROM panels
        WHERE active=1
        ORDER BY assigned_sales ASC, id ASC
        LIMIT 1
        """, fetchone=True)

    if not panel:
        bot.answer_callback_query(
            call.id, "هیچ پنل فعالی برای ساخت سرویس وجود ندارد.", show_alert=True
        )
        return

    result = pasarguard_create_service(
        panel=panel, telegram_user=user, plan=plan
    )

    if not result["success"]:
        bot.answer_callback_query(
            call.id, "ساخت سرویس انجام نشد.", show_alert=True
        )

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
        f"🔐 کانفیگ:\n"
        f"<code>{service['config']}</code>"
    )

    bot.answer_callback_query(call.id, "پرداخت و سرویس تأیید شد ✅")


@bot.callback_query_handler(func=lambda call: call.data.startswith("payreject:"))
def reject_payment(call):
    if not is_superadmin(call.from_user.id):
        return

    payment_id = int(call.data.split(":")[1])

    payment = db_execute(
        "SELECT * FROM payments WHERE id=?",
        (payment_id,),
        fetchone=True
    )

    if not payment or payment["status"] != "pending":
        bot.answer_callback_query(
            call.id, "این پرداخت قبلاً بررسی شده.", show_alert=True
        )
        return

    db_execute(
        "UPDATE payments SET status='rejected', updated_at=? WHERE id=?",
        (now(), payment_id)
    )

    user = db_execute(
        "SELECT * FROM users WHERE id=?",
        (payment["user_id"],),
        fetchone=True
    )

    if user:
        bot.send_message(
            user["telegram_id"],
            "❌ رسید پرداخت شما رد شد.\n\n"
            "در صورت اشتباه، دوباره اقدام کنید."
        )

    bot.edit_message_reply_markup(
        call.message.chat.id, call.message.message_id, reply_markup=None
    )

    bot.answer_callback_query(call.id, "پرداخت رد شد ❌")
