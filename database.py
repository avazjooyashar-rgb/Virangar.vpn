# ============================================================
# database.py
# SQLite Database
# VirangarVPN
# ============================================================

import sqlite3
import threading
from datetime import datetime

from config import DB_PATH, SUPER_ADMIN_ID


# ============================================================
# DATABASE LOCK
# ============================================================

DB_LOCK = threading.Lock()


# ============================================================
# CONNECTION
# ============================================================

def connect():
    db = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )

    db.row_factory = sqlite3.Row

    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    return db


# ============================================================
# TIME
# ============================================================

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# GENERIC DATABASE EXECUTOR
# ============================================================

def db_execute(
    sql,
    params=(),
    fetchone=False,
    fetchall=False,
    commit=True
):
    with DB_LOCK:

        db = connect()

        try:

            cur = db.cursor()

            cur.execute(sql, params)

            result = None

            if fetchone:
                result = cur.fetchone()

            elif fetchall:
                result = cur.fetchall()

            if commit:
                db.commit()

            return result

        finally:
            db.close()


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db():

    with DB_LOCK:

        db = connect()
        cur = db.cursor()

        # ====================================================
        # USERS
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            is_reseller INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
        """)

        # ====================================================
        # ADMINS
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            role TEXT DEFAULT 'admin',
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
        """)

        # ====================================================
        # PANELS
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            username TEXT,
            password TEXT,
            api_token TEXT,
            active INTEGER DEFAULT 1,
            status TEXT DEFAULT 'unknown',
            capacity INTEGER DEFAULT 0,
            assigned_sales INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
        """)

        # ====================================================
        # PLANS
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price INTEGER NOT NULL,
            volume INTEGER NOT NULL,
            duration INTEGER NOT NULL,
            devices INTEGER DEFAULT 1,
            reseller_price INTEGER DEFAULT 0,
            location TEXT,
            panel_id INTEGER,
            active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT,
            FOREIGN KEY(panel_id)
                REFERENCES panels(id)
                ON DELETE SET NULL
        )
        """)

        # ====================================================
        # PLANS MIGRATION
        # برای دیتابیس‌های قدیمی
        # ====================================================

        plan_columns = {
            row["name"]
            for row in cur.execute(
                "PRAGMA table_info(plans)"
            ).fetchall()
        }

        if "description" not in plan_columns:

            cur.execute("""
            ALTER TABLE plans
            ADD COLUMN description TEXT DEFAULT ''
            """)

        # ====================================================
        # SERVICES
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_id INTEGER,
            panel_id INTEGER,
            username TEXT,
            config TEXT,
            qr TEXT,
            volume INTEGER DEFAULT 0,
            used_volume INTEGER DEFAULT 0,
            duration INTEGER DEFAULT 0,
            devices INTEGER DEFAULT 1,
            expires_at TEXT,
            status TEXT DEFAULT 'active',
            reseller_id INTEGER,
            created_at TEXT,
            updated_at TEXT,

            FOREIGN KEY(user_id)
                REFERENCES users(id),

            FOREIGN KEY(plan_id)
                REFERENCES plans(id),

            FOREIGN KEY(panel_id)
                REFERENCES panels(id)
        )
        """)

        # ====================================================
        # PAYMENTS
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_id INTEGER,
            amount INTEGER NOT NULL,
            method TEXT,
            receipt_file_id TEXT,
            receipt_type TEXT,
            custom_username TEXT,
            status TEXT DEFAULT 'pending',
            service_id INTEGER,
            created_at TEXT,
            updated_at TEXT,

            FOREIGN KEY(user_id)
                REFERENCES users(id),

            FOREIGN KEY(plan_id)
                REFERENCES plans(id)
        )
        """)

        # ====================================================
        # PAYMENTS MIGRATION
        # برای دیتابیس‌های قدیمی که ستون‌های جدید رو ندارن
        # ====================================================

        payment_columns = {
            row["name"]
            for row in cur.execute(
                "PRAGMA table_info(payments)"
            ).fetchall()
        }

        if "custom_username" not in payment_columns:

            cur.execute("""
            ALTER TABLE payments
            ADD COLUMN custom_username TEXT
            """)

        # نوع پرداخت: purchase (خرید جدید) / renew (تمدید) / increase (افزایش حجم) / wallet (شارژ کیف پول)
        if "type" not in payment_columns:

            cur.execute("""
            ALTER TABLE payments
            ADD COLUMN type TEXT DEFAULT 'purchase'
            """)

        # سرویسی که این پرداخت (تمدید/افزایش حجم) روش اعمال می‌شود
        if "target_service_id" not in payment_columns:

            cur.execute("""
            ALTER TABLE payments
            ADD COLUMN target_service_id INTEGER
            """)

        # مقدار گیگ اضافه‌شده در حالت افزایش حجم
        if "extra_volume" not in payment_columns:

            cur.execute("""
            ALTER TABLE payments
            ADD COLUMN extra_volume INTEGER DEFAULT 0
            """)

        # تعداد روز اضافه‌شده در حالت تمدید
        if "extra_days" not in payment_columns:

            cur.execute("""
            ALTER TABLE payments
            ADD COLUMN extra_days INTEGER DEFAULT 0
            """)

        # ====================================================
        # TRANSACTIONS
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            type TEXT,
            description TEXT,
            reference TEXT,
            created_at TEXT,

            FOREIGN KEY(user_id)
                REFERENCES users(id)
        )
        """)

        # ====================================================
        # RESELLER PLANS
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS reseller_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            capacity INTEGER DEFAULT 0,
            duration INTEGER DEFAULT 30,
            active INTEGER DEFAULT 1,
            panel_id INTEGER,
            created_at TEXT,

            FOREIGN KEY(panel_id)
                REFERENCES panels(id)
                ON DELETE SET NULL
        )
        """)

        # ====================================================
        # RESELLER PANELS
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS reseller_panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reseller_plan_id INTEGER,
            name TEXT,
            balance INTEGER DEFAULT 0,
            expires_at TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT,

            FOREIGN KEY(user_id)
                REFERENCES users(id),

            FOREIGN KEY(reseller_plan_id)
                REFERENCES reseller_plans(id)
        )
        """)

        # ====================================================
        # TICKETS
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subject TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT,
            updated_at TEXT,

            FOREIGN KEY(user_id)
                REFERENCES users(id)
        )
        """)

        # ====================================================
        # TICKET MESSAGES
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS ticket_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            message TEXT,
            created_at TEXT,

            FOREIGN KEY(ticket_id)
                REFERENCES tickets(id)
        )
        """)

        # ====================================================
        # LICENSES
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_name TEXT,
            price INTEGER DEFAULT 0,
            license_key TEXT UNIQUE,
            expires_at TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT,

            FOREIGN KEY(user_id)
                REFERENCES users(id)
        )
        """)

        # ====================================================
        # SETTINGS
        # ====================================================

        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        # ====================================================
        # SUPER ADMIN
        # ====================================================

        if SUPER_ADMIN_ID:

            cur.execute("""
            INSERT OR IGNORE INTO admins
            (
                telegram_id,
                role,
                is_active,
                created_at
            )
            VALUES (?, 'superadmin', 1, ?)
            """, (
                SUPER_ADMIN_ID,
                now()
            ))

        # ====================================================
        # DEFAULT SETTINGS
        # ====================================================

        defaults = {

            # Force Join
            "force_join_enabled": "0",
            "force_join_channel": "",
            "force_join_url": "",

            # Payment
            "payment_mode": "manual",
            "manual_payment_enabled": "1",

            "card_number": "",
            "card_holder": "",

            # Online Gateway
            "online_payment_enabled": "0",
            "gateway_provider": "",
            "gateway_api_key": "",
            "gateway_merchant_id": "",

            # Trial
            "trial_enabled": "1",
            "trial_volume": "5",
            "trial_duration": "1",
            "trial_devices": "1",
            "trial_limit": "1",

            # Renewal / Volume increase
            "extra_gb_price": "5000",

            # Support
            "support_username": "",

            # Backup
            "backup_enabled": "1",
            "backup_interval_hours": "24",
            "backup_retention_days": "30",
        }

        for key, value in defaults.items():

            cur.execute("""
            INSERT OR IGNORE INTO settings
            (key, value)
            VALUES (?, ?)
            """, (
                key,
                value
            ))

        # ====================================================
        # DEFAULT PLANS
        # ====================================================

        count = cur.execute(
            "SELECT COUNT(*) FROM plans"
        ).fetchone()[0]

        if count == 0:

            default_plans = [

                (
                    "1 ماهه 20GB",
                    "",
                    100000,
                    20,
                    30,
                    1,
                    0,
                    "",
                    None
                ),

                (
                    "1 ماهه 50GB",
                    "",
                    180000,
                    50,
                    30,
                    2,
                    0,
                    "",
                    None
                ),

                (
                    "2 ماهه 100GB",
                    "",
                    320000,
                    100,
                    60,
                    3,
                    0,
                    "",
                    None
                ),
            ]

            for plan in default_plans:

                cur.execute("""
                INSERT INTO plans
                (
                    name,
                    description,
                    price,
                    volume,
                    duration,
                    devices,
                    reseller_price,
                    location,
                    panel_id,
                    active,
                    sort_order,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)
                """, (
                    plan[0],
                    plan[1],
                    plan[2],
                    plan[3],
                    plan[4],
                    plan[5],
                    plan[6],
                    plan[7],
                    plan[8],
                    now()
                ))

        # ====================================================
        # COMMIT
        # ====================================================

        db.commit()
        db.close()


# ============================================================
# SETTINGS - GET
# ============================================================

def get_setting(key, default=""):

    row = db_execute(
        """
        SELECT value
        FROM settings
        WHERE key=?
        """,
        (key,),
        fetchone=True
    )

    if row:
        return row["value"]

    return default


# ============================================================
# SETTINGS - SET
# ============================================================

def set_setting(key, value):

    db_execute(
        """
        INSERT INTO settings
        (
            key,
            value
        )
        VALUES (?, ?)

        ON CONFLICT(key)
        DO UPDATE SET
            value=excluded.value
        """,
        (
            key,
            str(value)
        )
    )


# ============================================================
# DATABASE HEALTH CHECK
# ============================================================

def database_health():

    try:

        row = db_execute(
            "SELECT 1 AS ok",
            fetchone=True
        )

        return bool(row and row["ok"] == 1)

    except Exception:

        return False
