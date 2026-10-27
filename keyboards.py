# ============================================================
# keyboards.py  [نسخه‌ی اصلاح‌شده]
# کیبوردهای Reply و Inline مشترک
#
# تغییرات:
#   - کیبورد ثابت (is_persistent): وقتی کیبورد گوشی بسته میشه، منوی
#     ربات همیشه پایین می‌مونه و جمع نمیشه
#   - دکمه‌های رنگی (Bot API 9.4): سبز / آبی / قرمز
#   - متن دکمه‌ها دقیقاً مثل قبله، پس هندلرها (m.text == "...") سالم می‌مونن
#   - اگه نسخه‌ی کتابخونه یا تلگرام کاربر از رنگ/ثابت‌بودن پشتیبانی
#     نکنه، بدون خطا همون کیبورد ساده نشون داده میشه
# ============================================================

from telebot import types

from database import get_setting


# رنگ دکمه‌ها
GREEN = "success"
BLUE = "primary"
RED = "danger"

PLACEHOLDER = "یکی از گزینه‌ها رو انتخاب کن 👇"


# ============================================================
# HELPERS (با fallback امن برای نسخه‌های قدیمی‌تر کتابخونه)
# ============================================================

def _btn(text, style=None):
    """دکمه‌ی کیبورد پایین؛ اگه کتابخونه style رو نشناخت، دکمه‌ی ساده."""
    if style:
        try:
            return types.KeyboardButton(text, style=style)
        except TypeError:
            pass
    return types.KeyboardButton(text)


def _ibtn(text, style=None, **kwargs):
    """دکمه‌ی شیشه‌ای؛ اگه کتابخونه style رو نشناخت، دکمه‌ی ساده."""
    if style:
        try:
            return types.InlineKeyboardButton(text, style=style, **kwargs)
        except TypeError:
            pass
    return types.InlineKeyboardButton(text, **kwargs)


def _reply_markup():
    """کیبورد ثابت و جمع‌نشدنی؛ با fallback اگه پارامترها پشتیبانی نشن."""
    attempts = (
        dict(resize_keyboard=True, one_time_keyboard=False,
             is_persistent=True, input_field_placeholder=PLACEHOLDER),
        dict(resize_keyboard=True, one_time_keyboard=False,
             input_field_placeholder=PLACEHOLDER),
        dict(resize_keyboard=True),
    )
    for kwargs in attempts:
        try:
            return types.ReplyKeyboardMarkup(**kwargs)
        except TypeError:
            continue
    return types.ReplyKeyboardMarkup()


# ============================================================
# USER KEYBOARD
# ============================================================

def user_keyboard(is_super_admin=False):
    kb = _reply_markup()

    kb.row(_btn("🛒 خرید VPN", GREEN), _btn("🛡 سرویس‌های من", BLUE))
    kb.row(_btn("🎁 تست رایگان", GREEN), _btn("💰 کیف پول", BLUE))
    kb.row(_btn("🤝 دعوت دوستان", GREEN))
    kb.row(_btn("📜 تراکنش‌های من", BLUE), _btn("🤝 پنل نمایندگی", GREEN))
    kb.row(_btn("🎫 خرید لایسنس ربات", BLUE), _btn("🆘 پشتیبانی", GREEN))
    kb.row(_btn("📚 راهنما", GREEN), _btn("⚙️ حساب کاربری", BLUE))

    if is_super_admin:
        kb.row(_btn("👑 پنل سوپر ادمین", RED))

    return kb


# ============================================================
# ADMIN KEYBOARD
# ============================================================

def admin_keyboard():
    kb = _reply_markup()

    kb.row(_btn("📊 داشبورد", BLUE), _btn("👥 کاربران", GREEN))
    kb.row(_btn("🖥 مدیریت پنل‌ها", GREEN), _btn("💎 مدیریت پلن‌های VPN", BLUE))
    kb.row(_btn("📦 سرویس‌ها", BLUE), _btn("🤝 مدیریت نمایندگان", GREEN))
    kb.row(_btn("💰 پرداخت‌ها", GREEN), _btn("💳 تنظیمات پرداخت", BLUE))
    kb.row(_btn("🎁 مدیریت تست رایگان", GREEN), _btn("📢 ارسال همگانی", BLUE))
    kb.row(_btn("📢 عضویت اجباری", BLUE), _btn("🧩 منوی کاربر", GREEN))
    kb.row(_btn("🎫 مدیریت تیکت‌ها", GREEN), _btn("👑 مدیران", BLUE))
    kb.row(_btn("💾 Backup / Restore", RED), _btn("📈 گزارش‌ها", GREEN))
    kb.row(_btn("🛡 امنیت", RED), _btn("⚙️ تنظیمات", BLUE))
    kb.row(_btn("🔧 وضعیت سیستم", GREEN))
    kb.row(_btn("🏠 منوی کاربر", BLUE))

    return kb


# ============================================================
# FORCE JOIN (inline)
# ============================================================

def force_join_markup():
    markup = types.InlineKeyboardMarkup()

    url = get_setting("force_join_url", "").strip()

    # متن دکمه‌ی عضویت، قابل تنظیم توسط ادمین از پنل (پیش‌فرض اگر خالی بود)
    btn_text = get_setting("force_join_button_text", "").strip()
    if not btn_text:
        btn_text = "📢 عضویت در کانال"

    if url:
        markup.add(_ibtn(btn_text, BLUE, url=url))

    markup.add(_ibtn("✅ بررسی عضویت", GREEN, callback_data="check_join"))

    return markup
