# ============================================================
# pasarguard.py
# اتصال به پنل PasarGuard (تست اتصال / ساخت سرویس) +
# ثبت سرویس ساخته‌شده در دیتابیس داخلی
# ============================================================

from datetime import datetime, timedelta

import requests

from db import db_execute, now


def pasarguard_test_panel(panel):
    """
    این قسمت عمداً endpoint جعلی ندارد.
    چون endpoint و authentication دقیق PasarGuard
    باید مطابق نسخه/API واقعی پنل تنظیم شود.
    """

    url = (panel["url"] or "").rstrip("/")

    if not url:
        return {"success": False, "error": "Panel URL is empty"}

    try:
        response = requests.get(url, timeout=8, verify=False)

        if response.status_code < 500:
            return {"success": True, "error": ""}

        return {"success": False, "error": f"HTTP {response.status_code}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def pasarguard_create_service(panel, telegram_user, plan):
    """
    مهم: این تابع محل اتصال واقعی به PasarGuard است.
    endpoint ساخت کاربر/سرویس در نسخه‌های مختلف می‌تواند متفاوت باشد.
    تا API واقعی پنل مشخص نباشد، کانفیگ ساختگی تولید نمی‌کنیم.
    """

    return {
        "success": False,
        "error": (
            "PasarGuard API endpoint for service creation "
            "is not configured."
        )
    }


def create_local_service(user, plan, panel, result):
    config = result.get("config", "")
    qr = result.get("qr", "")

    expires = (
        datetime.utcnow() + timedelta(days=int(plan["duration"]))
    ).strftime("%Y-%m-%d %H:%M:%S")

    username = result.get("username", f"tg_{user['telegram_id']}")

    db_execute("""
    INSERT INTO services
    (user_id, plan_id, panel_id,
     username, config, qr,
     volume, used_volume,
     duration, devices,
     expires_at, status,
     created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 'active', ?, ?)
    """, (
        user["id"],
        plan["id"],
        panel["id"],
        username,
        config,
        qr,
        plan["volume"],
        plan["duration"],
        plan["devices"],
        expires,
        now(),
        now()
    ))

    service = db_execute("""
    SELECT * FROM services
    WHERE user_id=?
    ORDER BY id DESC
    LIMIT 1
    """, (user["id"],), fetchone=True)

    return service
