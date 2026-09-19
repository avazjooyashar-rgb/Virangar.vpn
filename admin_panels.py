# ============================================================
# admin_panels.py
# مدیریت پنل‌های PasarGuard: افزودن، لیست، تست، فعال/غیرفعال، حذف
# + ویرایش نام/ظرفیت، نمایش و جابجایی پلن‌های هر پنل، تست دسته‌جمعی، صفحه‌بندی
# ============================================================

from telebot import types

from config import bot
from database import db_execute, now
from models import is_admin, is_superadmin
from decorators import admin_only
from pasarguard import pasarguard_test_panel


PANELS_PER_PAGE = 6


@bot.message_handler(func=lambda m: m.text == "🖥 پنل‌ها")
@admin_only
def admin_panels(message):
    kb = types.InlineKeyboardMarkup()

    kb.add(types.InlineKeyboardButton("➕ افزودن پنل", callback_data="panel_add"))
    kb.add(types.InlineKeyboardButton("📋 لیست پنل‌ها", callback_data="panel_list:0"))
    kb.add(types.InlineKeyboardButton("🔄 تست همه‌ی پنل‌ها", callback_data="panel_test_all"))

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


# ---------------- LIST (with pagination) ----------------

@bot.callback_query_handler(func=lambda call: call.data.startswith("panel_list:"))
def panel_list(call):
    if not is_admin(call.from_user.id):
        return

    page = int(call.data.split(":")[1])

    panels = db_execute("SELECT * FROM panels ORDER BY id", fetchall=True)

    if not panels:
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "📭 هنوز پنلی اضافه نشده.")
        return

    total_pages = max(1, (len(panels) + PANELS_PER_PAGE - 1) // PANELS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * PANELS_PER_PAGE
    page_panels = panels[start:start + PANELS_PER_PAGE]

    kb = types.InlineKeyboardMarkup()

    for panel in page_panels:
        status = "🟢" if panel["active"] else "🔴"
        kb.add(
            types.InlineKeyboardButton(
                f"{status} {panel['name']}",
                callback_data=f"panel:{panel['id']}"
            )
        )

    nav_row = []

    if page > 0:
        nav_row.append(
            types.InlineKeyboardButton("◀️ قبلی", callback_data=f"panel_list:{page - 1}")
        )

    nav_row.append(
        types.InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop")
    )

    if page < total_pages - 1:
        nav_row.append(
            types.InlineKeyboardButton("بعدی ▶️", callback_data=f"panel_list:{page + 1}")
        )

    if len(nav_row) > 1:
        kb.row(*nav_row)

    try:
        bot.edit_message_text(
            "🖥 <b>پنل‌ها</b>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb
        )
    except Exception:
        bot.send_message(call.message.chat.id, "🖥 <b>پنل‌ها</b>", reply_markup=kb)

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop(call):
    bot.answer_callback_query(call.id)


# ---------------- DETAILS ----------------

def render_panel_details(chat_id, panel_id, message_id=None):
    panel = db_execute("SELECT * FROM panels WHERE id=?", (panel_id,), fetchone=True)

    if not panel:
        return

    services_count = db_execute(
        "SELECT COUNT(*) c FROM services WHERE panel_id=?",
        (panel_id,), fetchone=True
    )["c"]

    plans = db_execute(
        "SELECT * FROM plans WHERE panel_id=? ORDER BY sort_order, id",
        (panel_id,), fetchall=True
    )

    text = (
        f"🖥 <b>{panel['name']}</b>\n\n"
        f"🆔 ID: {panel['id']}\n"
        f"🌐 URL: {panel['url']}\n"
        f"📌 وضعیت: {panel['status']}\n"
        f"👥 سرویس‌ها: {services_count}\n"
        f"📊 ظرفیت: {panel['capacity']}\n"
        f"🟢 فعال: {'بله' if panel['active'] else 'خیر'}\n\n"
    )

    if plans:
        text += f"📦 <b>پلن‌های این پنل ({len(plans)}):</b>\n"

        for plan in plans:
            plan_active_services = db_execute(
                "SELECT COUNT(*) c FROM services WHERE plan_id=? AND status='active'",
                (plan["id"],), fetchone=True
            )["c"]

            plan_status = "🟢" if plan["active"] else "🔴"
            text += (
                f"{plan_status} {plan['name']} — "
                f"{plan['price']:,} تومان — "
                f"{plan_active_services} سرویس فعال\n"
            )
    else:
        text += "📦 هیچ پلنی به این پنل متصل نیست."

    kb = types.InlineKeyboardMarkup()

    kb.row(
        types.InlineKeyboardButton("✏️ تغییر نام", callback_data=f"panelrename:{panel_id}"),
        types.InlineKeyboardButton("📊 تغییر ظرفیت", callback_data=f"panelcap:{panel_id}")
    )

    kb.row(
        types.InlineKeyboardButton("🔌 تست اتصال", callback_data=f"paneltest:{panel_id}"),
        types.InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"paneltoggle:{panel_id}")
    )

    if plans:
        kb.add(
            types.InlineKeyboardButton(
                "📦 مدیریت/جابجایی پلن‌ها", callback_data=f"panelplans:{panel_id}"
            )
        )

    kb.add(types.InlineKeyboardButton("🗑 حذف پنل", callback_data=f"paneldelete:{panel_id}"))
    kb.add(types.InlineKeyboardButton("⬅️ بازگشت به لیست", callback_data="panel_list:0"))

    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
            return
        except Exception:
            pass

    bot.send_message(chat_id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("panel:"))
def panel_details(call):
    if not is_admin(call.from_user.id):
        return

    panel_id = int(call.data.split(":")[1])
    render_panel_details(call.message.chat.id, panel_id, call.message.message_id)
    bot.answer_callback_query(call.id)


# ---------------- RENAME PANEL ----------------

@bot.callback_query_handler(func=lambda call: call.data.startswith("panelrename:"))
def panel_rename_start(call):
    if not is_admin(call.from_user.id):
        return

    panel_id = int(call.data.split(":")[1])
    panel = db_execute("SELECT * FROM panels WHERE id=?", (panel_id,), fetchone=True)

    if not panel:
        bot.answer_callback_query(call.id, "پنل پیدا نشد.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        call.message.chat.id,
        f"✏️ نام فعلی: <b>{panel['name']}</b>\n\nنام جدید پنل را ارسال کنید:"
    )
    bot.register_next_step_handler(msg, panel_rename_save, panel_id)


def panel_rename_save(message, panel_id):
    new_name = message.text.strip()

    if not new_name:
        bot.send_message(message.chat.id, "❌ نام نمی‌تواند خالی باشد.")
        return

    db_execute(
        "UPDATE panels SET name=?, updated_at=? WHERE id=?",
        (new_name, now(), panel_id)
    )

    bot.send_message(message.chat.id, f"✅ نام پنل به «{new_name}» تغییر کرد.")
    render_panel_details(message.chat.id, panel_id)


# ---------------- EDIT CAPACITY ----------------

@bot.callback_query_handler(func=lambda call: call.data.startswith("panelcap:"))
def panel_capacity_start(call):
    if not is_admin(call.from_user.id):
        return

    panel_id = int(call.data.split(":")[1])
    panel = db_execute("SELECT * FROM panels WHERE id=?", (panel_id,), fetchone=True)

    if not panel:
        bot.answer_callback_query(call.id, "پنل پیدا نشد.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        call.message.chat.id,
        f"📊 ظرفیت فعلی: <b>{panel['capacity']}</b>\n\nظرفیت جدید را به‌صورت عدد ارسال کنید:"
    )
    bot.register_next_step_handler(msg, panel_capacity_save, panel_id)


def panel_capacity_save(message, panel_id):
    text = message.text.strip()

    if not text.isdigit():
        bot.send_message(message.chat.id, "❌ لطفاً فقط عدد ارسال کنید.")
        return

    db_execute(
        "UPDATE panels SET capacity=?, updated_at=? WHERE id=?",
        (int(text), now(), panel_id)
    )

    bot.send_message(message.chat.id, f"✅ ظرفیت به {text} تغییر کرد.")
    render_panel_details(message.chat.id, panel_id)


# ---------------- PLANS PER PANEL / MOVE PLAN ----------------

@bot.callback_query_handler(func=lambda call: call.data.startswith("panelplans:"))
def panel_plans_list(call):
    if not is_admin(call.from_user.id):
        return

    panel_id = int(call.data.split(":")[1])

    plans = db_execute(
        "SELECT * FROM plans WHERE panel_id=? ORDER BY sort_order, id",
        (panel_id,), fetchall=True
    )

    if not plans:
        bot.answer_callback_query(call.id, "این پنل پلنی ندارد.", show_alert=True)
        return

    kb = types.InlineKeyboardMarkup()

    for plan in plans:
        status = "🟢" if plan["active"] else "🔴"
        kb.add(
            types.InlineKeyboardButton(
                f"{status} {plan['name']} ({plan['price']:,} ت)",
                callback_data=f"planmove:{plan['id']}:{panel_id}"
            )
        )

    kb.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data=f"panel:{panel_id}"))

    bot.send_message(
        call.message.chat.id,
        "📦 روی پلنی که می‌خواهید به پنل دیگری منتقل کنید بزنید:",
        reply_markup=kb
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("planmove:"))
def panel_plan_move_targets(call):
    if not is_admin(call.from_user.id):
        return

    _, plan_id, from_panel_id = call.data.split(":")
    plan_id, from_panel_id = int(plan_id), int(from_panel_id)

    plan = db_execute("SELECT * FROM plans WHERE id=?", (plan_id,), fetchone=True)

    if not plan:
        bot.answer_callback_query(call.id, "پلن پیدا نشد.", show_alert=True)
        return

    other_panels = db_execute(
        "SELECT * FROM panels WHERE id != ? ORDER BY name",
        (from_panel_id,), fetchall=True
    )

    if not other_panels:
        bot.answer_callback_query(call.id, "پنل دیگری برای انتقال وجود ندارد.", show_alert=True)
        return

    kb = types.InlineKeyboardMarkup()

    for p in other_panels:
        kb.add(
            types.InlineKeyboardButton(
                p["name"],
                callback_data=f"planmoveto:{plan_id}:{p['id']}:{from_panel_id}"
            )
        )

    kb.add(types.InlineKeyboardButton("⬅️ انصراف", callback_data=f"panelplans:{from_panel_id}"))

    bot.send_message(
        call.message.chat.id,
        f"📦 پلن «{plan['name']}» را به کدام پنل منتقل کنم؟",
        reply_markup=kb
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("planmoveto:"))
def panel_plan_move_confirm(call):
    if not is_admin(call.from_user.id):
        return

    _, plan_id, to_panel_id, from_panel_id = call.data.split(":")
    plan_id, to_panel_id, from_panel_id = int(plan_id), int(to_panel_id), int(from_panel_id)

    db_execute(
        "UPDATE plans SET panel_id=? WHERE id=?",
        (to_panel_id, plan_id)
    )

    to_panel = db_execute("SELECT name FROM panels WHERE id=?", (to_panel_id,), fetchone=True)

    bot.answer_callback_query(call.id, f"✅ پلن به پنل «{to_panel['name']}» منتقل شد.", show_alert=True)
    render_panel_details(call.message.chat.id, to_panel_id)


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

    render_panel_details(call.message.chat.id, panel_id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "panel_test_all")
def panel_test_all(call):
    if not is_admin(call.from_user.id):
        return

    panels = db_execute("SELECT * FROM panels", fetchall=True)

    if not panels:
        bot.answer_callback_query(call.id, "پنلی وجود ندارد.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    status_msg = bot.send_message(call.message.chat.id, f"⏳ در حال تست {len(panels)} پنل...")

    online, offline = 0, 0
    lines = []

    for panel in panels:
        result = pasarguard_test_panel(panel)
        status = "online" if result["success"] else "offline"

        db_execute("UPDATE panels SET status=?, updated_at=? WHERE id=?", (status, now(), panel["id"]))

        if result["success"]:
            online += 1
            lines.append(f"🟢 {panel['name']} — آنلاین")
        else:
            offline += 1
            lines.append(f"🔴 {panel['name']} — آفلاین")

    summary = (
        f"✅ تست تمام پنل‌ها انجام شد.\n\n"
        f"🟢 آنلاین: {online} | 🔴 آفلاین: {offline}\n\n" +
        "\n".join(lines)
    )

    try:
        bot.edit_message_text(summary, status_msg.chat.id, status_msg.message_id)
    except Exception:
        bot.send_message(call.message.chat.id, summary)


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
    render_panel_details(call.message.chat.id, panel_id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("paneldelete:"))
def panel_delete(call):
    if not is_superadmin(call.from_user.id):
        bot.answer_callback_query(call.id, "فقط سوپرادمین می‌تواند پنل را حذف کند.", show_alert=True)
        return

    panel_id = int(call.data.split(":")[1])

    linked_plans = db_execute(
        "SELECT COUNT(*) c FROM plans WHERE panel_id=?",
        (panel_id,), fetchone=True
    )["c"]

    if linked_plans:
        bot.answer_callback_query(
            call.id,
            f"⚠️ این پنل {linked_plans} پلن متصل دارد. اول پلن‌ها را جابجا یا حذف کنید.",
            show_alert=True
        )
        return

    db_execute("DELETE FROM panels WHERE id=?", (panel_id,))
    bot.answer_callback_query(call.id, "پنل حذف شد 🗑")
    bot.send_message(call.message.chat.id, "✅ پنل حذف شد.")
