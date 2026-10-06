# ============================================================
# handlers_reseller.py  [نسخه‌ی v3]
# پنل نمایندگی از دید کاربر:
#   - خرید حجم نمایندگی (کارت به کارت، نیاز به تأیید ادمین)
#   - پنل‌های من = استخرهای حجمی که در هر پنل داره
#   - ساخت سرویس برای مشتری (نام / حجم / مدت / دستگاه + QR کد)
#   - کاربران من = لیست سرویس‌هایی که برای مشتری‌هاش ساخته
#
# تغییرات v3:
#   - ورود به «پنل نمایندگی» کیبورد منوی کاربر رو دوباره تثبیت می‌کنه
#     (پیام حامل کیبورد با کلید جدا user_menu ثبت میشه و پاک نمیشه)
#   - بعد از ساخت سرویس مشتری، همه‌چیز تو «یک پیام» میاد:
#     QR کد بالا، و زیرش مشخصات سرویس + لینک اشتراک
#   - دکمه‌ی «QR کد» تو جزئیات مشتری هم QR + لینک رو تو یک پیام می‌فرسته
#
# نکته‌ی طراحی: «مشتریِ نماینده» یک کاربر تلگرامی جدا نیست.
# سرویس زیر حساب خودِ نماینده ثبت میشه (reseller_id = خودِ نماینده).
# کم شدن از استخر «قطره‌ای» و بر اساس مصرف واقعی انجام میشه
# (کارش با reseller_billing هست، نه این فایل).
#
# نیازمندی:  pip install "qrcode[pil]"
# ============================================================

import io
import math
import re
import traceback
from datetime import datetime, timedelta
from html import escape as _esc

from telebot import types

from config import bot
from database import db_execute, get_setting, now
from models import get_user, internal_user_id, is_superadmin
from keyboards import user_keyboard
from pasarguard_api import (
    pasarguard_create_service,
    pasarguard_set_status,
    pasarguard_delete_service,
    pasarguard_get_user_usage,
)
import chat_clean as cc
import reseller_billing

try:
    import qrcode
except ImportError:  # اگه نصب نبود، لینک فقط به‌صورت متن فرستاده میشه
    qrcode = None

# فلوی چندمرحله‌ایِ «ساخت سرویس برای مشتری»
_draft = {}  # chat_id -> dict

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{2,20}$")


# ============================================================
# HELPERS
# ============================================================

def render(chat_id, text, kb, message_id=None):
    """پیام مرحله رو ادیت می‌کنه (اگه message_id بدیم) وگرنه با cc.show می‌فرسته."""
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="HTML")
            return message_id
        except Exception:
            pass
    sent = cc.show(chat_id, text, reply_markup=kb, parse_mode="HTML")
    return sent.message_id if sent else None


def _edit_screen(chat_id, text, kb):
    """برای مراحل پرسش‌وپاسخ: صفحه‌ی فعلی رو ادیت می‌کنه، وگرنه پیام جدید."""
    screen_id = cc.get_screen(chat_id)
    if screen_id:
        try:
            bot.edit_message_text(text, chat_id, screen_id, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    cc.show(chat_id, text, reply_markup=kb, parse_mode="HTML")


def _home_markup():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))
    return kb


def _ensure_menu_keyboard(chat_id, telegram_id):
    """
    کیبورد منوی کاربر رو تثبیت می‌کنه. تلگرام کیبورد پایین رو به پیامی
    وصل می‌کنه که فرستاده؛ اگه اون پیام پاک بشه کیبورد هم ناپدید میشه.
    برای همین پیام حامل با کلید جدا (user_menu) ثبت میشه تا صفحه‌های
    پنل نمایندگی پاکش نکنن، و هر بار جای قبلی رو می‌گیره (پیام تکراری نمیشه).
    """
    try:
        cc.show(
            chat_id,
            "🤝",
            key="user_menu",
            reply_markup=user_keyboard(is_super_admin=is_superadmin(telegram_id))
        )
    except Exception:
        traceback.print_exc()


def _get_pool(pool_id, owner_user_id):
    """
    اسم واقعیِ پنل (که فقط سوپرادمین می‌بینه) برنمی‌گرده؛
    اسمِ پلن نمایندگی به‌عنوان برچسب استخر نشون داده میشه.
    """
    return db_execute("""
    SELECT reseller_panels.*, reseller_plans.name AS pool_label
    FROM reseller_panels
    LEFT JOIN reseller_plans ON reseller_plans.id = reseller_panels.reseller_plan_id
    WHERE reseller_panels.id=? AND reseller_panels.user_id=?
    """, (pool_id, owner_user_id), fetchone=True)


def _pool_label(pool):
    try:
        label = pool["pool_label"]
    except (IndexError, KeyError):
        label = None
    if label:
        return label
    plan_id = pool["reseller_plan_id"] if "reseller_plan_id" in pool.keys() else None
    if plan_id:
        plan = db_execute("SELECT name FROM reseller_plans WHERE id=?", (plan_id,), fetchone=True)
        if plan and plan["name"]:
            return plan["name"]
    return f"استخر #{pool['id']}"


def _progress_bar(used, total, length=10):
    total = total or 0
    if total <= 0:
        pct = 0
    else:
        pct = min(1, max(0, used) / total)
    filled = int(pct * length)
    return "🟩" * filled + "⬜️" * (length - filled) + f"  {int(pct * 100)}٪"


def _fmt_gb(value):
    value = float(value or 0)
    if value == int(value):
        return f"{int(value)}"
    return f"{value:.2f}"


def _qr_bio(link):
    if not qrcode or not link:
        return None
    try:
        img = qrcode.make(link)
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        return bio
    except Exception:
        traceback.print_exc()
        return None


def _send_qr_message(chat_id, link, caption, kb=None):
    """
    یک پیام واحد: QR کد بالا، و کپشن (مشخصات + لینک اشتراک) زیرش.
    اگه کپشن از حد تلگرام (۱۰۲۴ کاراکتر) بلندتر بشه، QR و بعدش متن
    جدا فرستاده میشه (همچنان QR بالا و لینک پایین).
    """
    bio = _qr_bio(link)
    if bio:
        try:
            if len(caption) <= 1000:
                bot.send_photo(
                    chat_id, bio, caption=caption,
                    parse_mode="HTML", reply_markup=kb
                )
                return True
            bot.send_photo(chat_id, bio)
        except Exception:
            traceback.print_exc()
    bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)
    return False


def _send_qr(chat_id, link, username):
    """QR کد + لینک اشتراک یک سرویس (QR بالا، لینک پایین، یک پیام)."""
    caption = (
        f"📱 <b>QR کد اشتراک</b> — <code>{_esc(str(username))}</code>\n\n"
        "🔗 لینک اشتراک:\n"
        f"<code>{_esc(link)}</code>"
    )
    _send_qr_message(chat_id, link, caption)


# ============================================================
# MAIN MENU
# ============================================================

def _reseller_menu_markup():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🛒 خرید حجم نمایندگی", callback_data="res_buy"))
    kb.add(types.InlineKeyboardButton("🖥 پنل‌های من", callback_data="res_pools"))
    kb.add(types.InlineKeyboardButton("👥 کاربران من", callback_data="res_customers"))
    kb.add(types.InlineKeyboardButton("📈 آمار فروش", callback_data="res_stats"))
    kb.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))
    return kb


_MENU_TEXT = (
    "🤝 <b>پنل نمایندگی</b>\n\n"
    "از این قسمت می‌تونی حجم نمایندگی بخری، برای مشتری‌هات سرویس بسازی و وضعیت استخرهات رو ببینی."
)


@bot.message_handler(func=lambda m: m.text == "🤝 پنل نمایندگی")
def reseller_menu(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    cc.drop(message)
    # کیبورد منو همیشه دوباره تثبیت میشه تا تو پنل نمایندگی ناپدید نشه
    _ensure_menu_keyboard(message.chat.id, message.from_user.id)
    cc.show(message.chat.id, _MENU_TEXT, reply_markup=_reseller_menu_markup(), parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: call.data == "res_menu")
def res_menu_cb(call):
    bot.answer_callback_query(call.id)
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    _draft.pop(call.message.chat.id, None)
    render(call.message.chat.id, _MENU_TEXT, _reseller_menu_markup(), call.message.message_id)


# ============================================================
# BUY RESELLER VOLUME
# ============================================================

def _show_buy_list(chat_id, message_id):
    plans = db_execute("""
    SELECT reseller_plans.*, panels.name AS panel_name
    FROM reseller_plans
    LEFT JOIN panels ON panels.id = reseller_plans.panel_id
    WHERE reseller_plans.active=1
    ORDER BY reseller_plans.id
    """, fetchall=True) or []

    kb = types.InlineKeyboardMarkup()

    if not plans:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))
        render(chat_id, "📭 فعلاً پلن نمایندگی‌ای تعریف نشده.", kb, message_id)
        return

    for plan in plans:
        kb.add(types.InlineKeyboardButton(f"🤝 {plan['name']}", callback_data=f"resplan:{plan['id']}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))

    render(chat_id, "🤝 <b>خرید حجم نمایندگی</b>\n\nیه پلن انتخاب کن:", kb, message_id)


@bot.callback_query_handler(func=lambda call: call.data == "res_buy")
def res_buy(call):
    bot.answer_callback_query(call.id)
    _show_buy_list(call.message.chat.id, call.message.message_id)


def _plan_tiers(plan_id):
    return db_execute(
        "SELECT * FROM reseller_plan_tiers WHERE plan_id=? ORDER BY sort_order, volume_gb",
        (plan_id,), fetchall=True
    ) or []


def _show_plan(chat_id, message_id, plan_id):
    """False برمی‌گردونه اگه پلن پیدا نشد."""
    plan = db_execute("""
    SELECT reseller_plans.*, panels.name AS panel_name
    FROM reseller_plans
    LEFT JOIN panels ON panels.id = reseller_plans.panel_id
    WHERE reseller_plans.id=? AND reseller_plans.active=1
    """, (plan_id,), fetchone=True)

    if not plan:
        return False

    tiers = _plan_tiers(plan_id)
    has_custom = bool(plan["price_per_gb"] and plan["price_per_gb"] > 0)

    kb = types.InlineKeyboardMarkup()
    for tier in tiers:
        kb.add(types.InlineKeyboardButton(
            f"📦 {_fmt_gb(tier['volume_gb'])}GB — {tier['price']:,} تومان",
            callback_data=f"respaytier:{tier['id']}"
        ))
    if has_custom:
        kb.add(types.InlineKeyboardButton("💬 حجم دلخواه", callback_data=f"rescustomvol:{plan_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_buy"))

    lines = [f"🤝 <b>{plan['name']}</b>\n"]
    if not tiers and not has_custom:
        lines.append("📭 فعلاً هیچ گزینه‌ی خریدی براش تعریف نشده.")
    else:
        if tiers:
            lines.append("یکی از حجم‌های آماده رو انتخاب کن:")
        if has_custom:
            lines.append(
                f"یا «💬 حجم دلخواه» (حداقل {_fmt_gb(plan['custom_min_gb'] or 300)} گیگ، "
                f"هر گیگ {plan['price_per_gb']:,} تومان)"
            )
    lines.append(
        "\n⏳ بدون محدودیت زمانی. با هر خرید بیشتر، حجم به استخر قبلیت اضافه میشه (جمع میشه)."
    )

    render(chat_id, "\n".join(lines), kb, message_id)
    return True


@bot.callback_query_handler(func=lambda call: call.data.startswith("resplan:"))
def resplan_detail(call):
    plan_id = int(call.data.split(":")[1])
    if not _show_plan(call.message.chat.id, call.message.message_id, plan_id):
        bot.answer_callback_query(call.id, "این پلن دیگر موجود نیست.", show_alert=True)
        return
    bot.answer_callback_query(call.id)


def _start_payment(chat_id, message_id, back_cb, volume_gb, price, reseller_plan_id):
    card = get_setting("card_number", "")
    holder = get_setting("card_holder", "")

    if not card:
        cc.show(chat_id, "❌ پرداخت کارت به کارت فعلاً تنظیم نشده.")
        return

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 انصراف", callback_data=back_cb))

    render(
        chat_id,
        f"📦 حجم: <b>{_fmt_gb(volume_gb)} GB</b>\n"
        f"💳 مبلغ <b>{price:,} تومان</b> رو به کارت زیر انتقال بده:\n\n"
        f"<code>{card}</code>\n"
        f"👤 {holder or '---'}\n\n"
        "بعد از انتقال، تصویر رسید رو همینجا بفرست.",
        kb,
        message_id
    )
    bot.register_next_step_handler_by_chat_id(
        chat_id, respay_receipt, reseller_plan_id, volume_gb, price, back_cb
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("respaytier:"))
def respaytier_start(call):
    tier_id = int(call.data.split(":")[1])
    tier = db_execute("SELECT * FROM reseller_plan_tiers WHERE id=?", (tier_id,), fetchone=True)
    if not tier:
        bot.answer_callback_query(call.id, "این گزینه دیگر موجود نیست.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    _start_payment(
        call.message.chat.id, call.message.message_id,
        back_cb=f"resplan:{tier['plan_id']}",
        volume_gb=tier["volume_gb"], price=tier["price"],
        reseller_plan_id=tier["plan_id"]
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("rescustomvol:"))
def rescustomvol_start(call):
    plan_id = int(call.data.split(":")[1])
    plan = db_execute("SELECT * FROM reseller_plans WHERE id=? AND active=1", (plan_id,), fetchone=True)
    if not plan or not plan["price_per_gb"]:
        bot.answer_callback_query(call.id, "این پلن حجم دلخواه نداره.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    min_gb = plan["custom_min_gb"] or 300

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"resplan:{plan_id}"))

    render(
        chat_id,
        f"💬 چند گیگ می‌خوای؟ (فقط عدد، حداقل {_fmt_gb(min_gb)} گیگ)\n\n"
        f"هر گیگ: {plan['price_per_gb']:,} تومان",
        kb, call.message.message_id
    )
    bot.register_next_step_handler_by_chat_id(chat_id, _customvol_amount, plan_id)


def _customvol_amount(message, plan_id):
    chat_id = message.chat.id
    cc.drop(message)

    plan = db_execute("SELECT * FROM reseller_plans WHERE id=? AND active=1", (plan_id,), fetchone=True)
    kb_back = types.InlineKeyboardMarkup()
    kb_back.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"resplan:{plan_id}"))

    if not plan or not plan["price_per_gb"]:
        _edit_screen(chat_id, "❌ این پلن دیگه موجود نیست.", kb_back)
        return

    min_gb = plan["custom_min_gb"] or 300
    text_raw = (message.text or "").strip().replace(",", "")

    try:
        amount = float(text_raw)
        if not math.isfinite(amount):
            amount = -1
    except ValueError:
        amount = -1

    if amount < min_gb:
        _edit_screen(chat_id, f"❌ حداقل {_fmt_gb(min_gb)} گیگ باید باشه. دوباره یه عدد بفرست:", kb_back)
        bot.register_next_step_handler_by_chat_id(chat_id, _customvol_amount, plan_id)
        return

    price = round(amount * plan["price_per_gb"])

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ تایید و پرداخت", callback_data=f"rescustomvol_go:{plan_id}:{amount:g}"),
        types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"resplan:{plan_id}"),
    )
    _edit_screen(
        chat_id,
        f"📦 حجم: <b>{_fmt_gb(amount)} GB</b>\n"
        f"💰 مبلغ: <b>{price:,} تومان</b>\n\n"
        "تایید می‌کنی؟",
        kb
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("rescustomvol_go:"))
def rescustomvol_go(call):
    try:
        _, plan_id, amount = call.data.split(":")
        plan_id = int(plan_id)
        amount = float(amount)
    except ValueError:
        bot.answer_callback_query(call.id, "داده نامعتبر.", show_alert=True)
        return

    plan = db_execute("SELECT * FROM reseller_plans WHERE id=? AND active=1", (plan_id,), fetchone=True)
    if not plan or not plan["price_per_gb"]:
        bot.answer_callback_query(call.id, "این پلن دیگه موجود نیست.", show_alert=True)
        return

    # callback_data از سمت کاربر قابل دست‌کاریه؛ حداقل رو دوباره چک می‌کنیم
    min_gb = plan["custom_min_gb"] or 300
    if not math.isfinite(amount) or amount < min_gb:
        bot.answer_callback_query(call.id, f"حداقل {_fmt_gb(min_gb)} گیگ.", show_alert=True)
        return

    price = round(amount * plan["price_per_gb"])
    bot.answer_callback_query(call.id)
    _start_payment(
        call.message.chat.id, call.message.message_id,
        back_cb=f"resplan:{plan_id}",
        volume_gb=amount, price=price, reseller_plan_id=plan_id
    )


def respay_receipt(message, reseller_plan_id, volume_gb, price, back_cb):
    chat_id = message.chat.id
    cc.drop(message)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 انصراف", callback_data=back_cb))

    if not message.photo:
        _edit_screen(chat_id, "❌ فقط تصویر رسید رو بفرست.", kb)
        bot.register_next_step_handler_by_chat_id(
            chat_id, respay_receipt, reseller_plan_id, volume_gb, price, back_cb
        )
        return

    user_id = internal_user_id(message.from_user.id)
    file_id = message.photo[-1].file_id

    db_execute("""
    INSERT INTO payments
    (user_id, plan_id, amount, method,
     receipt_file_id, receipt_type,
     type, reseller_plan_id, reseller_volume_gb,
     status, created_at, updated_at)
    VALUES (?, NULL, ?, 'manual', ?, 'photo',
            'reseller', ?, ?, 'pending', ?, ?)
    """, (
        user_id, price, file_id, reseller_plan_id, volume_gb, now(), now()
    ))

    ok_kb = types.InlineKeyboardMarkup()
    ok_kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل نمایندگی", callback_data="res_menu"))

    _edit_screen(chat_id, "✅ رسید ثبت شد.\n\n⏳ بعد از تأیید مدیریت، حجم به استخرت اضافه میشه.", ok_kb)


# ============================================================
# تأیید پرداخت (صدا زده میشه از handlers_payment.py بعد از approve)
# ============================================================

def apply_reseller_topup(payment):
    """
    بعد از تأیید ادمین: حجمِ خریداری‌شده به استخر نماینده تو همون پنل
    اضافه میشه (اگه استخری نباشه، ساخته میشه).
    توجه: جلوگیری از تأیید دوباره‌ی یک پرداخت (idempotency) باید تو
    handlers_payment.py انجام بشه (وضعیت payment رو قبل از صدا زدن
    این تابع از pending عوض کن).
    """
    reseller_plan_id = payment["reseller_plan_id"] if "reseller_plan_id" in payment.keys() else None
    if not reseller_plan_id:
        return False, "پلن نمایندگی نامعتبر است"

    rplan = db_execute("SELECT * FROM reseller_plans WHERE id=?", (reseller_plan_id,), fetchone=True)
    if not rplan:
        return False, "پلن نمایندگی پیدا نشد"

    panel_id = rplan["panel_id"]
    if not panel_id:
        return False, "این پلن نمایندگی به هیچ پنلی وصل نیست"

    volume = payment["reseller_volume_gb"] if "reseller_volume_gb" in payment.keys() else None
    if not volume:
        volume = rplan["volume_gb"] or 0
    user_id = payment["user_id"]

    pool = db_execute(
        "SELECT * FROM reseller_panels WHERE user_id=? AND panel_id=?",
        (user_id, panel_id), fetchone=True
    )

    if pool:
        # اتمیک: خوندن و نوشتن جدا نیست
        db_execute("""
        UPDATE reseller_panels
        SET balance = COALESCE(balance, 0) + ?,
            total_purchased = COALESCE(total_purchased, 0) + ?,
            active=1, updated_at=?
        WHERE id=?
        """, (volume, volume, now(), pool["id"]))
    else:
        db_execute("""
        INSERT INTO reseller_panels
        (user_id, reseller_plan_id, panel_id, name, balance, total_purchased, active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (user_id, reseller_plan_id, panel_id, rplan["name"], volume, volume, now(), now()))

    db_execute("UPDATE users SET is_reseller=1 WHERE id=?", (user_id,))

    user = db_execute("SELECT * FROM users WHERE id=?", (user_id,), fetchone=True)
    if user:
        try:
            bot.send_message(
                user["telegram_id"],
                "✅ <b>خرید حجم نمایندگی تأیید شد!</b>\n\n"
                f"➕ {_fmt_gb(volume)} گیگ به استخر «{rplan['name']}» اضافه شد.",
                parse_mode="HTML",
                reply_markup=_home_markup()
            )
        except Exception:
            pass

    return True, "ok"


# ============================================================
# MY POOLS  (پنل‌های من)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "res_pools")
def res_pools(call):
    bot.answer_callback_query(call.id)
    user_id = internal_user_id(call.from_user.id)

    pools = db_execute("""
    SELECT reseller_panels.*, reseller_plans.name AS pool_label
    FROM reseller_panels
    LEFT JOIN reseller_plans ON reseller_plans.id = reseller_panels.reseller_plan_id
    WHERE reseller_panels.user_id=?
    ORDER BY reseller_panels.id DESC
    """, (user_id,), fetchall=True) or []

    kb = types.InlineKeyboardMarkup()

    if not pools:
        kb.add(types.InlineKeyboardButton("🛒 خرید حجم نمایندگی", callback_data="res_buy"))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))
        render(call.message.chat.id, "📭 هنوز هیچ استخر حجمی نداری.", kb, call.message.message_id)
        return

    for pool in pools:
        icon = "🟢" if pool["active"] and (pool["balance"] or 0) > 0 else "🔴"
        kb.add(types.InlineKeyboardButton(
            f"{icon} {_pool_label(pool)} — {_fmt_gb(pool['balance'])}GB",
            callback_data=f"respool:{pool['id']}"
        ))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))

    render(call.message.chat.id, "🖥 <b>پنل‌های من</b>\n\nروی هرکدوم بزن:", kb, call.message.message_id)


def _pool_customer_stats(pool):
    row = db_execute("""
    SELECT COUNT(*) AS total, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active
    FROM services
    WHERE reseller_id=? AND panel_id=?
    """, (pool["user_id"], pool["panel_id"]), fetchone=True)
    total = (row["total"] if row else 0) or 0
    active = (row["active"] if row else 0) or 0
    return active, total


def _render_pool_detail(chat_id, pool_id, message_id=None, online_note=None):
    pool = db_execute("""
    SELECT reseller_panels.*, reseller_plans.name AS pool_label
    FROM reseller_panels
    LEFT JOIN reseller_plans ON reseller_plans.id = reseller_panels.reseller_plan_id
    WHERE reseller_panels.id=?
    """, (pool_id,), fetchone=True)

    if not pool:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_pools"))
        render(chat_id, "❌ این استخر دیگه وجود نداره.", kb, message_id)
        return

    active_customers, total_customers = _pool_customer_stats(pool)

    balance = pool["balance"] or 0
    total_purchased = pool["total_purchased"] or 0
    used = max(0, total_purchased - balance)

    is_on = pool["active"] and balance > 0
    status_line = "🟢 فعال" if is_on else "🔴 تموم‌شده / غیرفعال"

    kb = types.InlineKeyboardMarkup()
    if balance > 0:
        kb.add(types.InlineKeyboardButton("➕ ساخت کانفیگ جدید", callback_data=f"resnew:{pool_id}"))

    kb.row(
        types.InlineKeyboardButton("👥 مشتری‌های این پنل", callback_data=f"respoolcust:{pool_id}"),
        types.InlineKeyboardButton("📶 آنلاین الان", callback_data=f"respoolonline:{pool_id}"),
    )
    kb.row(
        types.InlineKeyboardButton("🔄 بروزرسانی مصرف", callback_data=f"respoolrefresh:{pool_id}"),
        types.InlineKeyboardButton("📊 گراف مصرف روزانه", callback_data=f"respoolchart:{pool_id}"),
    )
    kb.row(
        types.InlineKeyboardButton("⏸ خاموش کردن همه", callback_data=f"respoolpause:{pool_id}"),
        types.InlineKeyboardButton("▶️ روشن کردن همه", callback_data=f"respoolresume:{pool_id}"),
    )
    kb.add(types.InlineKeyboardButton("🔋 تمدید / افزایش حجم", callback_data=f"respooltopup:{pool_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_pools"))

    text = (
        f"🖥 <b>{_pool_label(pool)}</b>\n\n"
        f"وضعیت: {status_line}\n\n"
        f"📊 <b>مصرف از استخر</b>\n"
        f"{_progress_bar(used, total_purchased)}\n"
        f"مصرف‌شده: {_fmt_gb(used)} GB از {_fmt_gb(total_purchased)} GB\n"
        f"باقیمونده: <b>{_fmt_gb(balance)} GB</b>\n\n"
        f"👥 مشتری‌ها: {active_customers} فعال از {total_customers} کل"
    )
    if online_note:
        text += f"\n\n{online_note}"

    render(chat_id, text, kb, message_id)


def _report_error(call, where, exc):
    """خطا رو تو لاگ سرور چاپ می‌کنه و متنش رو تو چت نشون میده تا دیباگ راحت باشه."""
    traceback.print_exc()
    try:
        bot.send_message(
            call.message.chat.id,
            f"⚠️ خطا ({where}):\n<code>{type(exc).__name__}: {exc}</code>",
            parse_mode="HTML"
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("respool:"))
def respool_detail(call):
    try:
        pool_id = int(call.data.split(":")[1])
        user_id = internal_user_id(call.from_user.id)
        pool = _get_pool(pool_id, user_id)

        if not pool:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        _render_pool_detail(call.message.chat.id, pool_id, call.message.message_id)
    except Exception as e:
        _report_error(call, "باز کردن پنل", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respoolrefresh:"))
def respool_refresh(call):
    try:
        pool_id = int(call.data.split(":")[1])
        user_id = internal_user_id(call.from_user.id)
        pool = _get_pool(pool_id, user_id)

        if not pool:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        bot.answer_callback_query(call.id, "⏳ در حال بروزرسانی مصرف...")
        try:
            reseller_billing.refresh_pool(pool_id)
        except Exception:
            traceback.print_exc()
        _render_pool_detail(call.message.chat.id, pool_id, call.message.message_id)
    except Exception as e:
        _report_error(call, "بروزرسانی", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respoolonline:"))
def respool_online(call):
    """شمارشِ تخمینیِ «آنلاین الان»؛ اگه مشتری زیاد باشه ممکنه چند ثانیه طول بکشه."""
    try:
        pool_id = int(call.data.split(":")[1])
        user_id = internal_user_id(call.from_user.id)
        pool = _get_pool(pool_id, user_id)

        if not pool:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        bot.answer_callback_query(call.id, "⏳ در حال چک کردن وضعیت آنلاین...")

        panel = db_execute("SELECT * FROM panels WHERE id=?", (pool["panel_id"],), fetchone=True)
        services = db_execute(
            "SELECT * FROM services WHERE reseller_id=? AND panel_id=? AND status='active'",
            (pool["user_id"], pool["panel_id"]), fetchall=True
        ) or []

        online_count = 0
        checked = 0
        if panel:
            for svc in services:
                if not svc["username"]:
                    continue
                try:
                    usage = pasarguard_get_user_usage(panel, svc["username"])
                except Exception:
                    continue
                checked += 1
                if usage.get("success") and usage.get("online"):
                    online_count += 1

        note = f"📶 آنلاین الان (تخمینی): <b>{online_count}</b> از {checked} مشتری فعال"
        _render_pool_detail(call.message.chat.id, pool_id, call.message.message_id, online_note=note)
    except Exception as e:
        _report_error(call, "آنلاین", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respoolpause:"))
def respool_pause_all(call):
    try:
        pool_id = int(call.data.split(":")[1])
        user_id = internal_user_id(call.from_user.id)
        pool = _get_pool(pool_id, user_id)

        if not pool:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        panel = db_execute("SELECT * FROM panels WHERE id=?", (pool["panel_id"],), fetchone=True)
        services = db_execute(
            "SELECT * FROM services WHERE reseller_id=? AND panel_id=? AND status='active'",
            (pool["user_id"], pool["panel_id"]), fetchall=True
        ) or []

        if not services:
            bot.answer_callback_query(call.id, "سرویس فعالی نیست.", show_alert=True)
            return

        bot.answer_callback_query(call.id, f"⏳ در حال خاموش کردن {len(services)} سرویس...")

        done = 0
        failed = 0
        for svc in services:
            if panel and svc["username"]:
                try:
                    result = pasarguard_set_status(panel, svc["username"], enabled=False)
                    if not result.get("success"):
                        failed += 1
                        continue
                except Exception:
                    failed += 1
                    continue
            db_execute("UPDATE services SET status='disabled', updated_at=? WHERE id=?", (now(), svc["id"]))
            done += 1

        note = f"⏸ {done} سرویس خاموش شد."
        if failed:
            note += f"\n⚠️ {failed} سرویس خاموش نشد (خطای پنل)."
        _render_pool_detail(call.message.chat.id, pool_id, call.message.message_id, online_note=note)
    except Exception as e:
        _report_error(call, "خاموش کردن همه", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respoolresume:"))
def respool_resume_all(call):
    try:
        pool_id = int(call.data.split(":")[1])
        user_id = internal_user_id(call.from_user.id)
        pool = _get_pool(pool_id, user_id)

        if not pool:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        if (pool["balance"] or 0) <= 0:
            bot.answer_callback_query(call.id, "❌ این استخر موجودی نداره، اول شارژش کن.", show_alert=True)
            return

        panel = db_execute("SELECT * FROM panels WHERE id=?", (pool["panel_id"],), fetchone=True)
        services = db_execute(
            "SELECT * FROM services WHERE reseller_id=? AND panel_id=? AND status!='active'",
            (pool["user_id"], pool["panel_id"]), fetchall=True
        ) or []

        if not services:
            bot.answer_callback_query(call.id, "سرویس خاموشی نیست.", show_alert=True)
            return

        bot.answer_callback_query(call.id, f"⏳ در حال روشن کردن {len(services)} سرویس...")

        done = 0
        failed = 0
        for svc in services:
            if panel and svc["username"]:
                try:
                    result = pasarguard_set_status(panel, svc["username"], enabled=True)
                    if not result.get("success"):
                        failed += 1
                        continue
                except Exception:
                    failed += 1
                    continue
            db_execute("UPDATE services SET status='active', updated_at=? WHERE id=?", (now(), svc["id"]))
            done += 1

        db_execute("UPDATE reseller_panels SET active=1 WHERE id=?", (pool["id"],))
        note = f"▶️ {done} سرویس روشن شد."
        if failed:
            note += f"\n⚠️ {failed} سرویس روشن نشد (خطای پنل)."
        _render_pool_detail(call.message.chat.id, pool_id, call.message.message_id, online_note=note)
    except Exception as e:
        _report_error(call, "روشن کردن همه", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respooltopup:"))
def respool_topup(call):
    try:
        pool_id = int(call.data.split(":")[1])
        user_id = internal_user_id(call.from_user.id)
        pool = _get_pool(pool_id, user_id)

        if not pool:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        chat_id, message_id = call.message.chat.id, call.message.message_id

        if pool["reseller_plan_id"]:
            if _show_plan(chat_id, message_id, pool["reseller_plan_id"]):
                return

        # پلن اصلی دیگه فعال نیست یا مشخص نیست → لیست کلی خرید
        _show_buy_list(chat_id, message_id)
    except Exception as e:
        _report_error(call, "افزایش حجم", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respoolchart:"))
def respool_chart(call):
    try:
        pool_id = int(call.data.split(":")[1])
        user_id = internal_user_id(call.from_user.id)
        pool = _get_pool(pool_id, user_id)

        if not pool:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        bot.answer_callback_query(call.id)

        rows = db_execute("""
        SELECT substr(created_at, 1, 10) AS day, SUM(amount_gb) AS total
        FROM reseller_usage_log
        WHERE reseller_panel_id=?
        GROUP BY day
        ORDER BY day DESC
        LIMIT 7
        """, (pool_id,), fetchall=True) or []
        rows = list(reversed(rows))

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))

        if not rows:
            render(call.message.chat.id, "📊 هنوز مصرفی ثبت نشده که نموداری نشونت بدم.", kb, call.message.message_id)
            return

        max_val = max((r["total"] or 0) for r in rows) or 1
        bar_width = 12
        lines = [f"📊 <b>مصرف {len(rows)} روز اخیر — {_pool_label(pool)}</b>\n"]
        for r in rows:
            val = r["total"] or 0
            filled = max(1, round((val / max_val) * bar_width)) if val > 0 else 0
            bar = "🟩" * filled + "⬜️" * (bar_width - filled)
            lines.append(f"<code>{r['day']}</code>  {bar}  {_fmt_gb(val)}GB")

        total_week = sum((r["total"] or 0) for r in rows)
        lines.append(f"\nجمع این بازه: <b>{_fmt_gb(total_week)} GB</b>")

        render(call.message.chat.id, "\n".join(lines), kb, call.message.message_id)
    except Exception as e:
        _report_error(call, "گراف مصرف", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("respoolcust:"))
def respool_customers(call):
    try:
        pool_id = int(call.data.split(":")[1])
        user_id = internal_user_id(call.from_user.id)
        pool = _get_pool(pool_id, user_id)

        if not pool:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        services = db_execute("""
        SELECT * FROM services
        WHERE reseller_id=? AND panel_id=?
        ORDER BY id DESC
        LIMIT 50
        """, (pool["user_id"], pool["panel_id"]), fetchall=True) or []

        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()

        if not services:
            kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))
            render(call.message.chat.id, "📭 هنوز برای این پنل مشتری‌ای نساختی.", kb, call.message.message_id)
            return

        for svc in services:
            icon = "🟢" if svc["status"] == "active" else "🔴"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {svc['username']}",
                callback_data=f"rescust:{svc['id']}:respoolcust:{pool_id}"
            ))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))

        render(
            call.message.chat.id,
            f"👥 <b>مشتری‌های {_pool_label(pool)}</b>\n\nروی هرکدوم بزن:",
            kb, call.message.message_id
        )
    except Exception as e:
        _report_error(call, "لیست مشتری‌ها", e)


# ============================================================
# CREATE CUSTOMER SERVICE  (ساخت کانفیگ)
# نام → حجم → مدت → دستگاه → تأیید → ساخت + (QR + مشخصات + لینک) تو یک پیام
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("resnew:"))
def resnew_start(call):
    pool_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)
    pool = _get_pool(pool_id, user_id)

    if not pool or (pool["balance"] or 0) <= 0:
        bot.answer_callback_query(call.id, "این استخر موجودی نداره.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    _draft.pop(chat_id, None)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))

    render(
        chat_id,
        "🏷 یه نام دلخواه برای این مشتری بفرست (فقط حروف/عدد انگلیسی، بدون فاصله):\n\n"
        "مثال: <code>ali</code>",
        kb,
        call.message.message_id
    )
    bot.register_next_step_handler_by_chat_id(chat_id, resnew_name, pool_id)


def _sanitize_customer_name(owner_id, raw):
    return f"res{owner_id}_{raw}"


def resnew_name(message, pool_id):
    chat_id = message.chat.id
    cc.drop(message)
    user_id = internal_user_id(message.from_user.id)
    pool = _get_pool(pool_id, user_id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))

    def _reask(text):
        _edit_screen(chat_id, text, kb)
        bot.register_next_step_handler_by_chat_id(chat_id, resnew_name, pool_id)

    if not pool or (pool["balance"] or 0) <= 0:
        cc.show(chat_id, "❌ این استخر دیگه موجودی نداره.", reply_markup=_home_markup())
        return

    raw = (message.text or "").strip().lower()
    if not USERNAME_PATTERN.match(raw):
        _reask("❌ نام نامعتبره. فقط حروف/عدد انگلیسی و بدون فاصله (۲ تا ۲۰ کاراکتر). دوباره بفرست:")
        return

    final_username = _sanitize_customer_name(user_id, raw)
    exists = db_execute("SELECT id FROM services WHERE username=?", (final_username,), fetchone=True)
    if exists:
        _reask(f"❌ نام «{raw}» قبلاً استفاده شده. یه نام دیگه بفرست:")
        return

    _draft[chat_id] = {"pool_id": pool_id, "raw": raw}

    _edit_screen(
        chat_id,
        "📊 این مشتری چند گیگ داشته باشه؟ (فقط عدد)\n\n"
        f"باقیمونده‌ی استخرت: {_fmt_gb(pool['balance'])} گیگ",
        kb
    )
    bot.register_next_step_handler_by_chat_id(chat_id, resnew_volume, pool_id)


def resnew_volume(message, pool_id):
    chat_id = message.chat.id
    cc.drop(message)
    draft = _draft.get(chat_id)
    if not draft:
        return

    user_id = internal_user_id(message.from_user.id)
    pool = _get_pool(pool_id, user_id)
    balance = (pool["balance"] or 0) if pool else 0

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))

    def _reask(text):
        _edit_screen(chat_id, text, kb)
        bot.register_next_step_handler_by_chat_id(chat_id, resnew_volume, pool_id)

    text = (message.text or "").strip().replace(",", ".")
    try:
        volume = float(text)
        if not math.isfinite(volume) or volume <= 0:
            raise ValueError
    except ValueError:
        _reask("❌ فقط عدد بزرگ‌تر از صفر بفرست:")
        return

    if volume > balance:
        _reask(f"❌ حجم مشتری نمی‌تونه از باقیمونده‌ی استخر ({_fmt_gb(balance)} گیگ) بیشتر باشه. یه عدد کمتر بفرست:")
        return

    draft["volume"] = volume
    _edit_screen(chat_id, "⏳ چند روز اعتبار داشته باشه؟ (فقط عدد)", kb)
    bot.register_next_step_handler_by_chat_id(chat_id, resnew_duration, pool_id)


def resnew_duration(message, pool_id):
    chat_id = message.chat.id
    cc.drop(message)
    draft = _draft.get(chat_id)
    if not draft:
        return

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))

    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0 or int(text) > 3650:
        _edit_screen(chat_id, "❌ فقط عدد روز (بین ۱ تا ۳۶۵۰) بفرست:", kb)
        bot.register_next_step_handler_by_chat_id(chat_id, resnew_duration, pool_id)
        return

    draft["duration"] = int(text)
    _edit_screen(chat_id, "📱 چند تا دستگاه همزمان مجاز باشه؟ (فقط عدد)", kb)
    bot.register_next_step_handler_by_chat_id(chat_id, resnew_devices, pool_id)


def resnew_devices(message, pool_id):
    chat_id = message.chat.id
    cc.drop(message)
    draft = _draft.get(chat_id)
    if not draft:
        return

    user_id = internal_user_id(message.from_user.id)
    pool = _get_pool(pool_id, user_id)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"respool:{pool_id}"))

    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0 or int(text) > 100:
        _edit_screen(chat_id, "❌ فقط عدد بزرگ‌تر از صفر (حداکثر ۱۰۰) بفرست:", kb)
        bot.register_next_step_handler_by_chat_id(chat_id, resnew_devices, pool_id)
        return

    draft["devices"] = int(text)

    if not pool or (pool["balance"] or 0) <= 0:
        _draft.pop(chat_id, None)
        cc.show(chat_id, "❌ این استخر دیگه موجودی نداره.", reply_markup=_home_markup())
        return

    final_username = _sanitize_customer_name(user_id, draft["raw"])
    kb2 = types.InlineKeyboardMarkup()
    kb2.row(
        types.InlineKeyboardButton("✅ بساز", callback_data="resmk_confirm"),
        types.InlineKeyboardButton("❌ انصراف", callback_data=f"respool:{pool_id}"),
    )

    _edit_screen(
        chat_id,
        "🔎 <b>مشخصات سرویس مشتری</b>\n\n"
        f"🏷 استخر: {_pool_label(pool)}\n"
        f"👤 نام کاربری: <code>{final_username}</code>\n"
        f"📊 حجم: {_fmt_gb(draft['volume'])} گیگ\n"
        f"⏳ مدت: {draft['duration']} روز\n"
        f"📱 دستگاه: {draft['devices']}\n\n"
        "مصرف واقعی این مشتری از استخرت کم میشه. تایید می‌کنی؟",
        kb2
    )


@bot.callback_query_handler(func=lambda call: call.data == "resmk_confirm")
def resnew_confirm(call):
    chat_id = call.message.chat.id

    # pop اتمیک: دابل‌کلیک فقط یک بار از این‌جا رد میشه
    draft = _draft.pop(chat_id, None)
    if not draft:
        bot.answer_callback_query(call.id, "⛔ این مرحله منقضی شده یا قبلاً ثبت شده.", show_alert=True)
        return

    try:
        pool_id = draft["pool_id"]
        user_id = internal_user_id(call.from_user.id)
        pool = _get_pool(pool_id, user_id)

        if not pool or (pool["balance"] or 0) <= 0:
            bot.answer_callback_query(call.id, "این استخر دیگه موجودی نداره.", show_alert=True)
            return

        if draft["volume"] > (pool["balance"] or 0):
            bot.answer_callback_query(call.id, "حجم از موجودی استخر بیشتره.", show_alert=True)
            return

        panel = db_execute("SELECT * FROM panels WHERE id=?", (pool["panel_id"],), fetchone=True)
        if not panel:
            bot.answer_callback_query(call.id, "پنل این استخر پیدا نشد.", show_alert=True)
            return

        final_username = _sanitize_customer_name(user_id, draft["raw"])
        if db_execute("SELECT id FROM services WHERE username=?", (final_username,), fetchone=True):
            bot.answer_callback_query(call.id, "این نام همین الان گرفته شد، از اول با یه نام دیگه امتحان کن.", show_alert=True)
            return

        bot.answer_callback_query(call.id, "⏳ در حال ساخت سرویس...")
        try:
            bot.edit_message_text("⏳ در حال ساخت سرویس...", chat_id, call.message.message_id)
        except Exception:
            pass

        fake_plan = {
            "name": f"Reseller:{pool_id}",
            "price": 0,
            "volume": draft["volume"],
            "duration": draft["duration"],
            "devices": draft["devices"],
        }
        owner = {"telegram_id": f"reseller{user_id}"}

        result = pasarguard_create_service(
            panel=panel,
            telegram_user=owner,
            plan=fake_plan,
            desired_username=final_username
        )

        kb_back = types.InlineKeyboardMarkup()
        kb_back.add(types.InlineKeyboardButton("🔙 بازگشت به استخر", callback_data=f"respool:{pool_id}"))

        if not result.get("success"):
            render(
                chat_id,
                f"❌ ساخت سرویس ناموفق بود.\n\n<code>{result.get('error', 'نامشخص')}</code>",
                kb_back, call.message.message_id
            )
            return

        expires_at = (datetime.utcnow() + timedelta(days=draft["duration"])).strftime("%Y-%m-%d %H:%M:%S")
        link = result.get("config", "")
        created_username = result.get("username", final_username)

        db_execute("""
        INSERT INTO services
        (user_id, plan_id, panel_id, username, config, qr,
         volume, used_volume, duration, devices,
         expires_at, status, reseller_id, is_unlimited,
         created_at, updated_at)
        VALUES (?, NULL, ?, ?, ?, '', ?, 0, ?, ?, ?, 'active', ?, 0, ?, ?)
        """, (
            user_id, pool["panel_id"], created_username,
            link, draft["volume"], draft["duration"], draft["devices"],
            expires_at, user_id, now(), now()
        ))

        # صفحه‌ی «در حال ساخت» پاک میشه و تحویل سرویس تو «یک پیام» میاد:
        # QR کد بالا، و زیرش مشخصات سرویس + لینک اشتراک.
        # این پیام عمداً ثبت/پاک نمیشه تا نماینده لینک رو از دست نده.
        cc.drop_screen(chat_id)
        cc.safe_delete(chat_id, call.message.message_id)

        caption = (
            "🎉 <b>سرویس مشتری ساخته شد!</b>\n\n"
            f"👤 نام کاربری: <code>{_esc(str(created_username))}</code>\n"
            f"📊 حجم: {_fmt_gb(draft['volume'])} گیگ\n"
            f"⏳ مدت: {draft['duration']} روز\n"
            f"📱 دستگاه: {draft['devices']}\n\n"
            "🔗 لینک اشتراک (این رو به مشتریت بده):\n"
            f"<code>{_esc(link) if link else '---'}</code>"
        )
        kb_done = types.InlineKeyboardMarkup()
        kb_done.add(types.InlineKeyboardButton("🔙 بازگشت به استخر", callback_data=f"respool:{pool_id}"))
        kb_done.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_home"))

        _send_qr_message(chat_id, link, caption, kb_done)
    except Exception as e:
        _report_error(call, "ساخت سرویس", e)


# ============================================================
# MY CUSTOMERS
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "res_customers")
def res_customers(call):
    bot.answer_callback_query(call.id)
    user_id = internal_user_id(call.from_user.id)

    services = db_execute("""
    SELECT * FROM services
    WHERE reseller_id=?
    ORDER BY id DESC
    LIMIT 50
    """, (user_id,), fetchall=True) or []

    kb = types.InlineKeyboardMarkup()

    if not services:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))
        render(call.message.chat.id, "📭 هنوز برای هیچ مشتری‌ای سرویس نساختی.", kb, call.message.message_id)
        return

    for svc in services:
        icon = "🟢" if svc["status"] == "active" else "🔴"
        kb.add(types.InlineKeyboardButton(f"{icon} {svc['username']}", callback_data=f"rescust:{svc['id']}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))

    render(call.message.chat.id, "👥 <b>کاربران من</b>\n\nروی هرکدوم بزن:", kb, call.message.message_id)


def _days_left(expires_at):
    if not expires_at:
        return None
    try:
        expire_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
        return (expire_dt - datetime.utcnow()).days
    except Exception:
        return None


def _render_customer_detail(chat_id, service_id, owner_user_id, message_id=None, back_cb="res_customers"):
    svc = db_execute(
        "SELECT * FROM services WHERE id=? AND reseller_id=?",
        (service_id, owner_user_id), fetchone=True
    )
    if not svc:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb))
        render(chat_id, "❌ این سرویس دیگه وجود نداره.", kb, message_id)
        return

    status_label = "🟢 فعال" if svc["status"] == "active" else "🔴 غیرفعال"

    used = svc["used_volume"] or 0
    total = svc["volume"] or 0
    remaining = max(0, total - used)

    days_left = _days_left(svc["expires_at"])
    if days_left is None:
        days_text = "نامشخص"
    elif days_left < 0:
        days_text = "منقضی شده ❗️"
    else:
        days_text = f"{days_left} روز"

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🔄 بروزرسانی مصرف", callback_data=f"rescustrefresh:{service_id}:{back_cb}"),
        types.InlineKeyboardButton("📱 QR کد", callback_data=f"resqr:{service_id}"),
    )
    if svc["status"] == "active":
        kb.add(types.InlineKeyboardButton("⏸ غیرفعال کردن دستی", callback_data=f"respause:{service_id}:{back_cb}"))
    else:
        kb.add(types.InlineKeyboardButton("▶️ فعال کردن دوباره", callback_data=f"resresume:{service_id}:{back_cb}"))
    kb.add(types.InlineKeyboardButton("🗑 حذف سرویس", callback_data=f"resdel_ask:{service_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data=back_cb))

    text = (
        f"👤 <b>{svc['username']}</b>\n\n"
        f"وضعیت: {status_label}\n"
        f"⏳ زمان باقی‌مانده: {days_text}\n"
        f"📱 دستگاه مجاز: {svc['devices']}\n\n"
        f"📊 <b>حجم مصرفی</b>\n"
        f"{_progress_bar(used, total)}\n"
        f"مصرف‌شده: {_fmt_gb(used)} GB از {_fmt_gb(total)} GB\n"
        f"باقیمونده: {_fmt_gb(remaining)} GB\n\n"
        f"🔗 لینک اشتراک:\n<code>{svc['config'] or '---'}</code>"
    )
    render(chat_id, text, kb, message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("rescust:"))
def rescust_detail(call):
    try:
        parts = call.data.split(":", 2)
        service_id = int(parts[1])
        back_cb = parts[2] if len(parts) > 2 else "res_customers"
        user_id = internal_user_id(call.from_user.id)
        bot.answer_callback_query(call.id)
        _render_customer_detail(call.message.chat.id, service_id, user_id, call.message.message_id, back_cb)
    except Exception as e:
        _report_error(call, "جزئیات مشتری", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("resqr:"))
def res_qr(call):
    service_id = int(call.data.split(":")[1])
    user_id = internal_user_id(call.from_user.id)
    svc = db_execute(
        "SELECT * FROM services WHERE id=? AND reseller_id=?",
        (service_id, user_id), fetchone=True
    )
    if not svc or not svc["config"]:
        bot.answer_callback_query(call.id, "لینکی برای این سرویس ثبت نشده.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    _send_qr(call.message.chat.id, svc["config"], svc["username"])


@bot.callback_query_handler(func=lambda call: call.data.startswith("rescustrefresh:"))
def rescust_refresh(call):
    try:
        _, service_id, back_cb = call.data.split(":", 2)
        service_id = int(service_id)
        user_id = internal_user_id(call.from_user.id)

        svc = db_execute(
            "SELECT id FROM services WHERE id=? AND reseller_id=?",
            (service_id, user_id), fetchone=True
        )
        if not svc:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        bot.answer_callback_query(call.id, "⏳ در حال بروزرسانی...")
        try:
            reseller_billing.refresh_service(service_id)
        except Exception:
            traceback.print_exc()
        _render_customer_detail(call.message.chat.id, service_id, user_id, call.message.message_id, back_cb)
    except Exception as e:
        _report_error(call, "بروزرسانی مشتری", e)


def _svc_panel(svc):
    if not svc["panel_id"]:
        return None
    return db_execute("SELECT * FROM panels WHERE id=?", (svc["panel_id"],), fetchone=True)


def _split_cb(data):
    """callback به شکل  action:service_id[:back_cb]"""
    parts = data.split(":", 2)
    service_id = int(parts[1])
    back_cb = parts[2] if len(parts) > 2 else "res_customers"
    return service_id, back_cb


@bot.callback_query_handler(func=lambda call: call.data.startswith("respause:"))
def respause(call):
    try:
        service_id, back_cb = _split_cb(call.data)
        user_id = internal_user_id(call.from_user.id)
        svc = db_execute("SELECT * FROM services WHERE id=? AND reseller_id=?", (service_id, user_id), fetchone=True)
        if not svc:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        panel = _svc_panel(svc)
        if panel and svc["username"]:
            result = pasarguard_set_status(panel, svc["username"], enabled=False)
            if not result.get("success"):
                bot.answer_callback_query(call.id, f"خطای پنل: {result.get('error')}", show_alert=True)
                return

        db_execute("UPDATE services SET status='disabled', updated_at=? WHERE id=?", (now(), service_id))
        bot.answer_callback_query(call.id, "⏸ غیرفعال شد.")
        _render_customer_detail(call.message.chat.id, service_id, user_id, call.message.message_id, back_cb)
    except Exception as e:
        _report_error(call, "غیرفعال کردن", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("resresume:"))
def resresume(call):
    try:
        service_id, back_cb = _split_cb(call.data)
        user_id = internal_user_id(call.from_user.id)
        svc = db_execute("SELECT * FROM services WHERE id=? AND reseller_id=?", (service_id, user_id), fetchone=True)
        if not svc:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        pool = db_execute(
            "SELECT * FROM reseller_panels WHERE user_id=? AND panel_id=?",
            (user_id, svc["panel_id"]), fetchone=True
        )
        if not pool or (pool["balance"] or 0) <= 0:
            bot.answer_callback_query(call.id, "❌ استخر این پنل موجودی نداره، اول شارژ کن.", show_alert=True)
            return

        panel = _svc_panel(svc)
        if panel and svc["username"]:
            result = pasarguard_set_status(panel, svc["username"], enabled=True)
            if not result.get("success"):
                bot.answer_callback_query(call.id, f"خطا: {result.get('error')}", show_alert=True)
                return

        db_execute("UPDATE services SET status='active', updated_at=? WHERE id=?", (now(), service_id))
        db_execute("UPDATE reseller_panels SET active=1 WHERE id=?", (pool["id"],))
        bot.answer_callback_query(call.id, "▶️ دوباره فعال شد.")
        _render_customer_detail(call.message.chat.id, service_id, user_id, call.message.message_id, back_cb)
    except Exception as e:
        _report_error(call, "فعال کردن", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("resdel_ask:"))
def resdel_ask(call):
    service_id = int(call.data.split(":")[1])
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"resdel_go:{service_id}"),
        types.InlineKeyboardButton("❌ انصراف", callback_data=f"rescust:{service_id}"),
    )
    bot.answer_callback_query(call.id)
    render(
        call.message.chat.id,
        "⚠️ مطمئنی می‌خوای این سرویس رو حذف کنی؟ لینک اشتراکش از کار میفته.",
        kb, call.message.message_id
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("resdel_go:"))
def resdel_go(call):
    try:
        service_id = int(call.data.split(":")[1])
        user_id = internal_user_id(call.from_user.id)
        svc = db_execute("SELECT * FROM services WHERE id=? AND reseller_id=?", (service_id, user_id), fetchone=True)
        if not svc:
            bot.answer_callback_query(call.id, "پیدا نشد.", show_alert=True)
            return

        kb = types.InlineKeyboardMarkup()
        panel = _svc_panel(svc)
        if panel and svc["username"]:
            result = pasarguard_delete_service(panel, svc["username"])
            if not result.get("success"):
                # سرویس از دیتابیس پاک نمیشه تا یتیم تو پنل نمونه
                bot.answer_callback_query(call.id, "خطا", show_alert=False)
                kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"rescust:{service_id}"))
                render(
                    call.message.chat.id,
                    f"❌ حذف از پنل انجام نشد، سرویس دست‌نخورده موند.\n\n<code>{result.get('error')}</code>",
                    kb, call.message.message_id
                )
                return

        db_execute("DELETE FROM services WHERE id=?", (service_id,))
        bot.answer_callback_query(call.id, "🗑 حذف شد.")

        kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="res_customers"))
        render(call.message.chat.id, "✅ سرویس حذف شد.", kb, call.message.message_id)
    except Exception as e:
        _report_error(call, "حذف سرویس", e)


# ============================================================
# STATS
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "res_stats")
def res_stats(call):
    bot.answer_callback_query(call.id)
    user_id = internal_user_id(call.from_user.id)

    pools = db_execute("SELECT * FROM reseller_panels WHERE user_id=?", (user_id,), fetchall=True) or []
    total_remaining = sum((p["balance"] or 0) for p in pools)
    total_purchased = sum((p["total_purchased"] or 0) for p in pools)

    customers_count = db_execute(
        "SELECT COUNT(*) c FROM services WHERE reseller_id=?",
        (user_id,), fetchone=True
    )["c"]
    active_count = db_execute(
        "SELECT COUNT(*) c FROM services WHERE reseller_id=? AND status='active'",
        (user_id,), fetchone=True
    )["c"]

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="res_menu"))

    render(
        call.message.chat.id,
        "📈 <b>آمار نمایندگی من</b>\n\n"
        f"📦 مجموع حجم خریداری‌شده: {_fmt_gb(total_purchased)} گیگ\n"
        f"📊 مجموع باقیمونده: {_fmt_gb(total_remaining)} گیگ\n"
        f"👥 تعداد مشتری‌ها: {customers_count}\n"
        f"🟢 مشتری‌های فعال: {active_count}",
        kb,
        call.message.message_id
    )
