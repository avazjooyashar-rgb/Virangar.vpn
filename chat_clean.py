# ============================================================
# chat_clean.py
# ابزار تمیز نگه داشتن صفحه‌ی چت:
# فقط «مرحله‌ی فعلی» می‌مونه و پیام‌های قبلی پاک میشن.
#
# استفاده:
#   from chat_clean import show, drop, safe_delete, drop_screen
#
#   drop(message)                    -> پیام خود کاربر (مثلاً دکمه‌ی منو) رو پاک می‌کنه
#   show(chat_id, text, **kwargs)    -> پیام جدید می‌فرسته و «صفحه‌ی» قبلی همون چت رو پاک می‌کنه
#   drop_screen(chat_id)             -> صفحه‌ی فعلی رو پاک می‌کنه
#   safe_delete(chat_id, message_id) -> پاک کردن بی‌خطر یه پیام
#
# key: هر «نوع صفحه» یه کلید داره (پیش‌فرض "main") تا صفحه‌های
# مستقل همدیگه رو پاک نکنن (مثلاً منوی کاربر و منوی ادمین).
# ============================================================

import threading

from config import bot

_last = {}
_lock = threading.Lock()

# وقتی یه «صفحه‌ی» جدید با این کلید نمایش داده میشه، پیام‌های موقتِ وابسته‌ش هم پاک میشن
# (مثلاً پیام خطا کنار صفحه‌ی کاربر، یا عکس رسید کنار صفحه‌ی مدیر)
_LINKED = {
    "main": ["err"],
    "admin_menu": ["admin_receipt"],
}


def safe_delete(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def delete_later(chat_id, message_id, delay=1.0):
    t = threading.Timer(delay, safe_delete, args=(chat_id, message_id))
    t.daemon = True
    t.start()


def get_screen(chat_id, key="main"):
    """آیدی پیامِ «صفحه‌ی فعلیِ» این کلید رو برمی‌گردونه (یا None)."""
    with _lock:
        return _last.get((chat_id, key))


def is_screen(chat_id, message_id, key="main"):
    """آیا این پیام همون «صفحه‌ی» فعلیِ ثبت‌شده‌ست؟ (یعنی پیام منو/مرحله‌ست، نه مثلاً کانفیگ)"""
    with _lock:
        return _last.get((chat_id, key)) == message_id


def drop(message):
    """پیام ورودی خود کاربر (مثل زدن دکمه‌ی منو) رو پاک می‌کنه."""
    safe_delete(message.chat.id, message.message_id)


def drop_screen(chat_id, key="main"):
    with _lock:
        old = _last.pop((chat_id, key), None)
    if old:
        safe_delete(chat_id, old)


def track(chat_id, message_id, key="main"):
    """پیامی که خودمون (بیرون از show) فرستادیم رو به‌عنوان «صفحه‌ی فعلی» ثبت می‌کنه."""
    with _lock:
        _last[(chat_id, key)] = message_id


def show(chat_id, text, key="main", **kwargs):
    """
    پیام جدید می‌فرسته و صفحه‌ی قبلیِ همین کلید رو پاک می‌کنه.
    برای سرعت بیشتر: اول پیام جدید فرستاده میشه (کاربر فوری جواب رو
    می‌بینه)، بعد پیام قبلی تو پس‌زمینه (بدون معطل کردن کاربر) پاک میشه.
    """
    with _lock:
        old = _last.get((chat_id, key))

    for linked in _LINKED.get(key, []):
        drop_screen(chat_id, linked)

    sent = bot.send_message(chat_id, text, **kwargs)

    with _lock:
        _last[(chat_id, key)] = sent.message_id

    if old and old != sent.message_id:
        t = threading.Timer(0, safe_delete, args=(chat_id, old))
        t.daemon = True
        t.start()

    return sent
