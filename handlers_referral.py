# ============================================================
# handlers_referral.py
# چالش دعوت دوستان: دعوت ۷ نفر => ۱۰ گیگ (بعد از ۲ روز بررسی)
#
# ضد سوءاستفاده:
#  - هر آیدی تلگرام فقط یک بار برای همیشه در جدول referrals ثبت می‌شود
#    (PRIMARY KEY)، پس خروج و ورود دوباره‌ی همان افراد شمرده نمی‌شود
#  - فقط کاربر کاملاً جدید (که قبلاً در جدول users نبوده) معتبر است
#  - رفرال فقط بعد از «گرفتن واقعی تست رایگان» فعال می‌شود
#  - بعد از ۴۸ ساعت دوباره همه‌ی ۷ نفر بررسی می‌شوند (عضویت/بلاک)
#  - هر کاربر فقط یک بار در عمرش جایزه می‌گیرد
#  - خودرفرالی ممنوع، و تأیید دستی ادمین (قابل خاموش شدن)
# ============================================================

import time
import logging
import threading
import secrets

from telebot import types
from telebot.apihelper import ApiTelegramException

from config import bot
from database import db_execute, get_setting, set_setting
from models import get_user, is_admin
from pasarguard_api import pasarguard_create_service
from services import create_local_service
from handlers_trial import get_trial_panel, username_taken, USERNAME_PREFIX

logger = logging.getLogger(__name__)

# ------------------------- تنظیمات ثابت (اینجا ویرایش کن) -------------------------
CHECK_SERVICE_EXISTS = False         # اگر True باشد سرویس تست دعوت‌شده باید هنوز در services باشد
WORKER_INTERVAL = 600                # هر چند ثانیه جایزه‌های رسیده بررسی شوند
WORKER_FIRST_DELAY = 60              # تأخیر اولین اجرا (تا init_db فرصت اجرا داشته باشد)
# ------------------------------------------------------------------------------------

_pay_lock = threading.Lock()
_bot_username_cache = {"v": None}


# ============================================================
# DB
# ============================================================

def init_referral_tables():
    db_execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        invited_id INTEGER PRIMARY KEY,
        inviter_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        service_username TEXT,
        created_at INTEGER NOT NULL,
        activated_at INTEGER
    )
    """)
    db_execute("CREATE INDEX IF NOT EXISTS idx_ref_inviter ON referrals(inviter_id, status)")
    db_execute("""
    CREATE TABLE IF NOT EXISTS referral_rewards (
        inviter_id INTEGER PRIMARY KEY,
        status TEXT NOT NULL,
        reached_at INTEGER,
        eligible_at INTEGER,
        paid_at INTEGER,
        service_username TEXT
    )
    """)


try:
    init_referral_tables()
except Exception:
    logger.exception("init_referral_tables failed")


# ============================================================
# HELPERS
# ============================================================

def _cfg_int(key, default):
    try:
        return int(float(get_setting(key, str(default))))
    except Exception:
        return default


def _target():
    return max(1, _cfg_int("ref_target", 7))


def _safe_send(chat_id, text, **kw):
    try:
        return bot.send_message(chat_id, text, parse_mode="HTML", **kw)
    except Exception:
        logger.exception("send_message failed for %s", chat_id)
        return None


def _bot_username():
    if not _bot_username_cache["v"]:
        _bot_username_cache["v"] = bot.get_me().username
    return _bot_username_cache["v"]


def _user_exists(tg_id):
    """اگر خطا بدهد True برمی‌گرداند (محتاطانه: رفرال ثبت نشود)."""
    try:
        return get_user(tg_id) is not None
    except Exception:
        logger.exception("_user_exists failed")
        return True


def _referral_row(invited_id):
    return db_execute("SELECT * FROM referrals WHERE invited_id=?", (invited_id,), fetchone=True)


def _count(inviter_id, status):
    row = db_execute(
        "SELECT COUNT(*) c FROM referrals WHERE inviter_id=? AND status=?",
        (inviter_id, status), fetchone=True
    )
    return row["c"] if row else 0


def _get_reward(inviter_id):
    return db_execute("SELECT * FROM referral_rewards WHERE inviter_id=?", (inviter_id,), fetchone=True)


# ============================================================
# STEP 1: ثبت دعوت (در هندلر /start صدا زده شود، قبل از ساخت کاربر)
# ============================================================

def capture_referral(message):
    try:
        if get_setting("ref_enabled", "1") != "1":
            return False

        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].startswith("ref_"):
            return False

        inviter = parts[1][4:]
        if not inviter.isdigit():
            return False

        inviter = int(inviter)
        invited = message.from_user.id

        if message.from_user.is_bot or inviter == invited:
            return False
        if _referral_row(invited):
            return False                  # قبلاً ثبت شده؛ دعوت‌کننده هرگز عوض نمی‌شود
        if _user_exists(invited):
            return False                  # کاربر قدیمی است
        if not _user_exists(inviter):
            return False                  # دعوت‌کننده‌ی نامعتبر

        db_execute("""
        INSERT OR IGNORE INTO referrals (invited_id, inviter_id, status, created_at)
        VALUES (?, ?, 'pending', ?)
        """, (invited, inviter, int(time.time())))
        return True

    except Exception:
        logger.exception("capture_referral failed")
        return False


# ============================================================
# STEP 2: فعال‌شدن رفرال بعد از گرفتن تست رایگان
# ============================================================

def referral_activate(invited_tg_id, service_username=None):
    try:
        row = _referral_row(invited_tg_id)
        if not row or row["status"] != "pending":
            return

        db_execute("""
        UPDATE referrals SET status='active', activated_at=?, service_username=?
        WHERE invited_id=? AND status='pending'
        """, (int(time.time()), service_username, invited_tg_id))

        inviter = row["inviter_id"]
        count = _count(inviter, "active")
        target = _target()

        if count >= target and not _get_reward(inviter):
            now_ts = int(time.time())
            wait_h = _cfg_int("ref_wait_hours", 48)
            db_execute("""
            INSERT OR IGNORE INTO referral_rewards (inviter_id, status, reached_at, eligible_at)
            VALUES (?, 'waiting', ?, ?)
            """, (inviter, now_ts, now_ts + wait_h * 3600))
            _safe_send(
                inviter,
                f"🎉 <b>{target} نفر از دعوت‌هات ثبت شد!</b>\n\n"
                f"بعد از {wait_h} ساعت وضعیت دعوت‌شده‌ها بررسی می‌شه و جایزه‌ات فعال می‌شه.\n"
                "⚠️ تا اون موقع دعوت‌شده‌ها نباید ربات رو ترک کنن."
            )
        elif not _get_reward(inviter):
            _safe_send(inviter, f"✅ یک نفر جدید با دعوت تو ثبت شد!\nپیشرفت: <b>{count} از {target}</b>")

    except Exception:
        logger.exception("referral_activate failed")


# ============================================================
# STEP 3: بررسی نهایی بعد از ۴۸ ساعت
# ============================================================

def _is_still_valid(ref):
    invited = ref["invited_id"]

    # ۱) بلاک نکردن ربات
    try:
        bot.send_chat_action(invited, "typing")
    except ApiTelegramException as e:
        if getattr(e, "error_code", None) == 403:
            return False
    except Exception:
        logger.exception("chat_action check failed")

    # ۲) عضویت در کانال (اختیاری)
    if get_setting("force_join_enabled", "0") == "1":
        channel = get_setting("force_join_channel", "").strip()
        if channel:
            try:
                st = bot.get_chat_member(channel, invited).status
                if st in ("left", "kicked"):
                    return False
            except Exception:
                logger.exception("get_chat_member failed")

    # ۳) وجود سرویس تست (اختیاری)
    if CHECK_SERVICE_EXISTS and ref["service_username"]:
        try:
            row = db_execute("SELECT id FROM services WHERE username=? LIMIT 1",
                             (ref["service_username"],), fetchone=True)
            if not row:
                return False
        except Exception:
            logger.exception("service exists check failed")

    return True


def _notify_admins(text, kb=None):
    try:
        rows = db_execute(
            "SELECT telegram_id FROM admins WHERE is_active=1", fetchall=True
        ) or []
    except Exception:
        logger.exception("reading admins failed")
        rows = []
    for r in rows:
        _safe_send(r["telegram_id"], text, reply_markup=kb)


def _review_markup(inviter):
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ تأیید و ارسال", callback_data=f"refok:{inviter}"),
        types.InlineKeyboardButton("❌ رد", callback_data=f"refno:{inviter}"),
    )
    return kb


def _process_one(reward):
    inviter = reward["inviter_id"]
    refs = db_execute("""
    SELECT * FROM referrals WHERE inviter_id=? AND status='active'
    ORDER BY activated_at
    """, (inviter,), fetchall=True) or []

    valid = 0
    for ref in refs:
        if _is_still_valid(ref):
            valid += 1
        else:
            db_execute("UPDATE referrals SET status='left' WHERE invited_id=?", (ref["invited_id"],))

    target = _target()

    if valid < target:
        db_execute("DELETE FROM referral_rewards WHERE inviter_id=? AND status='waiting'", (inviter,))
        _safe_send(
            inviter,
            f"⚠️ تعدادی از دعوت‌شده‌هات ربات رو ترک کردن و حذف شدن.\n"
            f"پیشرفت فعلی: <b>{valid} از {target}</b>\n"
            "با دعوت افراد جدید دوباره می‌تونی به هدف برسی."
        )
        return

    if get_setting("ref_manual_approve", "1") == "1":
        db_execute("UPDATE referral_rewards SET status='review' WHERE inviter_id=? AND status='waiting'", (inviter,))
        _safe_send(inviter, "✅ بررسی انجام شد و همه‌ی دعوت‌ها معتبر بود. جایزه‌ات به‌زودی ارسال می‌شه.")
        _notify_admins(
            f"🎁 درخواست جایزه‌ی رفرال\nکاربر: <code>{inviter}</code>\nهمه‌ی {target} دعوت معتبر است.",
            _review_markup(inviter)
        )
    else:
        _pay(inviter)


def process_due_rewards():
    rows = db_execute("""
    SELECT * FROM referral_rewards WHERE status='waiting' AND eligible_at<=?
    """, (int(time.time()),), fetchall=True) or []
    for r in rows:
        try:
            _process_one(r)
        except Exception:
            logger.exception("process reward failed for %s", r["inviter_id"])


_worker_started = {"v": False}


def _worker_loop():
    time.sleep(WORKER_FIRST_DELAY)
    while True:
        try:
            process_due_rewards()
        except Exception:
            logger.exception("referral worker loop failed")
        time.sleep(WORKER_INTERVAL)


def start_referral_worker():
    if _worker_started["v"]:
        return
    _worker_started["v"] = True
    t = threading.Thread(target=_worker_loop, daemon=True, name="referral-worker")
    t.start()


# ============================================================
# پرداخت جایزه (ساخت سرویس جدید روی پنل)
# ============================================================

def _free_username(inviter):
    final = f"{USERNAME_PREFIX}_ref{inviter}"
    display = f"{USERNAME_PREFIX}.ref{inviter}"
    for _ in range(5):
        if not username_taken(final):
            return display
        suffix = secrets.token_hex(2)
        final = f"{USERNAME_PREFIX}_ref{inviter}{suffix}"
        display = f"{USERNAME_PREFIX}.ref{inviter}{suffix}"
    return display


def _pay(inviter):
    """برمی‌گرداند (موفق؟، پیام)."""
    with _pay_lock:
        reward = _get_reward(inviter)
        if not reward or reward["status"] not in ("waiting", "review"):
            return False, "قبلاً پردازش شده"

        prev_status = reward["status"]
        db_execute("UPDATE referral_rewards SET status='paying' WHERE inviter_id=?", (inviter,))

        try:
            user = get_user(inviter)
            panel = get_trial_panel()
            if not panel:
                raise RuntimeError("پنل فعالی وجود ندارد")

            gb = float(get_setting("ref_reward_gb", "10"))
            days = _cfg_int("ref_reward_days", 30)
            devices = _cfg_int("trial_devices", 1)

            plan = {"id": None, "name": "Referral Reward", "price": 0,
                    "volume": gb, "duration": days, "devices": devices}

            result = pasarguard_create_service(
                panel=panel, telegram_user=user, plan=plan,
                desired_username=_free_username(inviter)
            )
            if not result.get("success"):
                raise RuntimeError(result.get("error", "نامشخص"))

            service = create_local_service(user=user, plan=plan, panel=panel, result=result)

            db_execute("""
            UPDATE referral_rewards SET status='paid', paid_at=?, service_username=?
            WHERE inviter_id=?
            """, (int(time.time()), result.get("username"), inviter))

            gb_show = int(gb) if gb == int(gb) else gb
            _safe_send(
                inviter,
                "🎁 <b>جایزه‌ی دعوت دوستان فعال شد!</b>\n\n"
                f"📊 حجم: {gb_show} GB\n⏳ مدت: {days} روز\n\n"
                f"🔗 لینک اشتراک:\n<code>{service['config']}</code>"
            )
            return True, "ارسال شد"

        except Exception as e:
            logger.exception("reward payment failed")
            db_execute("UPDATE referral_rewards SET status=? WHERE inviter_id=?", (prev_status, inviter))
            return False, str(e)


# ============================================================
# ادمین: تأیید / رد
# ============================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("refok:") or c.data.startswith("refno:"))
def referral_admin_decision(call):
    try:
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id)
            return

        action, inviter = call.data.split(":", 1)
        inviter = int(inviter)

        if action == "refok":
            ok, msg = _pay(inviter)
            bot.answer_callback_query(call.id, ("✅ " if ok else "❌ ") + msg, show_alert=not ok)
            if ok:
                bot.edit_message_text(f"✅ جایزه برای <code>{inviter}</code> ارسال شد.",
                                      call.message.chat.id, call.message.message_id, parse_mode="HTML")
        else:
            db_execute("""
            UPDATE referral_rewards SET status='rejected'
            WHERE inviter_id=? AND status IN ('waiting','review')
            """, (inviter,))
            bot.answer_callback_query(call.id, "رد شد.")
            bot.edit_message_text(f"❌ جایزه‌ی <code>{inviter}</code> رد شد.",
                                  call.message.chat.id, call.message.message_id, parse_mode="HTML")
            _safe_send(inviter, "❌ متأسفانه درخواست جایزه‌ی دعوت دوستان تأیید نشد.")

    except Exception:
        logger.exception("referral_admin_decision crashed")


@bot.message_handler(commands=["refpending"], func=lambda m: is_admin(m.from_user.id))
def referral_pending(message):
    try:
        rows = db_execute("SELECT * FROM referral_rewards WHERE status='review'", fetchall=True) or []
        if not rows:
            _safe_send(message.chat.id, "موردی در انتظار تأیید نیست.")
            return
        for r in rows:
            _safe_send(message.chat.id, f"🎁 کاربر <code>{r['inviter_id']}</code>",
                       reply_markup=_review_markup(r["inviter_id"]))
    except Exception:
        logger.exception("referral_pending crashed")


REF_SETTINGS = {
    "enabled": "ref_enabled",        # 1 / 0
    "target": "ref_target",          # تعداد دعوت لازم
    "gb": "ref_reward_gb",           # حجم جایزه
    "days": "ref_reward_days",       # اعتبار جایزه
    "wait": "ref_wait_hours",        # ساعت انتظار قبل از بررسی
    "manual": "ref_manual_approve",  # 1 = تأیید دستی ادمین
}


@bot.message_handler(commands=["refset"], func=lambda m: is_admin(m.from_user.id))
def referral_set(message):
    try:
        parts = (message.text or "").split()
        if len(parts) == 3 and parts[1] in REF_SETTINGS:
            try:
                float(parts[2])
            except ValueError:
                _safe_send(message.chat.id, "❌ مقدار باید عدد باشد.")
                return
            set_setting(REF_SETTINGS[parts[1]], parts[2])
            _safe_send(message.chat.id, f"✅ <code>{parts[1]}</code> = <code>{parts[2]}</code>")
            return

        cur = "\n".join(f"{k} = <code>{get_setting(v, '-')}</code>" for k, v in REF_SETTINGS.items())
        _safe_send(message.chat.id, "استفاده: <code>/refset target 7</code>\n\n" + cur)
    except Exception:
        logger.exception("referral_set crashed")


@bot.message_handler(commands=["refstats"], func=lambda m: is_admin(m.from_user.id))
def referral_stats(message):
    try:
        def cnt(table, status=None):
            if status:
                r = db_execute(f"SELECT COUNT(*) c FROM {table} WHERE status=?", (status,), fetchone=True)
            else:
                r = db_execute(f"SELECT COUNT(*) c FROM {table}", fetchone=True)
            return r["c"] if r else 0

        _safe_send(
            message.chat.id,
            "📊 <b>آمار رفرال</b>\n\n"
            f"دعوت‌های ثبت‌شده: {cnt('referrals')}\n"
            f"فعال: {cnt('referrals', 'active')}\n"
            f"خارج‌شده: {cnt('referrals', 'left')}\n"
            f"در انتظار بررسی: {cnt('referral_rewards', 'waiting')}\n"
            f"در انتظار تأیید ادمین: {cnt('referral_rewards', 'review')}\n"
            f"جایزه‌های پرداخت‌شده: {cnt('referral_rewards', 'paid')}"
        )
    except Exception:
        logger.exception("referral_stats crashed")


# ============================================================
# کاربر: /myref
# ============================================================

@bot.message_handler(commands=["myref"])
@bot.message_handler(func=lambda m: m.text == "🤝 دعوت دوستان")
def my_referral(message):
    try:
        if get_setting("ref_enabled", "1") != "1":
            _safe_send(message.chat.id, "❌ چالش دعوت دوستان فعلاً غیرفعال است.")
            return

        uid = message.from_user.id
        target = _target()
        gb = get_setting("ref_reward_gb", "10")
        wait_h = _cfg_int("ref_wait_hours", 48)
        active = _count(uid, "active")
        pending = _count(uid, "pending")
        reward = _get_reward(uid)

        link = f"https://t.me/{_bot_username()}?start=ref_{uid}"

        if reward and reward["status"] == "paid":
            status = "🎁 جایزه‌ات قبلاً دریافت شده."
        elif reward and reward["status"] in ("waiting", "review", "paying"):
            status = f"⏳ هدف کامل شد؛ جایزه بعد از بررسی ({wait_h} ساعت) فعال می‌شه."
        elif reward and reward["status"] == "rejected":
            status = "❌ درخواست جایزه‌ات تأیید نشد."
        else:
            status = f"📈 پیشرفت: <b>{min(active, target)} از {target}</b>"

        text = (
            "🤝 <b>چالش دعوت دوستان</b>\n\n"
            f"{target} نفر رو دعوت کن، {gb} گیگ هدیه بگیر!\n\n"
            "شرایط:\n"
            "• فقط کاربر جدید حساب می‌شه\n"
            "• دعوت‌شده باید تست رایگان رو بگیره\n"
            f"• {wait_h} ساعت بعد از تکمیل هدف، همه بررسی می‌شن؛ اگه کسی ربات رو ترک کرده باشه حساب نمی‌شه\n"
            "• هر نفر فقط یک بار جایزه می‌گیره\n\n"
            f"{status}\n"
            f"👥 منتظر گرفتن تست: {pending} نفر\n\n"
            f"🔗 لینک اختصاصی تو:\n<code>{link}</code>"
        )
        _safe_send(message.chat.id, text)

    except Exception:
        logger.exception("my_referral crashed")


# job بررسی جایزه‌ها خودکار با ایمپورت این فایل شروع می‌شود
start_referral_worker()
