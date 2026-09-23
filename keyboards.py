# ============================================================
# keyboards.py
# کیبوردهای Reply و Inline مشترک
# ============================================================

from telebot import types

from database import get_setting


def user_keyboard(is_super_admin=False):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)

    kb.row("🛒 خرید VPN", "🛡 سرویس‌های من")
    kb.row("🎁 تست رایگان", "💰 کیف پول")
    kb.row("📜 تراکنش‌های من", "🤝 پنل نمایندگی")
    kb.row("🎫 خرید لایسنس ربات", "🆘 پشتیبانی")
    kb.row("📚 راهنما", "⚙️ حساب کاربری")

    if is_super_admin:
        kb.row("👑 پنل سوپر ادمین")

    return kb


def admin_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)

    kb.row("📊 داشبورد", "👥 کاربران")
    kb.row("🖥 مدیریت پنل‌ها", "💎 مدیریت پلن‌های VPN")
    kb.row("📦 سرویس‌ها", "🤝 نمایندگان")
    kb.row("💰 پرداخت‌ها", "💳 تنظیمات پرداخت")
    kb.row("🎁 مدیریت تست رایگان", "📢 ارسال همگانی")
    kb.row("📢 عضویت اجباری", "🧩 منوی کاربر")
    kb.row("🎫 مدیریت تیکت‌ها", "👑 مدیران")
    kb.row("💾 Backup / Restore", "📈 گزارش‌ها")
    kb.row("🛡 امنیت", "⚙️ تنظیمات")
    kb.row("🔧 وضعیت سیستم")
    kb.row("🏠 منوی کاربر")

    return kb


def force_join_markup():
    markup = types.InlineKeyboardMarkup()

    url = get_setting("force_join_url", "").strip()

    if url:
        markup.add(
            types.InlineKeyboardButton(
                "📢 عضویت در کانال",
                url=url
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            "✅ بررسی عضویت",
            callback_data="check_join"
        )
    )

    return markup
