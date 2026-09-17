# ============================================================
# models.py
# عملیات مربوط به کاربران و مدیران روی دیتابیس
# ============================================================

from database import db_execute, now


# ============================================================
# USERS
# ============================================================

def ensure_user(tg_user):
    existing = db_execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (tg_user.id,),
        fetchone=True
    )

    if existing:
        db_execute("""
        UPDATE users
        SET username=?, first_name=?, updated_at=?
        WHERE telegram_id=?
        """, (
            tg_user.username or "",
            tg_user.first_name or "",
            now(),
            tg_user.id
        ))
        return existing

    db_execute("""
    INSERT INTO users
    (telegram_id, username, first_name, balance,
     is_blocked, is_reseller, created_at, updated_at)
    VALUES (?, ?, ?, 0, 0, 0, ?, ?)
    """, (
        tg_user.id,
        tg_user.username or "",
        tg_user.first_name or "",
        now(),
        now()
    ))

    return db_execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (tg_user.id,),
        fetchone=True
    )


def get_user(tg_id):
    return db_execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (tg_id,),
        fetchone=True
    )


def internal_user_id(tg_id):
    user = get_user(tg_id)
    return user["id"] if user else None


# ============================================================
# ADMINS
# ============================================================

def is_admin(tg_id):
    row = db_execute("""
    SELECT 1 FROM admins
    WHERE telegram_id=? AND is_active=1
    """, (tg_id,), fetchone=True)

    return bool(row)


def is_superadmin(tg_id):
    row = db_execute("""
    SELECT 1 FROM admins
    WHERE telegram_id=? AND role='superadmin' AND is_active=1
    """, (tg_id,), fetchone=True)

    return bool(row)
