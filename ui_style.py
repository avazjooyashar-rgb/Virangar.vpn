# ============================================================
# ui_style.py
# ظاهر خفن‌تر برای کل ربات:
#   1) رنگ خودکار دکمه‌های شیشه‌ای (سبز / آبی / قرمز) بر اساس نوع دکمه،
#      بدون اینکه لازم باشه تک‌تک فایل‌ها رو دست بزنی
#   2) دکمه‌ی «📋 کپی لینک اشتراک» (با یک لمس کپی میشه)
#   3) افکت کانفتی 🎉 روی پیام تحویل سرویس
#
# همه‌چیز با fallback امنه: اگه کتابخونه یا تلگرام چیزی رو پشتیبانی نکنه،
# همون پیام بدون اون ویژگی فرستاده میشه و بات خطا نمیده.
#
# خاموش کردن کامل رنگ‌ها: ENABLED رو False کن.
# ============================================================
import io
from telebot import types

ENABLED = True

GREEN = "success"
BLUE = "primary"
RED = "danger"

CONFETTI = "5046509860389126442"  # 🎉

# --- قانون‌ها بر اساس callback_data (اولویت اول) ---
_RED_CB = (
    "resdel", "delsvc", "payreject", "ares:pdel", "ares:tier_del",
    "ares:custom_off", "respoolpause", "respause",
)
_GREEN_CB = (
    "payapprove", "resmk_confirm", "rescustomvol_go", "renewwallet",
    "incwallet", "walletpay", "manual:", "renewcard", "inccard",
    "respoolresume", "resresume", "resnew:", "res_buy", "check_join",
    "ares:plan_new", "ares:tier_new",
)
_BLUE_CB = (
    "go_home", "res_menu", "res_pools", "res_customers", "res_stats",
    "services_back", "respoolrefresh", "rescustrefresh", "respoolonline",
    "respoolchart", "respooltopup", "resqr",
)

# --- قانون‌ها بر اساس متن دکمه (اگه callback جور نشد) ---
_RED_TEXT_START = ("❌", "🗑")
_RED_TEXT_HAS = ("حذف", "انصراف")
_GREEN_TEXT_START = ("✅", "🛒", "➕", "▶️", "💳", "🎉", "💰 پرداخت", "🔄 شروع دوباره")
_GREEN_TEXT_HAS = ("خرید دوباره", "تأیید", "تایید", "بساز")
_BLUE_TEXT_START = ("🏠", "🔄", "📶", "📊", "📈", "📱", "🔐", "🔋", "🤝", "📋")


def _auto_style(text, callback_data):
    cb = callback_data or ""
    t = text or ""

    if cb:
        if cb.startswith(_RED_CB):
            return RED
        if cb.startswith(_GREEN_CB):
            return GREEN
        if cb.startswith(_BLUE_CB):
            return BLUE

    if t.startswith(_RED_TEXT_START) or any(w in t for w in _RED_TEXT_HAS):
        return RED
    if t.startswith(_GREEN_TEXT_START) or any(w in t for w in _GREEN_TEXT_HAS):
        return GREEN
    if t.startswith(_BLUE_TEXT_START):
        return BLUE
    return None


# ============================================================
# PATCH: دکمه‌ها style / copy_text رو حتی با کتابخونه‌ی قدیمی‌تر بفرستن
# ============================================================
def _patch(cls, inline):
    if not hasattr(cls, "to_dict"):
        return
    orig_init = cls.__init__
    orig_to_dict = cls.to_dict

    def __init__(self, *args, **kwargs):
        style = kwargs.pop("style", None)
        icon = kwargs.pop("icon_custom_emoji_id", None)
        orig_init(self, *args, **kwargs)
        if style is None and inline:
            text = args[0] if args else kwargs.get("text")
            style = _auto_style(text, kwargs.get("callback_data"))
        self._ui_style = style
        self._ui_icon = icon

    def to_dict(self):
        data = orig_to_dict(self)
        if ENABLED:
            style = getattr(self, "_ui_style", None)
            if style:
                data["style"] = style
        icon = getattr(self, "_ui_icon", None)
        if icon:
            data["icon_custom_emoji_id"] = icon
        copy_value = getattr(self, "_ui_copy", None)
        if copy_value:
            data.pop("callback_data", None)
            data["copy_text"] = {"text": copy_value}
        return data

    cls.__init__ = __init__
    cls.to_dict = to_dict


def install():
    if getattr(types, "_ui_style_installed", False):
        return
    _patch(types.InlineKeyboardButton, inline=True)
    _patch(types.KeyboardButton, inline=False)
    types._ui_style_installed = True


install()


# ============================================================
# دکمه‌ی کپی
# ============================================================
def copy_button(text, value, style=BLUE):
    """دکمه‌ای که با لمس، value رو کپی می‌کنه (۱ تا ۲۵۶ کاراکتر)."""
    value = str(value or "")
    if not value or len(value) > 256:
        return None
    btn = types.InlineKeyboardButton(text, callback_data="noop")
    btn._ui_copy = value
    btn._ui_style = style
    return btn


def with_copy_button(kb, value, label="📋 کپی لینک اشتراک"):
    """کپی از کیبورد با دکمه‌ی کپی در ردیف اول. اگه نشد، همون کیبورد."""
    btn = copy_button(label, value)
    if btn is None:
        return kb
    new_kb = types.InlineKeyboardMarkup()
    new_kb.add(btn)
    for row in (getattr(kb, "keyboard", None) or []):
        new_kb.row(*row)
    return new_kb


# ============================================================
# ارسال با fallback (افکت → بدون افکت → بدون دکمه‌ی کپی)
# ============================================================
def _attempts(kb, plain_kb, effect):
    attempts = []
    if effect:
        attempts.append({"reply_markup": kb, "message_effect_id": effect})
    attempts.append({"reply_markup": kb})
    if plain_kb is not kb:
        attempts.append({"reply_markup": plain_kb})
    return attempts


def send_photo_fancy(bot, chat_id, photo_bytes, caption, kb=None, plain_kb=None, effect=None):
    last = None
    for kwargs in _attempts(kb, plain_kb, effect):
        try:
            return bot.send_photo(
                chat_id, io.BytesIO(photo_bytes),
                caption=caption, parse_mode="HTML", **kwargs
            )
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def send_text_fancy(bot, chat_id, text, kb=None, plain_kb=None, effect=None):
    last = None
    for kwargs in _attempts(kb, plain_kb, effect):
        try:
            return bot.send_message(chat_id, text, parse_mode="HTML", **kwargs)
        except Exception as e:  # noqa: BLE001
            last = e
    raise last
