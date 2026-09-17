# ============================================================
# services.py
# ذخیره‌سازی سرویس در دیتابیس محلی پس از ساخت روی پنل
# ============================================================

from datetime import datetime, timedelta

from database import db_execute, now


def create_local_service(user, plan, panel, result):
    config = result.get("config", "")
    qr = result.get("qr", "")

    expires = (
        datetime.utcnow()
        + timedelta(days=int(plan["duration"]))
    ).strftime("%Y-%m-%d %H:%M:%S")

    username = result.get(
        "username",
        f"tg_{user['telegram_id']}"
    )

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
    """, (
        user["id"],
    ), fetchone=True)

    return service
