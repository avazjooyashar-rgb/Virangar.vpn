# ============================================================
# admin_panels.py
# مدیریت پنل‌های PasarGuard: افزودن، لیست، تست، فعال/غیرفعال، حذف
# ============================================================

from telebot import types

from config import bot
from database import db_execute, now
from models import is_admin, is_superadmin
from decorators import admin_only
from pasarguard import pasarguard_test_panel


@bot.message_handler(func=lambda m: m.text == "🖥 پنل‌ها")
@admin_only
def admin_panels(message):
    kb = types.InlineKeyboardMarkup()

    kb.add(types.InlineKeyboardButton("➕ افزودن پنل", callback_data="panel_add"))
    kb.add(types.InlineKeyboardButton("📋 لیست پنل‌ها", callback_data="panel_list"))

    bot.send_message(
        message.chat.id,
        "🖥 <b>مدیریت پنل‌های PasarGuard</b>\n\n"
        "اتصال پنل‌ها از این قسمت مدیریت می‌شود.",
        reply_markup=kb
    )


# ---------------- ADD PANEL WIZARD ----------------

@bot.callback_query_handler(func=lambda call: call.data == "panel_add")
def panel_add(call):
    if not is_admin(call.from_user.id):
        return

    bot.send_message(call.message.chat.id, "🖥 نام پنل را ارسال کنید:")
    bot.register_next_step_handler(call.message, panel_add_name)


def panel_add_name(message):
    name = message.text.strip()
    bot.send_message(
        message.chat.id,
        "🌐 آدرس پنل را با پروتکل و پورت ارسال کنید:\n"
        "مثال: <code>https://panel.example.com:8443</code>"
    )
    bot.register_next_step_handler(message, panel_add_url, name)


def panel_add_url(message, name):
    url = message.text.strip()
    bot.send_message(
        message.chat.id,
        "👤 یوزرنیم ادمین پنل را ارسال کنید:\n\n"
        "⚠️ باید یک ادمین <b>sudo</b> باشد نه اپراتور محدود، "
        "چون برای ساخت کاربر لازم است ربات به همه‌ی گروه‌های پنل دسترسی داشته باشد."
    )
    bot.register_next_step_handler(message, panel_add_username, name, url)


def panel_add_username(message, name, url):
    username = message.text.strip()
    bot.send_message(message.chat.id, "🔐 Password پنل را ارسال کنید:")
    bot.register_next_step_handler(message, panel_add_password, name, url, username)


def panel_add_password(message, name, url, username):
    password = message.text.strip()

    db_execute("""
    INSERT INTO panels
    (name, url, username, password,
     active, status, capacity,
     assigned_sales, created_at, updated_at)
    VALUES (?, ?, ?, ?, 1, 'unknown', 0, 0, ?, ?)
    """, (
        name, url, username, password, now(), now()
    ))

    panel = db_execute("""
    SELECT * FROM panels
    WHERE name=? AND url=? AND username=?
    ORDER BY id DESC LIMIT 1
    """, (name, url, username), fetchone=True)

    bot.send_message(message.chat.id, "⏳ در حال تست اتصال واقعی به پنل...")

    result = pasarguard_test_panel(panel)

    if result["success"]:
        status = "online"

        db_execute(
            "UPDATE panels SET status=?, updated_at=? WHERE id=?",
            (status, now(), panel["id"])
        )

        sudo_note = (
            "✅ ادمین sudo است."
            if result.get("is_sudo")
            else "⚠️ این ادمین sudo نیست — ممکن است ساخت سرویس با خطا مواجه شود."
        )

        bot.send_message(
            message.chat.id,
            "✅ <b>پنل با موفقیت اضافه و به آن متصل شد!</b>\n\n"
            f"👤 لاگین به‌عنوان: {result.get('admin_username', '---')}\n"
            f"{sudo_note}"
        )
    else:
        status = "offline"

        db_execute(
            "UPDATE panels SET status=?, updated_at=? WHERE id=?",
            (status, now(), panel["id"])
        )

        bot.send_message(
            message.chat.id,
            "⚠️ <b>پنل به دیتابیس اضافه شد، اما اتصال ناموفق بود.</b>\n\n"
            f"❌ خطا: <code>{result['error']}</code>\n\n"
            "آدرس/یوزرنیم/پسورد رو بررسی کن و از منوی «🖥 پنل‌ها» "
            "روی «🔌 تست اتصال» بزن تا دوباره امتحان کنی."
        )


# ---------------- LIST / DETAILS ----------------

@bot.callback_query_handler(func=lambda call: call.data == "panel_list")
def panel_list(call):
    if not is_admin(call.from_user.id):
        return

    panels = db_execute("SELECT * FROM panels ORDER BY id", fetchall=True)

    if not panels:
        bot.send_message(call.message.chat.id, "📭 هنوز پنلی اضافه نشده.")
        return

    kb = types.InlineKeyboardMarkup()

    for panel in panels:
        status = "🟢" if panel["active"] else "🔴"
        kb.add(
            types.InlineKeyboardButton(
                f"{status} {panel['name']}",
                callback_data=f"panel:{panel['id']}"
            )
        )

    bot.send_message(call.message.chat.id, "🖥 <b>پنل‌ها</b>", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("panel:"))
def panel_details(call):
    if not is_admin(call.from_user.id):
        return

    panel_id = int(call.data.split(":")[1])

    panel = db_execute("SELECT * FROM panels WHERE id=?", (panel_id,), fetchone=True)

    if not panel:
        return

    users = db_execute(
        "SELECT COUNT(*) c FROM services WHERE panel_id=?",
        (panel_id,), fetchone=True
    )["c"]

    text = (
        f"🖥 <b>{panel['name']}</b>\n\n"
        f"🆔 ID: {panel['id']}\n"
        f"🌐 URL: {panel['url']}\n"
        f"📌 وضعیت: {panel['status']}\n"
        f"👥 سرویس‌ها: {users}\n"
        f"📊 ظرفیت: {panel['capacity']}\n"
        f"🟢 فعال: {'بله' if panel['active'] else 'خیر'}"
    )

    kb = types.InlineKeyboardMarkup()

    kb.row(
        types.InlineKeyboardButton("🔌 تست اتصال", callback_data=f"paneltest:{panel_id}"),
        types.InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"paneltoggle:{panel_id}")
    )

    kb.add(types.InlineKeyboardButton("🗑 حذف پنل", callback_data=f"paneldelete:{panel_id}"))

    bot.send_message(call.message.chat.id, text, reply_markup=kb)


# ---------------- TEST / TOGGLE / DELETE ----------------

@bot.callback_query_handler(func=lambda call: call.data.startswith("paneltest:"))
def panel_test(call):
    if not is_admin(call.from_user.id):
        return

    panel_id = int(call.data.split(":")[1])
    panel = db_execute("SELECT * FROM panels WHERE id=?", (panel_id,), fetchone=True)

    if not panel:
        return

    result = pasarguard_test_panel(panel)
    status = "online" if result["success"] else "offline"

    db_execute("UPDATE panels SET status=?, updated_at=? WHERE id=?", (status, now(), panel_id))

    if result["success"]:
        sudo_text = "sudo ✅" if result.get("is_sudo") else "sudo ❌ (اپراتور محدود)"

        bot.answer_callback_query(
            call.id,
            f"اتصال موفق بود ✅\n"
            f"ادمین: {result.get('admin_username', '---')}\n"
            f"{sudo_text}",
            show_alert=True
        )
    else:
        bot.answer_callback_query(call.id, f"اتصال ناموفق: {result['error']}", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith("paneltoggle:"))
def panel_toggle(call):
    if not is_admin(call.from_user.id):
        return

    panel_id = int(call.data.split(":")[1])
    panel = db_execute("SELECT active FROM panels WHERE id=?", (panel_id,), fetchone=True)

    if not panel:
        return

    new_status = 0 if panel["active"] else 1

    db_execute("UPDATE panels SET active=?, updated_at=? WHERE id=?", (new_status, now(), panel_id))
    bot.answer_callback_query(call.id, "تغییر کرد ✅")


@bot.callback_query_handler(func=lambda call: call.data.startswith("paneldelete:"))
def panel_delete(call):
    if not is_superadmin(call.from_user.id):
        return

    panel_id = int(call.data.split(":")[1])
    db_execute("DELETE FROM panels WHERE id=?", (panel_id,))
    bot.answer_callback_query(call.id, "پنل حذف شد 🗑")
