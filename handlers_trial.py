# ============================================================
# handlers_trial.py
# تست رایگان برای کاربران عادی + پنل مدیریت کامل برای ادمین
# نسخه‌ی مقاوم: هر هندلر با try/except محافظت شده تا کرش نکنه
# ============================================================

import re
import logging
from datetime import date

from telebot import types

from config import bot
from database import db_execute, get_setting, set_setting
from models import get_user, is_admin
from pasarguard_api import pasarguard_create_service
from services import create_local_service


logger = logging.getLogger(__name__)

USERNAME_PREFIX = "virangarvpn"          # نمایش به کاربر: virangarvpn.ali
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{2,20}$")

GENERIC_ERROR_MESSAGE = "❌ خطایی رخ داد، لطفاً دوباره تلاش کن."


# ============================================================
# HELPERS
# ============================================================

def count_user_trials(user_id):
    try:
        row = db_execute("""
        SELECT COUNT(*) c FROM services
        WHERE user_id=? AND plan_id IS NULL
        """, (user_id,), fetchone=True)

        return row["c"] if row else 0
    except Exception:
        logger.exception("count_user_trials failed")
        return 0


def username_taken(final_username):
    """
    final_username همان چیزی است که واقعاً روی پنل/دیتابیس ذخیره
    می‌شود (پس از تبدیل نقطه به آندرلاین توسط pasarguard_api).
    """
    try:
        row = db_execute("""
        SELECT id FROM services
        WHERE username=?
        LIMIT 1
        """, (final_username,), fetchone=True)

        return bool(row)
    except Exception:
        logger.exception("username_taken failed")
        # برای احتیاط، در صورت خطا فرض می‌کنیم نام گرفته شده تا دوباره تلاش کند
        return True


def get_trial_panel():
    """
    اگر ادمین یک پنل مشخص برای تست رایگان انتخاب کرده باشد همان
    برگردانده می‌شود، وگرنه مثل قبل پنلی با کمترین assigned_sales
    به‌صورت خودکار انتخاب می‌شود.
    """
    try:
        panel_id = get_setting("trial_panel_id", "")

        if panel_id:
            panel = db_execute("""
            SELECT * FROM panels
            WHERE id=? AND active=1
            """, (panel_id,), fetchone=True)

            if panel:
                return panel

        return db_execute("""
        SELECT * FROM panels
        WHERE active=1
        ORDER BY assigned_sales ASC, id ASC
        LIMIT 1
        """, fetchone=True)
    except Exception:
        logger.exception("get_trial_panel failed")
        return None


def get_today_trial_count():
    """
    تعداد تست‌های صادر شده در «امروز» را برمی‌گرداند.
    اگر تاریخ ذخیره‌شده با امروز فرق داشته باشد، یعنی روز عوض شده
    و شمارنده باید صفر در نظر گرفته شود (ریست خودکار روزانه).
    """
    try:
        saved_date = get_setting("trial_daily_date", "")
        today = str(date.today())

        if saved_date != today:
            return 0

        return int(get_setting("trial_daily_count", "0"))
    except Exception:
        logger.exception("get_today_trial_count failed")
        return 0


def increment_today_trial_count():
    """
    یکی به شمارنده‌ی تست‌های امروز اضافه می‌کند.
    اگر روز عوض شده باشد، شمارنده از نو از ۱ شروع می‌شود.
    """
    try:
        today = str(date.today())
        current = get_today_trial_count()

        set_setting("trial_daily_date", today)
        set_setting("trial_daily_count", str(current + 1))
    except Exception:
        logger.exception("increment_today_trial_count failed")


def daily_limit_reached():
    """
    بررسی می‌کند سقف روزانه (کل ربات) پر شده یا نه.
    مقدار ۰ برای trial_daily_limit یعنی «بدون محدودیت روزانه».
    """
    try:
        daily_limit = int(get_setting("trial_daily_limit", "0"))

        if daily_limit <= 0:
            return False

        return get_today_trial_count() >= daily_limit
    except Exception:
        logger.exception("daily_limit_reached failed")
        return False


DAILY_LIMIT_MESSAGE = (
    "🎁 امروز اینقدر استقبال از تست رایگان خوب بود که سهمیه‌ی امروز تکمیل شد!\n\n"
    "✨ فردا با سهمیه‌ی جدید در خدمتتون هستیم.\n"
    "اگه عجله دارید، می‌تونید یکی از پلن‌های اشتراکی رو تهیه کنید."
)


def safe_answer_callback(call, text=None, show_alert=False):
    """جواب‌دادن امن به callback؛ اگر callback منقضی/تکراری باشد کرش نمی‌کند."""
    try:
        if text:
            bot.answer_callback_query(call.id, text, show_alert=show_alert)
        else:
            bot.answer_callback_query(call.id)
    except Exception:
        logger.exception("safe_answer_callback failed")


def safe_edit_message(text, chat_id, message_id, reply_markup=None):
    """ویرایش امن پیام؛ اگر پیام حذف شده یا تغییری نکرده باشد، پیام جدید می‌فرستد."""
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup)
        return True
    except Exception:
        try:
            bot.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception:
            logger.exception("safe_edit_message fallback send failed")
        return False


# ============================================================
# USER FLOW — STEP 1: START
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🎁 تست رایگان")
def free_trial(message):
    try:
        user = get_user(message.from_user.id)

        if get_setting("trial_enabled", "1") != "1":
            bot.send_message(message.chat.id, "❌ تست رایگان غیرفعال است.")
            return

        if daily_limit_reached():
            bot.send_message(message.chat.id, DAILY_LIMIT_MESSAGE)
            return

        limit = int(get_setting("trial_limit", "1"))
        used = count_user_trials(user["id"])

        if used >= limit:
            bot.send_message(message.chat.id, "❌ شما قبلاً از تست رایگان استفاده کرده‌اید.")
            return

        msg = bot.send_message(
            message.chat.id,
            "🎁 <b>تست رایگان</b>\n\n"
            "برای فعال‌سازی، اول یک نام دلخواه انتخاب کن (فقط حروف/عدد انگلیسی، بدون فاصله):\n\n"
            "مثال: <code>ali</code>"
        )
        bot.register_next_step_handler(msg, trial_get_name)

    except Exception:
        logger.exception("free_trial handler crashed")
        try:
            bot.send_message(message.chat.id, GENERIC_ERROR_MESSAGE)
        except Exception:
            pass


# ============================================================
# USER FLOW — STEP 2: GET NAME
# ============================================================

def trial_get_name(message):
    try:
        raw = (message.text or "").strip()

        if not NAME_PATTERN.match(raw):
            msg = bot.send_message(
                message.chat.id,
                "❌ نام نامعتبر است.\n\n"
                "فقط حروف انگلیسی، عدد و آندرلاین مجاز است (بین ۲ تا ۲۰ کاراکتر).\n"
                "دوباره یک نام ارسال کن:"
            )
            bot.register_next_step_handler(msg, trial_get_name)
            return

        name = raw.lower()
        display_username = f"{USERNAME_PREFIX}.{name}"     # چیزی که به کاربر نشون می‌دیم
        final_username = f"{USERNAME_PREFIX}_{name}"        # چیزی که واقعاً روی پنل ساخته می‌شود

        if username_taken(final_username):
            msg = bot.send_message(
                message.chat.id,
                f"❌ نام <code>{name}</code> قبلاً استفاده شده.\n\n"
                "یک نام دیگر ارسال کن:"
            )
            bot.register_next_step_handler(msg, trial_get_name)
            return

        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ تایید و ساخت", callback_data=f"trialgo:{name}"),
            types.InlineKeyboardButton("❌ انصراف", callback_data="trialcancel"),
        )

        bot.send_message(
            message.chat.id,
            "🔎 مشخصات سرویس تست:\n\n"
            f"👤 نام کاربری: <code>{display_username}</code>\n\n"
            "تایید می‌کنی؟",
            reply_markup=kb
        )

    except Exception:
        logger.exception("trial_get_name handler crashed")
        try:
            bot.send_message(message.chat.id, GENERIC_ERROR_MESSAGE)
        except Exception:
            pass


# ============================================================
# USER FLOW — STEP 3: CONFIRM & CREATE
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "trialcancel")
def trial_cancel(call):
    try:
        safe_answer_callback(call)
        safe_edit_message("❌ لغو شد.", call.message.chat.id, call.message.message_id)
    except Exception:
        logger.exception("trial_cancel handler crashed")


@bot.callback_query_handler(func=lambda call: call.data.startswith("trialgo:"))
def trial_confirm(call):
    try:
        name = call.data.split(":", 1)[1]
        display_username = f"{USERNAME_PREFIX}.{name}"
        final_username = f"{USERNAME_PREFIX}_{name}"

        user = get_user(call.from_user.id)

        if get_setting("trial_enabled", "1") != "1":
            safe_answer_callback(call, "❌ تست رایگان غیرفعال است.", show_alert=True)
            return

        if daily_limit_reached():
            safe_answer_callback(call, "❌ سهمیه‌ی امروز تکمیل شده.", show_alert=True)
            safe_edit_message(DAILY_LIMIT_MESSAGE, call.message.chat.id, call.message.message_id)
            return

        limit = int(get_setting("trial_limit", "1"))
        used = count_user_trials(user["id"])

        if used >= limit:
            safe_answer_callback(call, "❌ شما قبلاً از تست رایگان استفاده کرده‌اید.", show_alert=True)
            return

        if username_taken(final_username):
            safe_answer_callback(call, "❌ این نام همین الان توسط شخص دیگری گرفته شد.", show_alert=True)
            try:
                msg = bot.send_message(call.message.chat.id, "یک نام دیگر ارسال کن:")
                bot.register_next_step_handler(msg, trial_get_name)
            except Exception:
                logger.exception("re-prompt after username_taken failed")
            return

        try:
            volume = float(get_setting("trial_volume", "5"))
            duration = int(get_setting("trial_duration", "1"))
            devices = int(get_setting("trial_devices", "1"))
        except Exception:
            logger.exception("reading trial settings failed")
            safe_answer_callback(call, GENERIC_ERROR_MESSAGE, show_alert=True)
            return

        panel = get_trial_panel()

        if not panel:
            safe_answer_callback(call, "❌ در حال حاضر پنل فعالی برای تست وجود ندارد.", show_alert=True)
            return

        safe_answer_callback(call, "⏳ در حال ساخت سرویس...")
        safe_edit_message("⏳ در حال ساخت سرویس تست...", call.message.chat.id, call.message.message_id)

        fake_plan = {
            "id": None,
            "name": "Free Trial",
            "price": 0,
            "volume": volume,
            "duration": duration,
            "devices": devices
        }

        try:
            result = pasarguard_create_service(
                panel=panel,
                telegram_user=user,
                plan=fake_plan,
                desired_username=display_username     # pasarguard_api خودش نقطه رو به _ تبدیل می‌کند
            )
        except Exception:
            logger.exception("pasarguard_create_service crashed")
            try:
                bot.send_message(call.message.chat.id, "❌ ساخت تست رایگان انجام نشد (خطای ارتباط با پنل).")
            except Exception:
                pass
            return

        if not result.get("success"):
            try:
                bot.send_message(
                    call.message.chat.id,
                    f"❌ ساخت تست رایگان انجام نشد.\n\n<code>{result.get('error', 'نامشخص')}</code>"
                )
            except Exception:
                logger.exception("sending failure message crashed")
            return

        try:
            service = create_local_service(user=user, plan=fake_plan, panel=panel, result=result)
        except Exception:
            logger.exception("create_local_service crashed")
            try:
                bot.send_message(
                    call.message.chat.id,
                    "⚠️ سرویس روی پنل ساخته شد ولی ثبت داخلی آن با خطا مواجه شد. لطفاً به ادمین اطلاع بده."
                )
            except Exception:
                pass
            return

        # فقط بعد از موفقیت‌آمیز بودن ساخت سرویس، شمارنده‌ی روزانه افزایش پیدا می‌کند
        increment_today_trial_count()

        volume_display = int(volume) if volume == int(volume) else volume

        try:
            bot.send_message(
                call.message.chat.id,
                "🎁 <b>تست رایگان فعال شد!</b>\n\n"
                f"👤 نام کاربری: <code>{result.get('username', final_username)}</code>\n"
                f"📊 حجم: {volume_display} GB\n"
                f"⏳ مدت: {duration} روز\n"
                f"📱 دستگاه: {devices}\n\n"
                f"🔗 لینک اشتراک:\n"
                f"<code>{service['config']}</code>"
            )
        except Exception:
            logger.exception("sending success message crashed")

    except Exception:
        logger.exception("trial_confirm handler crashed")
        try:
            safe_answer_callback(call, GENERIC_ERROR_MESSAGE, show_alert=True)
        except Exception:
            pass


# ============================================================
# ADMIN — TRIAL SETTINGS PANEL
# ============================================================

def render_trial_settings(chat_id, message_id=None):
    try:
        enabled = get_setting("trial_enabled", "1") == "1"
        volume = get_setting("trial_volume", "5")
        duration = get_setting("trial_duration", "1")
        devices = get_setting("trial_devices", "1")
        limit = get_setting("trial_limit", "1")
        daily_limit = int(get_setting("trial_daily_limit", "0"))
        daily_used = get_today_trial_count()

        panel_id = get_setting("trial_panel_id", "")
        panel_name = "🔀 خودکار (کمترین فروش)"

        if panel_id:
            try:
                panel = db_execute("SELECT name FROM panels WHERE id=?", (panel_id,), fetchone=True)
                if panel:
                    panel_name = panel["name"]
            except Exception:
                logger.exception("reading panel name failed")

        daily_limit_display = "بدون محدودیت" if daily_limit <= 0 else f"{daily_used} / {daily_limit}"

        text = (
            "🎁 <b>تنظیمات تست رایگان</b>\n\n"
            f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}\n"
            f"📊 حجم: {volume} GB\n"
            f"⏳ مدت: {duration} روز\n"
            f"📱 دستگاه: {devices}\n"
            f"🔁 سقف استفاده هر کاربر: {limit} بار\n"
            f"📅 سقف روزانه کل ربات: {daily_limit_display}\n"
            f"🖥 پنل تست: {panel_name}\n\n"
            "برای تغییر هرکدام روی دکمه مربوطه بزن:"
        )

        kb = types.InlineKeyboardMarkup()

        kb.add(types.InlineKeyboardButton(
            "🔴 غیرفعال کردن" if enabled else "🟢 فعال کردن",
            callback_data="trialset:toggle"
        ))

        kb.row(
            types.InlineKeyboardButton(f"📊 حجم: {volume}GB", callback_data="trialset:volume"),
            types.InlineKeyboardButton(f"⏳ مدت: {duration}روز", callback_data="trialset:duration"),
        )

        kb.row(
            types.InlineKeyboardButton(f"📱 دستگاه: {devices}", callback_data="trialset:devices"),
            types.InlineKeyboardButton(f"🔁 سقف هرکاربر: {limit}", callback_data="trialset:limit"),
        )

        kb.row(
            types.InlineKeyboardButton(f"📅 سقف روزانه: {daily_limit_display}", callback_data="trialset:daily_limit"),
        )

        kb.add(types.InlineKeyboardButton(f"🖥 پنل تست: {panel_name}", callback_data="trialset:panel"))

        if message_id:
            if safe_edit_message(text, chat_id, message_id, reply_markup=kb):
                return
            return

        bot.send_message(chat_id, text, reply_markup=kb)

    except Exception:
        logger.exception("render_trial_settings crashed")
        try:
            bot.send_message(chat_id, GENERIC_ERROR_MESSAGE)
        except Exception:
            pass


@bot.message_handler(func=lambda m: m.text == "🎁 مدیریت تست رایگان" and is_admin(m.from_user.id))
def admin_trial_settings(message):
    try:
        render_trial_settings(message.chat.id)
    except Exception:
        logger.exception("admin_trial_settings handler crashed")
        try:
            bot.send_message(message.chat.id, GENERIC_ERROR_MESSAGE)
        except Exception:
            pass


# ---------------- TOGGLE ENABLED ----------------

@bot.callback_query_handler(func=lambda call: call.data == "trialset:toggle")
def trial_setting_toggle(call):
    try:
        if not is_admin(call.from_user.id):
            safe_answer_callback(call)
            return

        current = get_setting("trial_enabled", "1")
        set_setting("trial_enabled", "0" if current == "1" else "1")

        safe_answer_callback(call, "✅ تغییر کرد.")
        render_trial_settings(call.message.chat.id, call.message.message_id)

    except Exception:
        logger.exception("trial_setting_toggle handler crashed")
        try:
            safe_answer_callback(call, GENERIC_ERROR_MESSAGE, show_alert=True)
        except Exception:
            pass


# ---------------- NUMBER SETTINGS (volume / duration / devices / limit / daily_limit) ----------------

NUMBER_SETTINGS = {
    "volume": ("trial_volume", "📊 حجم جدید را به GB ارسال کن (اعشار هم مجاز است، مثال: 0.5):"),
    "duration": ("trial_duration", "⏳ مدت جدید را به روز ارسال کن (فقط عدد):"),
    "devices": ("trial_devices", "📱 تعداد دستگاه جدید را ارسال کن (فقط عدد):"),
    "limit": ("trial_limit", "🔁 سقف استفاده هر کاربر را ارسال کن (فقط عدد):"),
    "daily_limit": (
        "trial_daily_limit",
        "📅 سقف روزانه کل ربات را ارسال کن (فقط عدد).\n"
        "برای غیرفعال کردن محدودیت روزانه، عدد ۰ را ارسال کن:"
    ),
}


@bot.callback_query_handler(func=lambda call: call.data.startswith("trialset:")
                             and call.data.split(":")[1] in NUMBER_SETTINGS)
def trial_setting_number_start(call):
    try:
        if not is_admin(call.from_user.id):
            safe_answer_callback(call)
            return

        key = call.data.split(":")[1]
        _, prompt = NUMBER_SETTINGS[key]

        safe_answer_callback(call)
        msg = bot.send_message(call.message.chat.id, prompt)
        bot.register_next_step_handler(msg, trial_setting_number_save, key)

    except Exception:
        logger.exception("trial_setting_number_start handler crashed")
        try:
            safe_answer_callback(call, GENERIC_ERROR_MESSAGE, show_alert=True)
        except Exception:
            pass


def trial_setting_number_save(message, key):
    try:
        text = (message.text or "").strip().replace(",", ".")

        if key == "volume":
            # حجم می‌تواند اعشاری هم باشد (مثلاً 0.5 گیگ)
            try:
                value = float(text)
            except ValueError:
                value = -1

            if value <= 0:
                msg = bot.send_message(
                    message.chat.id,
                    "❌ لطفاً یک عدد بزرگ‌تر از صفر ارسال کن (اعشار هم مجاز است، مثال: 0.5):"
                )
                bot.register_next_step_handler(msg, trial_setting_number_save, key)
                return

            # اگر عدد صحیح بود بدون اعشار ذخیره شود (5 نه 5.0)
            text = str(int(value)) if value == int(value) else str(value)

        elif key == "daily_limit":
            # سقف روزانه: عدد ۰ یعنی «بدون محدودیت» و مجاز است
            if not text.isdigit():
                msg = bot.send_message(message.chat.id, "❌ لطفاً فقط یک عدد صحیح (۰ یا بیشتر) ارسال کن:")
                bot.register_next_step_handler(msg, trial_setting_number_save, key)
                return

        else:
            if not text.isdigit() or int(text) <= 0:
                msg = bot.send_message(message.chat.id, "❌ لطفاً فقط یک عدد بزرگ‌تر از صفر ارسال کن:")
                bot.register_next_step_handler(msg, trial_setting_number_save, key)
                return

        setting_key, _ = NUMBER_SETTINGS[key]
        set_setting(setting_key, text)

        bot.send_message(message.chat.id, "✅ ذخیره شد.")
        render_trial_settings(message.chat.id)

    except Exception:
        logger.exception("trial_setting_number_save handler crashed")
        try:
            bot.send_message(message.chat.id, GENERIC_ERROR_MESSAGE)
        except Exception:
            pass


# ---------------- PANEL SELECTION ----------------

@bot.callback_query_handler(func=lambda call: call.data == "trialset:panel")
def trial_setting_panel_list(call):
    try:
        if not is_admin(call.from_user.id):
            safe_answer_callback(call)
            return

        panels = db_execute("""
        SELECT * FROM panels
        WHERE active=1
        ORDER BY name
        """, fetchall=True)

        kb = types.InlineKeyboardMarkup()

        kb.add(types.InlineKeyboardButton(
            "🔀 خودکار (کمترین فروش)",
            callback_data="trialpanelset:auto"
        ))

        for panel in panels or []:
            kb.add(types.InlineKeyboardButton(
                panel["name"],
                callback_data=f"trialpanelset:{panel['id']}"
            ))

        kb.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data="trialset:back"))

        safe_answer_callback(call)
        safe_edit_message(
            "🖥 کدام پنل برای صدور تست رایگان استفاده شود؟",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb
        )

    except Exception:
        logger.exception("trial_setting_panel_list handler crashed")
        try:
            safe_answer_callback(call, GENERIC_ERROR_MESSAGE, show_alert=True)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("trialpanelset:"))
def trial_setting_panel_save(call):
    try:
        if not is_admin(call.from_user.id):
            safe_answer_callback(call)
            return

        value = call.data.split(":", 1)[1]
        set_setting("trial_panel_id", "" if value == "auto" else value)

        safe_answer_callback(call, "✅ ذخیره شد.")
        render_trial_settings(call.message.chat.id, call.message.message_id)

    except Exception:
        logger.exception("trial_setting_panel_save handler crashed")
        try:
            safe_answer_callback(call, GENERIC_ERROR_MESSAGE, show_alert=True)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "trialset:back")
def trial_setting_back(call):
    try:
        if not is_admin(call.from_user.id):
            safe_answer_callback(call)
            return

        safe_answer_callback(call)
        render_trial_settings(call.message.chat.id, call.message.message_id)

    except Exception:
        logger.exception("trial_setting_back handler crashed")
        try:
            safe_answer_callback(call, GENERIC_ERROR_MESSAGE, show_alert=True)
        except Exception:
            pass
