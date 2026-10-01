# ============================================================
# reseller_billing.py
# کارگر پس‌زمینه: هر چند دقیقه مصرف واقعیِ مشتری‌های هر نماینده
# رو از پنل می‌خونه، از استخر حجم همون نماینده کم می‌کنه، و اگه
# استخر صفر شد، سرویس‌های اون نماینده رو رو پنل غیرفعال می‌کنه.
#
# نحوه‌ی راه‌اندازی: کافیه این فایل یه‌بار ایمپورت بشه (مثلاً تو
# main.py کنار بقیه‌ی importها: `import reseller_billing`).
# همون لحظه‌ی ایمپورت، ترد پس‌زمینه شروع به کار می‌کنه.
# ============================================================

import logging
import threading
import time

from config import bot
from database import db_execute, get_setting, now
from pasarguard_api import pasarguard_get_user_usage, pasarguard_set_status

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def _get_panel(panel_id):
    if not panel_id:
        return None
    return db_execute("SELECT * FROM panels WHERE id=?", (panel_id,), fetchone=True)


def _get_pool(reseller_user_id, panel_id):
    return db_execute("""
    SELECT * FROM reseller_panels
    WHERE user_id=? AND panel_id=? AND active=1
    """, (reseller_user_id, panel_id), fetchone=True)


def _disable_pool_services(reseller_user_id, panel_id, panel):
    """
    وقتی استخر یه نماینده تو یه پنل خاص صفر می‌شه، همه‌ی سرویس‌های
    فعالِ همون نماینده رو همون پنل، رو پنل غیرفعال می‌شن.
    """
    siblings = db_execute("""
    SELECT * FROM services
    WHERE reseller_id=? AND panel_id=? AND status='active' AND is_unlimited=1
    """, (reseller_user_id, panel_id), fetchall=True) or []

    disabled_count = 0
    for svc in siblings:
        if not svc["username"]:
            continue
        try:
            result = pasarguard_set_status(panel, svc["username"], enabled=False)
        except Exception:
            logger.exception("pasarguard_set_status crashed for service %s", svc["id"])
            continue

        if result.get("success"):
            db_execute(
                "UPDATE services SET status='disabled', updated_at=? WHERE id=?",
                (now(), svc["id"])
            )
            disabled_count += 1

    return disabled_count


def _notify_pool_exhausted(reseller_user_id, pool_name, disabled_count):
    user = db_execute("SELECT * FROM users WHERE id=?", (reseller_user_id,), fetchone=True)
    if not user:
        return
    try:
        bot.send_message(
            user["telegram_id"],
            "🚫 <b>استخر حجم نمایندگی تموم شد!</b>\n\n"
            f"🖥 استخر: {pool_name or '---'}\n"
            f"⛔ {disabled_count} تا از سرویس‌های مشتری‌هات به همین دلیل غیرفعال شدن.\n\n"
            "برای فعال‌سازی دوباره، از «🤝 پنل نمایندگی → 🛒 خرید حجم نمایندگی» شارژ کن.",
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("notify_pool_exhausted failed")


def _tick():
    """یه دور کامل چک مصرفِ همه‌ی سرویس‌های نامحدودِ زیرمجموعه‌ی نماینده‌ها."""
    services = db_execute("""
    SELECT * FROM services
    WHERE is_unlimited=1 AND status='active' AND reseller_id IS NOT NULL
    """, fetchall=True) or []

    for svc in services:
        try:
            _process_service(svc)
        except Exception:
            logger.exception("reseller_billing: processing service %s failed", svc["id"])


def _process_service(svc):
    if not svc["username"] or not svc["panel_id"]:
        return

    panel = _get_panel(svc["panel_id"])
    if not panel:
        return

    usage = pasarguard_get_user_usage(panel, svc["username"])
    if not usage.get("success"):
        return

    new_used = float(usage.get("used_gb") or 0)
    old_used = float(svc["used_volume"] or 0)

    # همیشه آخرین مصرفِ خونده‌شده رو ذخیره می‌کنیم، حتی اگه دلتا صفر/منفی باشه
    db_execute(
        "UPDATE services SET used_volume=?, updated_at=? WHERE id=?",
        (new_used, now(), svc["id"])
    )

    delta = new_used - old_used
    if delta <= 0:
        # منفی یعنی احتمالاً مصرف رو پنل ریست شده (مثلاً دستی توسط ادمین پنل)؛
        # چیزی از استخر کم نمی‌کنیم، فقط مبنای بعدی رو آپدیت کردیم.
        return

    pool = _get_pool(svc["reseller_id"], svc["panel_id"])
    if not pool:
        # نماینده استخر فعالی برای این پنل نداره (شاید دستی/قدیمی)؛ کاری نمی‌کنیم
        return

    new_balance = round(max(0, (pool["balance"] or 0) - delta), 3)

    db_execute(
        "UPDATE reseller_panels SET balance=?, updated_at=? WHERE id=?",
        (new_balance, now(), pool["id"])
    )
    db_execute("""
    INSERT INTO reseller_usage_log
    (reseller_panel_id, service_id, amount_gb, created_at)
    VALUES (?, ?, ?, ?)
    """, (pool["id"], svc["id"], delta, now()))

    if new_balance <= 0:
        db_execute("UPDATE reseller_panels SET active=0 WHERE id=?", (pool["id"],))
        disabled_count = _disable_pool_services(svc["reseller_id"], svc["panel_id"], panel)
        _notify_pool_exhausted(svc["reseller_id"], pool["name"], disabled_count)


def _loop():
    logger.info("reseller_billing: background worker started")
    while True:
        try:
            interval_minutes = int(get_setting("reseller_check_interval_minutes", "15") or "15")
        except Exception:
            interval_minutes = 15
        interval_minutes = max(1, interval_minutes)

        try:
            _tick()
        except Exception:
            logger.exception("reseller_billing: tick crashed")

        time.sleep(interval_minutes * 60)


def start():
    """اگه قبلاً استارت نشده، ترد پس‌زمینه رو راه می‌اندازه. صدا زدن چندباره بی‌خطره."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
        t = threading.Thread(target=_loop, daemon=True)
        t.start()


# با همین ایمپورت شدن فایل، کارگر پس‌زمینه شروع به کار می‌کنه
start()
