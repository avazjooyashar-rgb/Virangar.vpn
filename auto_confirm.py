# ============================================================
# auto_confirm.py
# تایید خودکار کارت‌به‌کارت با پیامک بانک (مبلغ یکتا)
# داخل همون پروسس ربات اجرا میشه (thread) تا SQLite قفل نشه.
#
# قبل از اجرا:  export SMS_TOKEN="یک-رشته-تصادفی-طولانی"
# ============================================================
import hashlib
import hmac
import os
import random
import re
import threading
from datetime import datetime, timedelta

from config import bot, SUPER_ADMIN_ID
from database import db_execute, now

BANK_SENDER = "ResalatBank"          # اسم فرستنده پیامک
BANK_ACCOUNT = "10.13651898.1"       # فقط حساب مخصوص فروش
SMS_TOKEN = os.environ.get("SMS_TOKEN", "")
WINDOW_MIN = 20                      # عمر یک مبلغ یکتا (دقیقه)
OPEN_STATUSES = ("awaiting", "pending")

_log_lock = threading.Lock()


def ensure_schema():
    try:
        db_execute("ALTER TABLE payments ADD COLUMN unique_amount INTEGER")
    except Exception:
        pass  # ستون از قبل هست
    db_execute(
        "CREATE TABLE IF NOT EXISTS sms_log (hash TEXT PRIMARY KEY, created_at TEXT)"
    )


def _is_recent(created_at):
    try:
        dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return False
    return datetime.utcnow() - dt <= timedelta(minutes=WINDOW_MIN)


def _recent_open_rows():
    rows = db_execute(
        "SELECT * FROM payments WHERE status IN ('awaiting','pending') "
        "AND unique_amount IS NOT NULL",
        fetchall=True,
    ) or []
    return [r for r in rows if _is_recent(r["created_at"])]


def make_unique_amount(base):
    """base + عدد ۱ تا ۹۹ که با هیچ پرداخت باز دیگه‌ای برابر نباشه."""
    used = {r["unique_amount"] for r in _recent_open_rows()}
    candidates = [base + i for i in range(1, 100) if base + i not in used]
    return random.choice(candidates) if candidates else None


def find_open_payment(amount_toman):
    rows = [r for r in _recent_open_rows() if r["unique_amount"] == amount_toman]
    return rows[0] if len(rows) == 1 else None  # دوتا بود => خودکار تایید نکن


# ------------------------------------------------------------
# پارس پیامک
# ------------------------------------------------------------
_DEPOSIT_RE = re.compile(r"^\s*(?:\+([\d,]+)|([\d,]+)\+)\s*$", re.MULTILINE)


def parse_deposit(msg):
    """مبلغ واریز به تومان یا None."""
    if BANK_SENDER not in msg or BANK_ACCOUNT not in msg:
        return None
    m = _DEPOSIT_RE.search(msg)
    if not m:
        return None
    rial = int((m.group(1) or m.group(2)).replace(",", ""))
    if rial % 10:
        return None
    return rial // 10


def _notify_admin(text):
    try:
        bot.send_message(SUPER_ADMIN_ID, text)
    except Exception:
        pass


def process_sms(msg):
    h = hashlib.sha256(msg.encode()).hexdigest()
    with _log_lock:
        if db_execute("SELECT 1 FROM sms_log WHERE hash=?", (h,), fetchone=True):
            return {"ok": False, "why": "duplicate"}
        db_execute("INSERT INTO sms_log (hash, created_at) VALUES (?, ?)", (h, now()))

    amount = parse_deposit(msg)
    if amount is None:
        return {"ok": False, "why": "not a deposit"}

    payment = find_open_payment(amount)
    if not payment:
        _notify_admin(f"⚠️ واریز {amount:,} تومان رسید ولی سفارش مطابق پیدا نشد (یا بیش از یکی بود). دستی بررسی کن.")
        return {"ok": False, "why": "no match"}

    from handlers_payment import approve_payment_core, finish_receipt_screen
    ok, info = approve_payment_core(payment["id"])
    if not ok:
        _notify_admin(f"⚠️ تایید خودکار #{payment['id']} ناموفق: {info}")
        return {"ok": False, "why": info}

    finish_receipt_screen(payment["user_id"])
    return {"ok": True, "payment_id": payment["id"]}


# ------------------------------------------------------------
# FastAPI
# ------------------------------------------------------------
def start_sms_server(host="127.0.0.1", port=8000):
    import uvicorn
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.concurrency import run_in_threadpool

    ensure_schema()
    app = FastAPI()

    @app.post("/sms")
    async def sms(req: Request, token: str = ""):
        if not SMS_TOKEN or not hmac.compare_digest(token, SMS_TOKEN):
            raise HTTPException(403)
        try:
            msg = (await req.json()).get("message", "")
        except Exception:
            raise HTTPException(400)
        return await run_in_threadpool(process_sms, msg)

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()
