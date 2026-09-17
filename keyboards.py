# ============================================================
# keyboards.py
# کیبوردهای اصلی کاربر و مدیر + کیبورد لیست پلن‌ها
# ============================================================

from telebot import types

from db import db_execute


def user_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)

    kb.row("🛒 خرید VPN", "🛡 سرویس‌های من")
    kb.row("🎁 تست رایگان", "💰 کیف پول")
    kb.row("📜 تراکنش‌های من", "🤝 پنل نمایندگی")
    kb.row("🎫 خرید لایسنس ربات", "🆘 پشتیبانی")
    kb.row("📚 راهنما", "⚙️ حساب کاربری")

    return kb


def admin_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)

    kb.row("📊 داشبورد", "👥 کاربران")
    kb.row("🖥 پنل‌ها", "💎 پلن‌های VPN")
    kb.row("📦 سرویس‌ها", "🤝 نمایندگان")
    kb.row("💰 پرداخت‌ها", "💳 تنظیمات پرداخت")
    kb.row("🎁 تست رایگان", "📢 ارسال همگانی")
    kb.row("📢 عضویت اجباری", "🧩 منوی کاربر")
    kb.row("🎫 تیکت‌ها", "👑 مدیران")
    kb.row("💾 Backup / Restore", "📈 گزارش‌ها")
    kb.row("🛡 امنیت", "⚙️ تنظیمات")
    kb.row("🔧 وضعیت سیستم")
    kb.row("🏠 منوی کاربر")

    return kb


def plans_keyboard():
    plans = db_execute("""
    SELECT * FROM plans
    WHERE active=1
    ORDER BY sort_order, id
    """, fetchall=True)

    kb = types.InlineKeyboardMarkup()

    for plan in plans:
        kb.add(
            types.InlineKeyboardButton(
                f"💎 {plan['name']} | {plan['price']:,} تومان",
                callback_data=f"plan:{plan['id']}"
            )
        )

    return kb
