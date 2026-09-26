# ============================================================
# admin_plans.py
# مدیریت کامل پلن‌های VPN + پلن‌های افزایش حجم توسط ادمین / سوپر ادمین
# ============================================================

import traceback

from telebot import types

from config import bot
from database import db_execute, now
from models import is_admin
from decorators import admin_only


# ============================================================
# TEMPORARY PLAN CREATION STATE (پلن‌های خرید)
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


def is_editing(state):
    """
    True اگر داریم یک فیلد از یک پلنِ از قبل موجود را ویرایش می‌کنیم
    (نه اینکه در حال ساخت پلن جدید هستیم).
    """
    return bool(state.get("data", {}).get("editing_plan_id"))


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
            "⚡️ پلن‌های افزایش حجم",
            callback_data="renewal_admin_home"
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

@bot.message_handler(func=lambda m: m.text == "💎 مدیریت پلن‌های VPN")
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

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if not is_admin(call.from_user.id):
        bot.send_message(
            call.message.chat.id,
            "⛔️ دسترسی رد شد: is_admin() برای user_id "
            f"<code>{call.from_user.id}</code> مقدار False برگردوند."
        )
        return

    try:
        user_id = call.from_user.id

        clear_state(user_id)

        PLAN_CREATION[user_id] = {
            "step": "name",
            "data": {}
        }

        bot.send_message(
            call.message.chat.id,
            "➕ <b>افزودن پلن جدید</b>\n\n"
            "🏷 نام پلن را وارد کنید:\n\n"
            "مثال:\n"
            "<code>آلمان ویژه 100GB</code>",
            reply_markup=back_keyboard(),
            parse_mode="HTML"
        )

    except Exception:
        err = traceback.format_exc()
        bot.send_message(
            call.message.chat.id,
            "❌ خطا در شروع افزودن پلن:\n\n"
            f"<code>{err[-3500:]}</code>",
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
    editing = is_editing(state)

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

        if editing:
            state["step"] = "edit_menu"
            show_edit_menu(message.chat.id, user_id)
            return

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

        if editing:
            state["step"] = "edit_menu"
            show_edit_menu(message.chat.id, user_id)
            return

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

        if editing:
            state["step"] = "edit_menu"
            show_edit_menu(message.chat.id, user_id)
            return

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

        if editing:
            state["step"] = "edit_menu"
            show_edit_menu(message.chat.id, user_id)
            return

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

        if editing:
            state["step"] = "edit_menu"
            show_edit_menu(message.chat.id, user_id)
            return

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

        if editing:
            state["step"] = "edit_menu"
            show_edit_menu(message.chat.id, user_id)
            return

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

        if editing:
            state["step"] = "edit_menu"
            show_edit_menu(message.chat.id, user_id)
            return

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

        if editing:
            state["step"] = "edit_menu"
            show_edit_menu(message.chat.id, user_id)
            return

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

    bot.answer_callback_query(call.id)

    if is_editing(state):
        state["step"] = "edit_menu"
        show_edit_menu(call.message.chat.id, user_id)
        return

    state["step"] = "volume"

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

    state = PLAN_CREATION.get(user_id, {})
    if is_editing(state):
        kb.add(
            types.InlineKeyboardButton(
                "💾 ذخیره تغییرات",
                callback_data="plan_save_edit"
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


# ============================================================
# ============================================================
# VOLUME-INCREASE PLANS — مدیریت مستقل پلن‌های افزایش حجم
# همون ساختار بالا، فقط روی جدول renewal_plans
# (نام جدول و callback ها به دلایل سازگاری با کد قبلی renewal مانده،
#  فقط متن‌های نمایشی به «افزایش حجم» تغییر کرده است)
# ============================================================
# ============================================================

RENEWAL_CREATION = {}


def get_renewal_state(user_id):
    if user_id not in RENEWAL_CREATION:
        RENEWAL_CREATION[user_id] = {
            "step": None,
            "data": {}
        }
    return RENEWAL_CREATION[user_id]


def clear_renewal_state(user_id):
    RENEWAL_CREATION.pop(user_id, None)


def is_editing_renewal(state):
    return bool(state.get("data", {}).get("editing_renewal_id"))


def renewal_back_keyboard(callback_data="renewal_admin_back"):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data=callback_data
        )
    )
    return kb


def renewal_main_keyboard():
    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "➕ افزودن پلن افزایش حجم",
            callback_data="renewal_admin_add"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "📋 لیست پلن‌های افزایش حجم",
            callback_data="renewal_admin_list"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="plan_admin_home"
        )
    )

    return kb


# ============================================================
# VOLUME-INCREASE — HOME
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "renewal_admin_home")
def renewal_admin_home(call):

    if not is_admin(call.from_user.id):
        return

    clear_renewal_state(call.from_user.id)

    plans = db_execute(
        "SELECT * FROM renewal_plans ORDER BY sort_order ASC, id ASC",
        fetchall=True
    )

    text = "⚡️ <b>مدیریت پلن‌های افزایش حجم</b>\n\n"

    if not plans:
        text += "❌ هنوز هیچ پلن افزایش حجمی ساخته نشده است."
    else:
        text += f"📦 تعداد پلن‌های افزایش حجم: <b>{len(plans)}</b>"

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=renewal_main_keyboard(),
        parse_mode="HTML"
    )


# ============================================================
# VOLUME-INCREASE — ADD START
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "renewal_admin_add")
def renewal_admin_add(call):

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id

    clear_renewal_state(user_id)

    RENEWAL_CREATION[user_id] = {
        "step": "name",
        "data": {}
    }

    bot.send_message(
        call.message.chat.id,
        "⚡️ <b>افزودن پلن افزایش حجم جدید</b>\n\n"
        "🏷 نام پلن افزایش حجم را وارد کنید:\n\n"
        "مثال:\n"
        "<code>افزایش حجم 50GB</code>",
        reply_markup=renewal_back_keyboard(),
        parse_mode="HTML"
    )


# ============================================================
# VOLUME-INCREASE — TEXT INPUT (WIZARD)
# ============================================================

@bot.message_handler(
    func=lambda message:
        message.from_user.id in RENEWAL_CREATION
        and RENEWAL_CREATION[message.from_user.id]["step"] is not None
)
def renewal_creation_handler(message):

    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    state = RENEWAL_CREATION.get(user_id)

    if not state:
        return

    step = state["step"]
    value = (message.text or "").strip()
    editing = is_editing_renewal(state)

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    if step == "name":

        if not value:
            bot.send_message(
                message.chat.id,
                "❌ نام پلن نمی‌تواند خالی باشد.\n\n"
                "🏷 دوباره نام پلن افزایش حجم را وارد کنید:",
                reply_markup=renewal_back_keyboard()
            )
            return

        state["data"]["name"] = value

        if editing:
            state["step"] = "edit_menu"
            show_renewal_edit_menu(message.chat.id, user_id)
            return

        state["step"] = "description"

        bot.send_message(
            message.chat.id,
            "📝 توضیحات پلن افزایش حجم را وارد کنید:\n\n"
            "اگر نمی‌خواهید، عبارت <code>ندارد</code> را بفرستید.",
            reply_markup=renewal_back_keyboard(),
            parse_mode="HTML"
        )

    # --------------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------------

    elif step == "description":

        if value == "ندارد":
            value = ""

        state["data"]["description"] = value

        if editing:
            state["step"] = "edit_menu"
            show_renewal_edit_menu(message.chat.id, user_id)
            return

        state["step"] = "panel"

        show_renewal_panel_selection(message.chat.id)

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
                reply_markup=renewal_back_keyboard(),
                parse_mode="HTML"
            )
            return

        if duration <= 0:
            bot.send_message(
                message.chat.id,
                "❌ مدت باید بیشتر از صفر باشد.",
                reply_markup=renewal_back_keyboard()
            )
            return

        state["data"]["duration"] = duration

        if editing:
            state["step"] = "edit_menu"
            show_renewal_edit_menu(message.chat.id, user_id)
            return

        state["step"] = "volume"

        bot.send_message(
            message.chat.id,
            "📦 مقدار حجمی که با این پلن اضافه می‌شود را به GB وارد کنید:\n\n"
            "(این عدد به حجم فعلی سرویس اضافه می‌شود، نه جایگزین آن)\n\n"
            "مثال: <code>50</code>",
            reply_markup=renewal_back_keyboard(),
            parse_mode="HTML"
        )

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
                "مثال: <code>50</code>",
                reply_markup=renewal_back_keyboard(),
                parse_mode="HTML"
            )
            return

        if volume <= 0:
            bot.send_message(
                message.chat.id,
                "❌ حجم باید بیشتر از صفر باشد.",
                reply_markup=renewal_back_keyboard()
            )
            return

        state["data"]["volume"] = volume

        if editing:
            state["step"] = "edit_menu"
            show_renewal_edit_menu(message.chat.id, user_id)
            return

        state["step"] = "price"

        bot.send_message(
            message.chat.id,
            "💰 قیمت این پلن افزایش حجم را به تومان وارد کنید:\n\n"
            "مثال: <code>180000</code>",
            reply_markup=renewal_back_keyboard(),
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
                "مثال: <code>180000</code>",
                reply_markup=renewal_back_keyboard(),
                parse_mode="HTML"
            )
            return

        if price <= 0:
            bot.send_message(
                message.chat.id,
                "❌ قیمت باید بیشتر از صفر باشد.",
                reply_markup=renewal_back_keyboard()
            )
            return

        state["data"]["price"] = price

        if editing:
            state["step"] = "edit_menu"
            show_renewal_edit_menu(message.chat.id, user_id)
            return

        state["step"] = "preview"

        send_renewal_preview(message.chat.id, user_id)


# ============================================================
# VOLUME-INCREASE — PANEL SELECTION
# ============================================================

def show_renewal_panel_selection(chat_id):

    panels = db_execute(
        "SELECT * FROM panels WHERE active=1 ORDER BY id ASC",
        fetchall=True
    )

    kb = types.InlineKeyboardMarkup()

    if not panels:
        kb.add(
            types.InlineKeyboardButton(
                "🔄 تلاش مجدد",
                callback_data="renewal_admin_panel_refresh"
            )
        )
        kb.add(
            types.InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="renewal_admin_back"
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
        kb.add(
            types.InlineKeyboardButton(
                f"🟢 {panel['name']}",
                callback_data=f"renewal_panel:{panel['id']}"
            )
        )

    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="renewal_admin_back"
        )
    )

    bot.send_message(
        chat_id,
        "🖥 <b>پنل مرتبط با این پلن افزایش حجم را انتخاب کنید:</b>\n\n"
        "فقط برای سرویس‌های همین پنل قابل استفاده خواهد بود.",
        reply_markup=kb,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data == "renewal_admin_panel_refresh")
def renewal_panel_refresh(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    show_renewal_panel_selection(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("renewal_panel:"))
def renewal_panel_selected(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = RENEWAL_CREATION.get(user_id)

    if not state:
        bot.answer_callback_query(
            call.id,
            "❌ فرآیند افزودن پلن افزایش حجم منقضی شده است."
        )
        return

    panel_id = int(call.data.split(":")[1])

    panel = db_execute(
        "SELECT * FROM panels WHERE id=? AND active=1",
        (panel_id,),
        fetchone=True
    )

    if not panel:
        bot.answer_callback_query(call.id, "❌ این پنل دیگر فعال نیست.")
        return

    state["data"]["panel_id"] = panel_id
    state["data"]["panel_name"] = panel["name"]

    bot.answer_callback_query(call.id)

    if is_editing_renewal(state):
        state["step"] = "edit_menu"
        show_renewal_edit_menu(call.message.chat.id, user_id)
        return

    state["step"] = "duration"

    bot.send_message(
        call.message.chat.id,
        f"🖥 پنل انتخاب شد: <b>{panel['name']}</b>\n\n"
        "⏳ مدت این پلن افزایش حجم را به روز وارد کنید:\n\n"
        "مثال: <code>15</code>",
        reply_markup=renewal_back_keyboard(),
        parse_mode="HTML"
    )


# ============================================================
# VOLUME-INCREASE — PREVIEW
# ============================================================

def send_renewal_preview(chat_id, user_id):

    state = RENEWAL_CREATION.get(user_id)

    if not state:
        return

    data = state["data"]
    description = data.get("description") or "ندارد"

    text = (
        "⚡️ <b>پیش‌نمایش پلن افزایش حجم</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🏷 نام: <b>{data.get('name')}</b>\n\n"
        f"📝 توضیحات:\n{description}\n\n"
        f"🖥 پنل: <b>{data.get('panel_name', '---')}</b>\n"
        f"⏳ مدت اضافه‌شونده: <b>{data.get('duration')} روز</b>\n"
        f"📦 حجم اضافه‌شونده: <b>{data.get('volume')} GB</b>\n"
        f"💰 قیمت: <b>{data.get('price'):,} تومان</b>\n\n"
        "━━━━━━━━━━━━━━\n"
        "آیا اطلاعات صحیح است؟"
    )

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "✅ ساخت پلن افزایش حجم",
            callback_data="renewal_create_confirm"
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "✏️ اصلاح",
            callback_data="renewal_edit_start"
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="renewal_admin_back"
        )
    )

    bot.send_message(
        chat_id,
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# VOLUME-INCREASE — CREATE
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "renewal_create_confirm")
def renewal_create_confirm(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = RENEWAL_CREATION.get(user_id)

    if not state:
        bot.answer_callback_query(call.id, "❌ اطلاعات ساخت پلن افزایش حجم پیدا نشد.")
        return

    data = state["data"]

    try:
        db_execute(
            """
            INSERT INTO renewal_plans
            (name, description, price, duration, volume, panel_id, active, sort_order, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?)
            """,
            (
                data["name"],
                data.get("description", ""),
                data["price"],
                data["duration"],
                data["volume"],
                data["panel_id"],
                now()
            )
        )
    except Exception as e:
        bot.answer_callback_query(call.id, "❌ خطا در ساخت پلن افزایش حجم")
        bot.send_message(
            call.message.chat.id,
            "❌ <b>ساخت پلن افزایش حجم انجام نشد.</b>\n\n"
            f"<code>{str(e)}</code>",
            parse_mode="HTML",
            reply_markup=renewal_back_keyboard()
        )
        return

    clear_renewal_state(user_id)

    bot.answer_callback_query(call.id, "✅ پلن افزایش حجم ساخته شد")

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("⚡️ مدیریت پلن‌های افزایش حجم", callback_data="renewal_admin_home")
    )
    kb.add(
        types.InlineKeyboardButton("🔙 بازگشت", callback_data="plan_admin_home")
    )

    bot.send_message(
        call.message.chat.id,
        "✅ <b>پلن افزایش حجم با موفقیت ساخته شد.</b>\n\n"
        f"⚡️ {data['name']}",
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# VOLUME-INCREASE — EDIT START / MENU
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "renewal_edit_start")
def renewal_edit_start(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = RENEWAL_CREATION.get(user_id)

    if not state:
        bot.answer_callback_query(call.id, "❌ اطلاعات پلن افزایش حجم پیدا نشد.")
        return

    state["step"] = "edit_menu"

    bot.answer_callback_query(call.id)

    show_renewal_edit_menu(call.message.chat.id, user_id)


def show_renewal_edit_menu(chat_id, user_id):

    kb = types.InlineKeyboardMarkup()

    fields = [
        ("🏷 نام", "name"),
        ("📝 توضیحات", "description"),
        ("🖥 پنل", "panel"),
        ("⏳ مدت", "duration"),
        ("📦 حجم", "volume"),
        ("💰 قیمت", "price"),
    ]

    for title, field in fields:
        kb.add(
            types.InlineKeyboardButton(title, callback_data=f"renewal_edit_field:{field}")
        )

    kb.add(
        types.InlineKeyboardButton("👀 پیش‌نمایش", callback_data="renewal_edit_preview")
    )

    state = RENEWAL_CREATION.get(user_id, {})
    if is_editing_renewal(state):
        kb.add(
            types.InlineKeyboardButton("💾 ذخیره تغییرات", callback_data="renewal_save_edit")
        )

    kb.add(
        types.InlineKeyboardButton("🔙 بازگشت", callback_data="renewal_admin_back")
    )

    bot.send_message(
        chat_id,
        "✏️ <b>کدام قسمت پلن افزایش حجم را می‌خواهید اصلاح کنید؟</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("renewal_edit_field:"))
def renewal_edit_field(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = RENEWAL_CREATION.get(user_id)

    if not state:
        return

    field = call.data.split(":")[1]

    if field == "panel":
        state["step"] = "panel"
        bot.answer_callback_query(call.id)
        show_renewal_panel_selection(call.message.chat.id)
        return

    state["step"] = field

    prompts = {
        "name": "🏷 نام جدید پلن افزایش حجم را وارد کنید:",
        "description": "📝 توضیحات جدید را وارد کنید:",
        "duration": "⏳ مدت جدید را به روز وارد کنید:",
        "volume": "📦 حجم اضافه‌شونده جدید را به GB وارد کنید:",
        "price": "💰 قیمت جدید را به تومان وارد کنید:",
    }

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        prompts.get(field, "مقدار جدید را وارد کنید:"),
        reply_markup=renewal_back_keyboard("renewal_edit_back"),
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data == "renewal_edit_preview")
def renewal_edit_preview(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    send_renewal_preview(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda call: call.data == "renewal_edit_back")
def renewal_edit_back(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = RENEWAL_CREATION.get(user_id)

    if not state:
        bot.answer_callback_query(call.id)
        return

    state["step"] = "edit_menu"

    bot.answer_callback_query(call.id)

    show_renewal_edit_menu(call.message.chat.id, user_id)


# ============================================================
# VOLUME-INCREASE — LIST
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "renewal_admin_list")
def renewal_admin_list(call):

    if not is_admin(call.from_user.id):
        return

    plans = db_execute(
        "SELECT * FROM renewal_plans ORDER BY sort_order ASC, id ASC",
        fetchall=True
    )

    kb = types.InlineKeyboardMarkup()

    if not plans:
        kb.add(
            types.InlineKeyboardButton("➕ افزودن پلن افزایش حجم", callback_data="renewal_admin_add")
        )
    else:
        for plan in plans:
            status = "🟢" if plan["active"] else "🔴"
            kb.add(
                types.InlineKeyboardButton(
                    f"{status} ⚡️ {plan['name']}",
                    callback_data=f"renewaladmin:{plan['id']}"
                )
            )

    kb.add(
        types.InlineKeyboardButton("🔙 بازگشت", callback_data="renewal_admin_home")
    )

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        "📋 <b>لیست پلن‌های افزایش حجم</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# VOLUME-INCREASE — DETAILS
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("renewaladmin:"))
def renewal_admin_details(call):

    if not is_admin(call.from_user.id):
        return

    renewal_id = int(call.data.split(":")[1])

    plan = db_execute(
        """
        SELECT renewal_plans.*, panels.name AS panel_name
        FROM renewal_plans
        LEFT JOIN panels ON panels.id = renewal_plans.panel_id
        WHERE renewal_plans.id=?
        """,
        (renewal_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(call.id, "❌ پلن افزایش حجم پیدا نشد.")
        return

    description = plan["description"] or "ندارد"
    panel_name = plan["panel_name"] or "بدون پنل"
    status = "🟢 فعال" if plan["active"] else "🔴 غیرفعال"

    text = (
        f"⚡️ <b>{plan['name']}</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📝 توضیحات:\n{description}\n\n"
        f"💰 قیمت: <b>{plan['price']:,} تومان</b>\n"
        f"⏳ مدت اضافه‌شونده: <b>{plan['duration']} روز</b>\n"
        f"📦 حجم اضافه‌شونده: <b>{plan['volume']} GB</b>\n"
        f"🖥 پنل: <b>{panel_name}</b>\n"
        f"📌 وضعیت: <b>{status}</b>\n\n"
        "━━━━━━━━━━━━━━"
    )

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton("✏️ ویرایش", callback_data=f"renewal_edit:{renewal_id}")
    )

    if plan["active"]:
        kb.add(
            types.InlineKeyboardButton("🔴 غیرفعال کردن", callback_data=f"renewal_toggle:{renewal_id}")
        )
    else:
        kb.add(
            types.InlineKeyboardButton("🟢 فعال کردن", callback_data=f"renewal_toggle:{renewal_id}")
        )

    kb.add(
        types.InlineKeyboardButton("🗑 حذف", callback_data=f"renewal_delete:{renewal_id}")
    )

    kb.add(
        types.InlineKeyboardButton("🔙 بازگشت", callback_data="renewal_admin_list")
    )

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ============================================================
# VOLUME-INCREASE — TOGGLE
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("renewal_toggle:"))
def renewal_toggle(call):

    if not is_admin(call.from_user.id):
        return

    renewal_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT active FROM renewal_plans WHERE id=?",
        (renewal_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(call.id, "❌ پلن افزایش حجم پیدا نشد.")
        return

    new_status = 0 if plan["active"] else 1

    db_execute(
        "UPDATE renewal_plans SET active=? WHERE id=?",
        (new_status, renewal_id)
    )

    bot.answer_callback_query(call.id, "✅ وضعیت تغییر کرد.")

    fake_call = call
    fake_call.data = f"renewaladmin:{renewal_id}"
    renewal_admin_details(fake_call)


# ============================================================
# VOLUME-INCREASE — DELETE
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("renewal_delete:"))
def renewal_delete(call):

    if not is_admin(call.from_user.id):
        return

    renewal_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT name FROM renewal_plans WHERE id=?",
        (renewal_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(call.id, "❌ پلن افزایش حجم پیدا نشد.")
        return

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton("⚠️ بله، حذف شود", callback_data=f"renewal_delete_confirm:{renewal_id}")
    )
    kb.add(
        types.InlineKeyboardButton("🔙 انصراف", callback_data=f"renewaladmin:{renewal_id}")
    )

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        f"⚠️ <b>حذف پلن افزایش حجم</b>\n\n"
        f"⚡️ {plan['name']}\n\n"
        "آیا مطمئن هستید؟",
        reply_markup=kb,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("renewal_delete_confirm:"))
def renewal_delete_confirm(call):

    if not is_admin(call.from_user.id):
        return

    renewal_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT name FROM renewal_plans WHERE id=?",
        (renewal_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(call.id, "❌ پلن افزایش حجم پیدا نشد.")
        return

    db_execute("DELETE FROM renewal_plans WHERE id=?", (renewal_id,))

    bot.answer_callback_query(call.id, "✅ پلن افزایش حجم حذف شد.")

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("📋 لیست پلن‌های افزایش حجم", callback_data="renewal_admin_list")
    )
    kb.add(
        types.InlineKeyboardButton("🔙 بازگشت", callback_data="renewal_admin_home")
    )

    bot.send_message(
        call.message.chat.id,
        "✅ پلن افزایش حجم با موفقیت حذف شد.",
        reply_markup=kb
    )


# ============================================================
# VOLUME-INCREASE — EDIT EXISTING
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("renewal_edit:"))
def renewal_edit_existing(call):

    if not is_admin(call.from_user.id):
        return

    renewal_id = int(call.data.split(":")[1])

    plan = db_execute(
        "SELECT * FROM renewal_plans WHERE id=?",
        (renewal_id,),
        fetchone=True
    )

    if not plan:
        bot.answer_callback_query(call.id, "❌ پلن افزایش حجم پیدا نشد.")
        return

    user_id = call.from_user.id

    RENEWAL_CREATION[user_id] = {
        "step": "edit_menu",
        "data": {
            "editing_renewal_id": renewal_id,
            "name": plan["name"],
            "description": plan["description"] or "",
            "price": plan["price"],
            "duration": plan["duration"],
            "volume": plan["volume"],
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
            RENEWAL_CREATION[user_id]["data"]["panel_name"] = panel["name"]

    bot.answer_callback_query(call.id)

    show_renewal_edit_menu(call.message.chat.id, user_id)


# ============================================================
# VOLUME-INCREASE — SAVE EDIT
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "renewal_save_edit")
def renewal_save_edit(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = RENEWAL_CREATION.get(user_id)

    if not state:
        return

    data = state["data"]
    renewal_id = data.get("editing_renewal_id")

    if not renewal_id:
        return

    db_execute(
        """
        UPDATE renewal_plans
        SET name=?, description=?, price=?, duration=?, volume=?, panel_id=?
        WHERE id=?
        """,
        (
            data["name"],
            data.get("description", ""),
            data["price"],
            data["duration"],
            data["volume"],
            data.get("panel_id"),
            renewal_id
        )
    )

    clear_renewal_state(user_id)

    bot.answer_callback_query(call.id, "✅ پلن افزایش حجم ویرایش شد.")

    fake_call = call
    fake_call.data = f"renewaladmin:{renewal_id}"
    renewal_admin_details(fake_call)


# ============================================================
# VOLUME-INCREASE — GENERAL BACK (با پشتیبانی از بازگشت مرحله‌به‌مرحله)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "renewal_admin_back")
def renewal_admin_back(call):

    if not is_admin(call.from_user.id):
        return

    user_id = call.from_user.id
    state = RENEWAL_CREATION.get(user_id)

    if state and state.get("step"):

        step = state["step"]

        previous_steps = {
            "description": "name",
            "panel": "description",
            "duration": "panel",
            "volume": "duration",
            "price": "volume",
            "preview": "price",
        }

        previous = previous_steps.get(step)

        if previous:
            state["step"] = previous

            bot.answer_callback_query(call.id)

            if previous == "name":
                bot.send_message(
                    call.message.chat.id,
                    "🏷 نام پلن افزایش حجم را وارد کنید:",
                    reply_markup=renewal_back_keyboard()
                )

            elif previous == "description":
                bot.send_message(
                    call.message.chat.id,
                    "📝 توضیحات پلن افزایش حجم را وارد کنید:",
                    reply_markup=renewal_back_keyboard()
                )

            elif previous == "panel":
                show_renewal_panel_selection(call.message.chat.id)

            elif previous == "duration":
                bot.send_message(
                    call.message.chat.id,
                    "⏳ مدت این پلن افزایش حجم را به روز وارد کنید:",
                    reply_markup=renewal_back_keyboard()
                )

            elif previous == "volume":
                bot.send_message(
                    call.message.chat.id,
                    "📦 حجم اضافه‌شونده را به GB وارد کنید:",
                    reply_markup=renewal_back_keyboard()
                )

            elif previous == "price":
                bot.send_message(
                    call.message.chat.id,
                    "💰 قیمت این پلن افزایش حجم را به تومان وارد کنید:",
                    reply_markup=renewal_back_keyboard()
                )

            return

    clear_renewal_state(user_id)

    bot.answer_callback_query(call.id)

    plans = db_execute(
        "SELECT * FROM renewal_plans ORDER BY sort_order ASC, id ASC",
        fetchall=True
    )

    text = "⚡️ <b>مدیریت پلن‌های افزایش حجم</b>\n\n"

    if not plans:
        text += "❌ هنوز هیچ پلن افزایش حجمی ساخته نشده است."
    else:
        text += f"📦 تعداد پلن‌های افزایش حجم: <b>{len(plans)}</b>"

    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=renewal_main_keyboard(),
        parse_mode="HTML"
    )


# ============================================================
# ADMIN MAIN — بازگشت به کیبورد اصلی پنل مدیریت
# پیام قبلی (که ممکن است اطلاعات حساس تنظیمات را داشته باشد)
# کاملاً حذف می‌شود، نه فقط دکمه‌هایش. اگر حذف پیام به هر دلیلی
# (مثلاً پیام قدیمی‌تر از ۴۸ ساعت) ممکن نبود، حداقل متن آن هم
# پاک/خنثی می‌شود تا اطلاعاتی روی صفحه باقی نماند.
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "admin_main")
def admin_main_callback(call):

    if not is_admin(call.from_user.id):
        return

    clear_state(call.from_user.id)

    bot.answer_callback_query(call.id)

    deleted = False
    try:
        bot.delete_message(
            call.message.chat.id,
            call.message.message_id
        )
        deleted = True
    except Exception:
        deleted = False

    if not deleted:
        try:
            bot.edit_message_text(
                "👑 پنل مدیریت",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass

    from keyboards import admin_keyboard

    bot.send_message(
        call.message.chat.id,
        "👑 <b>پنل مدیریت VirangarVPN</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )
