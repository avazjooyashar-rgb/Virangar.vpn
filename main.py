# ============================================================
# main.py
# نقطه ورود اصلی ربات
# همه ماژول‌های هندلر اینجا import می‌شوند تا روی bot ثبت شوند
# ترتیب مهم است: fallback.py باید همیشه آخر import شود.
# ============================================================

from config import bot, BOT_NAME, SUPER_ADMIN_ID
from database import init_db, DB_PATH

# ---------------- USER-SIDE HANDLERS ----------------
import force_join          # noqa: F401  (/start, عضویت اجباری)
import handlers_shop        # noqa: F401  (خرید VPN، سرویس‌های من)
import handlers_payment     # noqa: F401  (پرداخت‌ها، تأیید/رد)
import handlers_wallet      # noqa: F401  (کیف پول، تراکنش‌ها)
import handlers_trial       # noqa: F401  (تست رایگان)
import handlers_reseller    # noqa: F401  (پنل نمایندگی)
import handlers_license     # noqa: F401  (لایسنس ربات)
import handlers_support     # noqa: F401  (پشتیبانی، تیکت)
import handlers_misc        # noqa: F401  (راهنما، حساب کاربری)

# ---------------- ADMIN-SIDE HANDLERS ----------------
import admin_dashboard          # noqa: F401  (/admin، داشبورد، کاربران)
import admin_panels             # noqa: F401  (پنل‌های PasarGuard)
import admin_plans              # noqa: F401  (پلن‌های VPN)
import admin_services           # noqa: F401  (سرویس‌ها، نمایندگان)
import admin_payment_settings   # noqa: F401  (تنظیمات پرداخت، /setcard)
import admin_broadcast          # noqa: F401  (همگانی، عضویت اجباری)
import admin_tickets            # noqa: F401  (تیکت‌های ادمین)
import admin_user_menu          # noqa: F401  (سوییچ مستقیم ادمین به منوی کاربر)
# import admin_management       # noqa: F401  (مدیران، بکاپ، گزارش، امنیت، تنظیمات) — فایل وجود نداره، موقتاً غیرفعال شد

# ---------------- FALLBACK (باید آخرین import باشد) ----------------
import fallback                 # noqa: F401


if __name__ == "__main__":
    init_db()

    print("=" * 50)
    print(f"{BOT_NAME} Bot is running...")
    print(f"Database: {DB_PATH}")
    print(f"Super Admin: {SUPER_ADMIN_ID}")
    print("=" * 50)

    bot.infinity_polling(
        skip_pending=True,
        allowed_updates=["message", "callback_query"]
    )
