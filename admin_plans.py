# ============================================================
# admin_plans.py
# مدیریت کامل پلن‌های VPN توسط ادمین / سوپر ادمین
# ============================================================

from telebot import types

from config import bot
from database import db_execute, now
from models import is_admin
from decorators import admin_only


# ============================================================
# TEMPORARY PLAN CREATION STATE
# ============================================================

PLAN_CREATION = {}


def get_state(user_id):
    if user_id not in PLAN_CREATION:
        PLAN_CREATION[user_id] = {
            "step": None,
            "data": {}
        }
    return PLAN_CREATION[user_id]


def clear_state(user_id):
    PLAN_CREATION.pop(user_id, None)


# ============================================================
# KEYBOARDS
# ============================================================

def back_keyboard(callback_data="plan_admin_back"):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data=callback_data
        )
    )
    return kb


def plans_main_keyboard():
    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "➕ افزودن پلن",
            callback_data="plan_admin_add"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "📋 لیست پلن‌ها",
            callback_data="plan_admin_list"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="admin_main"
        )
    )

    return kb


# ============================================================
# MAIN PLAN MENU
# ============================================================

@bot.message_handler(func=lambda m: m.text == "💎 پلن‌های VPN")
@admin_only
def admin_plans(message):

    plans = db_execute(
        """
        SELECT *
        FROM plans
        ORDER BY sort_order ASC, id ASC
        """,
        fetchall=True
    )

    text = "💎 <b>مدیریت پلن‌های VPN</b>\n\n"

    if not plans:
        text += "❌ هنوز هیچ پلنی ساخته نشده است."
    else:
        text += f"📦 تعداد پلن‌ها: <b>{len(plans)}</b>"

    bot.send_message(
        message.chat.id,
        text,
        reply_markup=plans_main_keyboard(),
        parse_mode="HTML"
    )


# ============================================================
# ADD PLAN - START
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "plan_admin_add")
def plan_admin_add(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id

    clear_state(user_id)

    PLAN_CREATION[user_id] = {
        "step": "name",
        "data": {}
    }

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        "➕ <b>افزودن پلن جدید</b>\n\n"
        "🏷 نام پلن را وارد کنید:\n\n"
        "مثال:\n"
        "<code>آلمان ویژه 100GB</code>",
        reply_markup=back_keyboard(),
        parse_mode="HTML"
    )


# ============================================================
# ADD PLAN - TEXT INPUT
# ============================================================

@bot.message_handler(
    func=lambda message:
        message.from_user.id in PLAN_CREATION
        and PLAN_CREATION[message.from_user.id]["step"] is not None
)
def plan_creation_handler(message):

    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    state = PLAN_CREATION.get(user_id)

    if not state:
        return

    step = state["step"]
    value = (message.text or "").strip()

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    if step == "name":

        if not value:
            bot.send_message(
                message.chat.id,
                "❌ نام پلن نمی‌تواند خالی باشد.\n\n"
                "🏷 دوباره نام پلن را وارد کنید:",
                reply_markup=back_keyboard()
            )
            return

        state["data"]["name"] = value
        state["step"] = "description"

        bot.send_message(
            message.chat.id,
            "📝 توضیحات پلن را وارد کنید:\n\n"
            "اگر توضیحی نمی‌خواهید، عبارت <code>ندارد</code> را بفرستید.",
            reply_markup=back_keyboard(),
            parse_mode="HTML"
        )

    # --------------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------------

    elif step == "description":

        if value == "ندارد":
            value = ""

        state["data"]["description"] = value
        state["step"] = "panel"

        show_panel_selection(message.chat.id)

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    elif step == "volume":

        try:
            volume = int(value)
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ حجم باید عدد باشد.\n\n"
                "مثال: <code>100</code>",
                reply_markup=back_keyboard(),
                parse_mode="HTML"
            )
            return

        if volume <= 0:
            bot.send_message(
                message.chat.id,
                "❌ حجم باید بیشتر از صفر باشد.",
                reply_markup=back_keyboard()
            )
            return

        state["data"]["volume"] = volume
        state["step"] = "duration"

        bot.send_message(
            message.chat.id,
            "⏳ مدت اعتبار پلن را به روز وارد کنید:\n\n"
            "مثال: <code>30</code>",
            reply_markup=back_keyboard(),
            parse_mode="HTML"
        )

    # --------------------------------------------------------
    # DURATION
    # --------------------------------------------------------

    elif step == "duration":

        try:
            duration = int(value)
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ مدت باید عدد باشد.\n\n"
                "مثال: <code>30</code>",
                reply_markup=back_keyboard(),
                parse_mode="HTML"
            )
            return

        if duration <= 0:
            bot.send_message(
                message.chat.id,
                "❌ مدت باید بیشتر از صفر باشد.",
                reply_markup=back_keyboard()
            )
            return

        state["data"]["duration"] = duration
        state["step"] = "devices"

        bot.send_message(
            message.chat.id,
            "📱 تعداد دستگاه / کاربر را وارد کنید:\n\n"
            "مثال: <code>2</code>",
            reply_markup=back_keyboard(),
            parse_mode="HTML"
        )

    # --------------------------------------------------------
    # DEVICES
    # --------------------------------------------------------

    elif step == "devices":

        try:
            devices = int(value)
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ تعداد دستگاه باید عدد باشد.\n\n"
                "مثال: <code>2</code>",
                reply_markup=back_keyboard(),
                parse_mode="HTML"
            )
            return

        if devices <= 0:
            bot.send_message(
                message.chat.id,
                "❌ تعداد دستگاه باید بیشتر از صفر باشد.",
                reply_markup=back_keyboard()
            )
            return

        state["data"]["devices"] = devices
        state["step"] = "price"

        bot.send_message(
            message.chat.id,
            "💰 قیمت فروش پلن را به تومان وارد کنید:\n\n"
            "مثال: <code>250000</code>",
            reply_markup=back_keyboard(),
            parse_mode="HTML"
        )

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    elif step == "price":

        try:
            price = int(value)
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ قیمت باید عدد باشد.\n\n"
                "مثال: <code>250000</code>",
                reply_markup=back_keyboard(),
                parse_mode="HTML"
            )
            return

        if price <= 0:
            bot.send_message(
                message.chat.id,
                "❌ قیمت باید بیشتر از صفر باشد.",
                reply_markup=back_keyboard()
            )
            return

        state["data"]["price"] = price
        state["step"] = "reseller_price"

        bot.send_message(
            message.chat.id,
            "🤝 قیمت نماینده را به تومان وارد کنید:\n\n"
            "مثال: <code>220000</code>\n\n"
            "اگر قیمت نماینده ندارید، <code>0</code> وارد کنید.",
            reply_markup=back_keyboard(),
            parse_mode="HTML"
        )

    # --------------------------------------------------------
    # RESELLER PRICE
    # --------------------------------------------------------

    elif step == "reseller_price":

        try:
            reseller_price = int(value)
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ قیمت نماینده باید عدد باشد.",
                reply_markup=back_keyboard()
            )
            return

        if reseller_price < 0:
            bot.send_message(
                message.chat.id,
                "❌ قیمت نماینده نمی‌تواند منفی باشد.",
                reply_markup=back_keyboard()
            )
            return

        state["data"]["reseller_price"] = reseller_price
        state["step"] = "location"

        bot.send_message(
            message.chat.id,
            "📍 لوکیشن پلن را وارد کنید:\n\n"
            "مثال: <code>Germany</code>\n\n"
            "اگر نمی‌خواهید ثبت شود، <code>ندارد</code> بفرستید.",
            reply_markup=back_keyboard(),
            parse_mode="HTML"
        )

    # --------------------------------------------------------
    # LOCATION
    # --------------------------------------------------------

    elif step == "location":

        if value == "ندارد":
            value = ""

        state["data"]["location"] = value
        state["step"] = "preview"

        send_plan_preview(message.chat.id, user_id)


# ============================================================
# PANEL SELECTION
# ============================================================

def show_panel_selection(chat_id):

    panels = db_execute(
        """
        SELECT *
        FROM panels
        WHERE active=1
        ORDER BY id ASC
        """,
        fetchall=True
    )

    kb = types.InlineKeyboardMarkup()

    if not panels:
        kb.add(
            types.InlineKeyboardButton(
                "🔄 تلاش مجدد",
                callback_data="plan_admin_panel_refresh"
            )
        )

        kb.add(
            types.InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="plan_admin_back"
            )
        )

        bot.send_message(
            chat_id,
            "🖥 <b>انتخاب پنل</b>\n\n"
            "❌ هیچ پنل فعالی در دیتابیس وجود ندارد.\n\n"
            "ابتدا یک پنل PasarGuard اضافه و فعال کنید.",
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    for panel in panels:

        status = "🟢"

        kb.add(
            types.InlineKeyboardButton(
                f"{status} {panel['name']}",
                callback_data=f"plan_panel:{panel['id']}"
            )
        )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="plan_admin_back"
        )
    )

    bot.send_message(
        chat_id,
        "🖥 <b>پنل PasarGuard را انتخاب کنید:</b>\n\n"
        "این پلن بعداً برای ساخت سرویس از همین پنل استفاده خواهد کرد.",
        reply_markup=kb,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data == "plan_admin_panel_refresh")
def plan_panel_refresh(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    show_panel_selection(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("plan_panel:"))
def plan_panel_selected(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id

    state = PLAN_CREATION.get(user_id)

    if not state:
        bot.answer_callback_query(
            call.id,
            "❌ فرآیند افزودن پلن منقضی شده است."
        )
        return

    panel_id = int(call.data.split(":")[1])

    panel = db_execute(
        "SELECT * FROM panels WHERE id=? AND active=1",
        (panel_id,),
        fetchone=True
    )

    if not panel:
        bot.answer_callback_query(
            call.id,
            "❌ این پنل دیگر فعال نیست."
        )
        return

    state["data"]["panel_id"] = panel_id
    state["data"]["panel_name"] = panel["name"]
    state["step"] = "volume"

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        f"🖥 پنل انتخاب شد: <b>{panel['name']}</b>\n\n"
        "📦 حجم پلن را به GB وارد کنید:\n\n"
        "مثال: <code>100</code>",
        reply_markup=back_keyboard(),
        parse_mode="HTML"
    )


# ============================================================
# PLAN PREVIEW
# ============================================================

def send_plan_preview(chat_id, user_id):

    state = PLAN_CREATION.get(user_id)

    if not state:
        return

    data = state["data"]

    description = data.get("description") or "ندارد"
    location = data.get("location") or "ندارد"
    reseller_price = data.get("reseller_price", 0)

    text = (
        "👀 <b>پیش‌نمایش پلن</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🏷 نام: <b>{data.get('name')}</b>\n\n"
        f"📝 توضیحات:\n{description}\n\n"
        f"🖥 پنل: <b>{data.get('panel_name', '---')}</b>\n"
        f"📦 حجم: <b>{data.get('volume')} GB</b>\n"
        f"⏳ مدت: <b>{data.get('duration')} روز</b>\n"
        f"📱 دستگاه: <b>{data.get('devices')}</b>\n"
        f"💰 قیمت: <b>{data.get('price'):,} تومان</b>\n"
        f"🤝 قیمت نماینده: <b>{reseller_price:,} تومان</b>\n"
        f"📍 لوکیشن: <b>{location}</b>\n\n"
        "━━━━━━━━━━━━━━\n"
        "آیا اطلاعات صحیح است؟"
    )

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "✅ ساخت پلن",
            callback_data="plan_create_confirm"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "✏️ اصلاح",
            callback_data="plan_edit_start"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="plan_admin_back"
        )
    )

    bot.send_message(
        chat_id,
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# CREATE PLAN
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "plan_create_confirm")
def plan_create_confirm(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = PLAN_CREATION.get(user_id)

    if not state:
        bot.answer_callback_query(
            call.id,
            "❌ اطلاعات ساخت پلن پیدا نشد."
        )
        return

    data = state["data"]

    try:
        db_execute(
            """
            INSERT INTO plans
            (
                name,
                description,
                price,
                volume,
                duration,
                devices,
                reseller_price,
                location,
                panel_id,
                active,
                sort_order,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)
            """,
            (
                data["name"],
                data.get("description", ""),
                data["price"],
                data["volume"],
                data["duration"],
                data["devices"],
                data.get("reseller_price", 0),
                data.get("location", ""),
                data["panel_id"],
                now()
            )
        )

    except Exception as e:

        bot.answer_callback_query(
            call.id,
            "❌ خطا در ساخت پلن"
        )

        bot.send_message(
            call.message.chat.id,
            "❌ <b>ساخت پلن انجام نشد.</b>\n\n"
            f"<code>{str(e)}</code>",
            parse_mode="HTML",
            reply_markup=back_keyboard()
        )

        return

    clear_state(user_id)

    bot.answer_callback_query(
        call.id,
        "✅ پلن ساخته شد"
    )

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "💎 مدیریت پلن‌ها",
            callback_data="plan_admin_home"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="admin_main"
        )
    )

    bot.send_message(
        call.message.chat.id,
        "✅ <b>پلن با موفقیت ساخته شد.</b>\n\n"
        f"💎 {data['name']}",
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# EDIT START
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "plan_edit_start")
def plan_edit_start(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = PLAN_CREATION.get(user_id)

    if not state:
        bot.answer_callback_query(
            call.id,
            "❌ اطلاعات پلن پیدا نشد."
        )
        return

    state["step"] = "edit_menu"

    bot.answer_callback_query(call.id)

    show_edit_menu(
        call.message.chat.id,
        user_id
    )


def show_edit_menu(chat_id, user_id):

    kb = types.InlineKeyboardMarkup()

    fields = [
        ("🏷 نام", "name"),
        ("📝 توضیحات", "description"),
        ("🖥 پنل", "panel"),
        ("📦 حجم", "volume"),
        ("⏳ مدت", "duration"),
        ("📱 دستگاه", "devices"),
        ("💰 قیمت", "price"),
        ("🤝 قیمت نماینده", "reseller_price"),
        ("📍 لوکیشن", "location"),
    ]

    for title, field in fields:
        kb.add(
            types.InlineKeyboardButton(
                title,
                callback_data=f"plan_edit_field:{field}"
            )
        )

    kb.add(
        types.InlineKeyboardButton(
            "👀 پیش‌نمایش",
            callback_data="plan_edit_preview"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="plan_admin_back"
        )
    )

    bot.send_message(
        chat_id,
        "✏️ <b>کدام قسمت را می‌خواهید اصلاح کنید؟</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("plan_edit_field:"))
def plan_edit_field(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = PLAN_CREATION.get(user_id)

    if not state:
        return

    field = call.data.split(":")[1]

    if field == "panel":
        state["step"] = "panel"
        bot.answer_callback_query(call.id)
        show_panel_selection(call.message.chat.id)
        return

    state["step"] = field

    prompts = {
        "name": "🏷 نام جدید پلن را وارد کنید:",
        "description": "📝 توضیحات جدید را وارد کنید:",
        "volume": "📦 حجم جدید را به GB وارد کنید:",
        "duration": "⏳ مدت جدید را به روز وارد کنید:",
        "devices": "📱 تعداد دستگاه جدید را وارد کنید:",
        "price": "💰 قیمت جدید را به تومان وارد کنید:",
        "reseller_price": "🤝 قیمت نماینده جدید را وارد کنید:",
        "location": "📍 لوکیشن جدید را وارد کنید:",
    }

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        prompts.get(field, "مقدار جدید را وارد کنید:"),
        reply_markup=back_keyboard("plan_edit_back"),
        parse_mode="HTML"
    )


# ============================================================
# EDIT PREVIEW
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "plan_edit_preview")
def plan_edit_preview(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    send_plan_preview(
        call.message.chat.id,
        call.from_user.id
    )


# ============================================================
# PLAN LIST
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "plan_admin_list")
def plan_admin_list(call):

    if not is_admin(call.from_user.id):
        return

    plans = db_execute(
        """
        SELECT *
        FROM plans
        ORDER BY sort_order ASC, id ASC
        """,
        fetchall=True
    )

    kb = types.InlineKeyboardMarkup()

    if not plans:

        kb.add(
            types.InlineKeyboardButton(
                "➕ افزودن پلن",
                callback_data="plan_admin_add"
            )
        )

    else:

        for plan in plans:

            status = "🟢" if plan["active"] else "🔴"

            kb.add(
                types.InlineKeyboardButton(
                    f"{status} {plan['name']}",
                    callback_data=f"planadmin:{plan['id']}"
                )
            )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="plan_admin_home"
        )
    )

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        "📋 <b>لیست پلن‌های VPN</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# PLAN DETAILS
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("planadmin:"))
def plan_admin_details(call):

    if not is_admin(call.from_user.id):
        return

    plan_id = int(call.data.split(":")[1])

    plan = db_execute(
        """
        SELECT
            plans.*,
            panels.name AS panel_name
        FROM plans
        LEFT JOIN panels
            ON panels.id = plans.panel_id
        WHERE plans.id=?
        """,
        (plan_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(
            call.id,
            "❌ پلن پیدا نشد."
        )
        return

    description = plan["description"] or "ندارد"
    location = plan["location"] or "ندارد"
    panel_name = plan["panel_name"] or "بدون پنل"

    status = "🟢 فعال" if plan["active"] else "🔴 غیرفعال"

    text = (
        f"💎 <b>{plan['name']}</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📝 توضیحات:\n{description}\n\n"
        f"💰 قیمت: <b>{plan['price']:,} تومان</b>\n"
        f"📊 حجم: <b>{plan['volume']} GB</b>\n"
        f"⏳ مدت: <b>{plan['duration']} روز</b>\n"
        f"📱 دستگاه: <b>{plan['devices']}</b>\n"
        f"🤝 قیمت نماینده: <b>{plan['reseller_price']:,} تومان</b>\n"
        f"📍 لوکیشن: <b>{location}</b>\n"
        f"🖥 پنل: <b>{panel_name}</b>\n"
        f"📌 وضعیت: <b>{status}</b>\n\n"
        "━━━━━━━━━━━━━━"
    )

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "✏️ ویرایش",
            callback_data=f"plan_edit:{plan_id}"
        )
    )

    if plan["active"]:
        kb.add(
            types.InlineKeyboardButton(
                "🔴 غیرفعال کردن",
                callback_data=f"plan_toggle:{plan_id}"
            )
        )
    else:
        kb.add(
            types.InlineKeyboardButton(
                "🟢 فعال کردن",
                callback_data=f"plan_toggle:{plan_id}"
            )
        )

    kb.add(
        types.InlineKeyboardButton(
            "🗑 حذف",
            callback_data=f"plan_delete:{plan_id}"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="plan_admin_list"
        )
    )

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# TOGGLE PLAN
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("plan_toggle:"))
def plan_toggle(call):

    if not is_admin(call.from_user.id):
        return

    plan_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT active FROM plans WHERE id=?",
        (plan_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(
            call.id,
            "❌ پلن پیدا نشد."
        )
        return

    new_status = 0 if plan["active"] else 1

    db_execute(
        "UPDATE plans SET active=? WHERE id=?",
        (new_status, plan_id)
    )

    bot.answer_callback_query(
        call.id,
        "✅ وضعیت پلن تغییر کرد."
    )

    # دوباره جزئیات را نمایش بده
    fake_call = call
    fake_call.data = f"planadmin:{plan_id}"
    plan_admin_details(fake_call)


# ============================================================
# DELETE PLAN
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("plan_delete:"))
def plan_delete(call):

    if not is_admin(call.from_user.id):
        return

    plan_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT name FROM plans WHERE id=?",
        (plan_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(
            call.id,
            "❌ پلن پیدا نشد."
        )
        return

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "⚠️ بله، حذف شود",
            callback_data=f"plan_delete_confirm:{plan_id}"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 انصراف",
            callback_data=f"planadmin:{plan_id}"
        )
    )

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        f"⚠️ <b>حذف پلن</b>\n\n"
        f"💎 {plan['name']}\n\n"
        "آیا مطمئن هستید؟",
        reply_markup=kb,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("plan_delete_confirm:"))
def plan_delete_confirm(call):

    if not is_admin(call.from_user.id):
        return

    plan_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT name FROM plans WHERE id=?",
        (plan_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(
            call.id,
            "❌ پلن پیدا نشد."
        )
        return

    # اگر سرویس قبلی به این پلن وصل باشد،
    # به خاطر Foreign Key حذف مستقیم ممکن است خطا بدهد.
    services = db_execute(
        "SELECT COUNT(*) AS count FROM services WHERE plan_id=?",
        (plan_id,),
        fetchone=True
    )

    if services and services["count"] > 0:

        bot.answer_callback_query(
            call.id,
            "⚠️ این پلن سرویس دارد و حذف نشد."
        )

        bot.send_message(
            call.message.chat.id,
            "⚠️ <b>این پلن قابل حذف نیست.</b>\n\n"
            f"💎 {plan['name']}\n"
            f"📦 تعداد سرویس‌های ساخته‌شده: "
            f"<b>{services['count']}</b>\n\n"
            "برای جلوگیری از خراب شدن سابقه سرویس‌ها، "
            "پلن را به‌جای حذف، غیرفعال کنید.",
            reply_markup=back_keyboard("plan_admin_list"),
            parse_mode="HTML"
        )

        return

    db_execute(
        "DELETE FROM plans WHERE id=?",
        (plan_id,)
    )

    bot.answer_callback_query(
        call.id,
        "✅ پلن حذف شد."
    )

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "📋 لیست پلن‌ها",
            callback_data="plan_admin_list"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="plan_admin_home"
        )
    )

    bot.send_message(
        call.message.chat.id,
        "✅ پلن با موفقیت حذف شد.",
        reply_markup=kb
    )


# ============================================================
# EDIT EXISTING PLAN
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("plan_edit:"))
def plan_edit_existing(call):

    if not is_admin(call.from_user.id):
        return

    plan_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT * FROM plans WHERE id=?",
        (plan_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(
            call.id,
            "❌ پلن پیدا نشد."
        )
        return

    user_id = call.from_user.id

    PLAN_CREATION[user_id] = {
        "step": "edit_menu",
        "data": {
            "editing_plan_id": plan_id,
            "name": plan["name"],
            "description": plan["description"] or "",
            "price": plan["price"],
            "volume": plan["volume"],
            "duration": plan["duration"],
            "devices": plan["devices"],
            "reseller_price": plan["reseller_price"],
            "location": plan["location"] or "",
            "panel_id": plan["panel_id"],
        }
    }

    if plan["panel_id"]:

        panel = db_execute(
            "SELECT name FROM panels WHERE id=?",
            (plan["panel_id"],),
            fetchone=True
        )

        if panel:
            PLAN_CREATION[user_id]["data"]["panel_name"] = panel["name"]

    bot.answer_callback_query(call.id)

    show_edit_menu(
        call.message.chat.id,
        user_id
    )


# ============================================================
# SAVE EDITED PLAN
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "plan_save_edit")
def plan_save_edit(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = PLAN_CREATION.get(user_id)

    if not state:
        return

    data = state["data"]
    plan_id = data.get("editing_plan_id")

    if not plan_id:
        return

    db_execute(
        """
        UPDATE plans
        SET
            name=?,
            description=?,
            price=?,
            volume=?,
            duration=?,
            devices=?,
            reseller_price=?,
            location=?,
            panel_id=?
        WHERE id=?
        """,
        (
            data["name"],
            data.get("description", ""),
            data["price"],
            data["volume"],
            data["duration"],
            data["devices"],
            data.get("reseller_price", 0),
            data.get("location", ""),
            data.get("panel_id"),
            plan_id
        )
    )

    clear_state(user_id)

    bot.answer_callback_query(
        call.id,
        "✅ پلن ویرایش شد."
    )

    fake_call = call
    fake_call.data = f"planadmin:{plan_id}"
    plan_admin_details(fake_call)


# ============================================================
# EDIT BACK
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "plan_edit_back")
def plan_edit_back(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = PLAN_CREATION.get(user_id)

    if not state:
        bot.answer_callback_query(call.id)
        return

    state["step"] = "edit_menu"

    bot.answer_callback_query(call.id)

    show_edit_menu(
        call.message.chat.id,
        user_id
    )


# ============================================================
# GENERAL BACK
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "plan_admin_back")
def plan_admin_back(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id

    state = PLAN_CREATION.get(user_id)

    # اگر وسط ساخت پلن هستیم، یک مرحله به عقب برو
    if state and state.get("step"):

        step = state["step"]

        previous_steps = {
            "description": "name",
            "panel": "description",
            "volume": "panel",
            "duration": "volume",
            "devices": "duration",
            "price": "devices",
            "reseller_price": "price",
            "location": "reseller_price",
            "preview": "location",
        }

        previous = previous_steps.get(step)

        if previous:
            state["step"] = previous

            bot.answer_callback_query(call.id)

            if previous == "name":
                bot.send_message(
                    call.message.chat.id,
                    "🏷 نام پلن را وارد کنید:",
                    reply_markup=back_keyboard(),
                )

            elif previous == "description":
                bot.send_message(
                    call.message.chat.id,
                    "📝 توضیحات پلن را وارد کنید:",
                    reply_markup=back_keyboard(),
                )

            elif previous == "panel":
                show_panel_selection(call.message.chat.id)

            elif previous == "volume":
                bot.send_message(
                    call.message.chat.id,
                    "📦 حجم پلن را به GB وارد کنید:",
                    reply_markup=back_keyboard()
                )

            elif previous == "duration":
                bot.send_message(
                    call.message.chat.id,
                    "⏳ مدت اعتبار را به روز وارد کنید:",
                    reply_markup=back_keyboard()
                )

            elif previous == "devices":
                bot.send_message(
                    call.message.chat.id,
                    "📱 تعداد دستگاه را وارد کنید:",
                    reply_markup=back_keyboard()
                )

            elif previous == "price":
                bot.send_message(
                    call.message.chat.id,
                    "💰 قیمت پلن را به تومان وارد کنید:",
                    reply_markup=back_keyboard()
                )

            elif previous == "reseller_price":
                bot.send_message(
                    call.message.chat.id,
                    "🤝 قیمت نماینده را وارد کنید:",
                    reply_markup=back_keyboard()
                )

            elif previous == "location":
                bot.send_message(
                    call.message.chat.id,
                    "📍 لوکیشن پلن را وارد کنید:",
                    reply_markup=back_keyboard()
                )

            return

    clear_state(user_id)

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        "💎 <b>مدیریت پلن‌های VPN</b>",
        reply_markup=plans_main_keyboard(),
        parse_mode="HTML"
    )


# ============================================================
# PLAN ADMIN HOME
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "plan_admin_home")
def plan_admin_home(call):

    if not is_admin(call.from_user.id):
        return

    clear_state(call.from_user.id)

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        "💎 <b>مدیریت پلن‌های VPN</b>",
        reply_markup=plans_main_keyboard(),
        parse_mode="HTML"
    )
