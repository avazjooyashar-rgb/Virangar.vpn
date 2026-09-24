# ============================================================
# pasarguard_api.py
# اتصال واقعی به پنل PasarGuard با استفاده از SDK رسمی
# پکیج پایتون: pip install pasarguard   (https://pypi.org/project/pasarguard/)
# ============================================================
import re
import time
import asyncio
from datetime import datetime
from pasarguard import PasarguardAPI, Tools, UserCreate, UserModify, UserStatus

VERIFY_SSL = True
REQUEST_TIMEOUT = 20.0


def _normalize_url(url):
    url = (url or "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _panel_credentials_ok(panel):
    return bool(
        (panel.get("url") or "").strip()
        and (panel.get("username") or "").strip()
        and (panel.get("password") or "").strip()
    )


def _sanitize_username(raw):
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", raw or "")
    cleaned = cleaned.strip("_")
    return cleaned or None


def _to_timestamp(value):
    """
    فیلد expire در نسخه‌های مختلف SDK پاسارگارد گاهی datetime و گاهی
    عدد timestamp برمی‌گردد. این تابع هر دو حالت را به int timestamp
    تبدیل می‌کند تا مقایسه و محاسبات ریاضی روی آن خطا ندهد.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    return None


# ============================================================
# ASYNC CORE
# ============================================================
async def _test_panel_async(panel):
    base_url = _normalize_url(panel["url"])
    async with PasarguardAPI(
        base_url=base_url,
        verify=VERIFY_SSL,
        timeout=REQUEST_TIMEOUT,
    ) as api:
        token = await api.get_token(
            username=panel["username"],
            password=panel["password"],
        )
        admin = await api.get_current_admin(token=token.access_token)
        return {
            "success": True,
            "error": "",
            "is_sudo": bool(getattr(admin, "is_sudo", False)),
            "admin_username": getattr(admin, "username", ""),
        }


async def _create_service_async(panel, telegram_user, plan, desired_username=None):
    base_url = _normalize_url(panel["url"])
    async with PasarguardAPI(
        base_url=base_url,
        verify=VERIFY_SSL,
        timeout=REQUEST_TIMEOUT,
    ) as api:
        token = await api.get_token(
            username=panel["username"],
            password=panel["password"],
        )

        username = _sanitize_username(desired_username)
        if not username:
            username = Tools.random_username(
                prefix=f"tg{telegram_user['telegram_id']}"
            )

        user_create = UserCreate(
            username=username,
            data_limit=Tools.gb(float(plan["volume"])),
            expire=Tools.days(int(plan["duration"])),
            status=UserStatus.ACTIVE,
            note=(
                f"VirangarVPN | tg:{telegram_user['telegram_id']} | "
                f"plan:{plan.get('name', '---')}"
            ),
        )
        user = await api.create_user_in_all_groups(
            user_create,
            token=token.access_token,
        )
        return {
            "success": True,
            "error": "",
            "username": user.username,
            "config": getattr(user, "subscription_url", "") or "",
            "qr": "",
        }


async def _get_user_usage_async(panel, username):
    base_url = _normalize_url(panel["url"])
    async with PasarguardAPI(
        base_url=base_url,
        verify=VERIFY_SSL,
        timeout=REQUEST_TIMEOUT,
    ) as api:
        token = await api.get_token(
            username=panel["username"],
            password=panel["password"],
        )
        user = await api.get_user_by_username(
            username=username,
            token=token.access_token,
        )
        used_bytes = getattr(user, "used_traffic", 0) or 0
        data_limit_bytes = getattr(user, "data_limit", 0) or 0
        return {
            "success": True,
            "error": "",
            "used_gb": used_bytes / (1024 ** 3),
            "data_limit_gb": data_limit_bytes / (1024 ** 3) if data_limit_bytes else 0,
            "status": str(getattr(user, "status", "")),
        }


async def _apply_renewal_async(panel, username, add_volume_gb, add_days):
    """
    تمدید روی خود پنل: فقط سقف حجم (data_limit) و تاریخ انقضا بالا
    برده می‌شود. مصرف قبلی کاربر عمداً صفر نمی‌شود، چون هدف این است که:
        باقیمانده‌ی جدید = باقیمانده‌ی قبلی + حجم پلن تمدید
    مثال: پلن ۵ گیگ/۳۰ روز، کاربر ۲ گیگ مصرف کرده (۳ گیگ باقیمانده).
    بعد از تمدید باید ۸ گیگ باقیمانده داشته باشد (۳ + ۵)، نه ۱۰ گیگ تازه.
    چون مصرف صفر نمی‌شود و فقط سقف بالا می‌رود، این محاسبه خودکار درست
    از آب در می‌آید: سقف جدید = سقف قدیم + پلن = ۱۰، مصرف = همان ۲،
    باقیمانده = ۱۰ - ۲ = ۸. ✅
    """
    base_url = _normalize_url(panel["url"])
    async with PasarguardAPI(
        base_url=base_url,
        verify=VERIFY_SSL,
        timeout=REQUEST_TIMEOUT,
    ) as api:
        token = await api.get_token(
            username=panel["username"],
            password=panel["password"],
        )
        current = await api.get_user_by_username(username=username, token=token.access_token)

        current_limit_gb = (getattr(current, "data_limit", 0) or 0) / (1024 ** 3)
        new_limit_gb = current_limit_gb + float(add_volume_gb)

        # --- تبدیل امن expire به timestamp عددی، چه datetime باشد چه int ---
        current_expire_ts = _to_timestamp(getattr(current, "expire", None))
        now_ts = int(time.time())
        base_ts = current_expire_ts if (current_expire_ts and current_expire_ts > now_ts) else now_ts
        new_expire_ts = base_ts + int(add_days) * 86400

        modify = UserModify(
            data_limit=Tools.gb(new_limit_gb),
            expire=new_expire_ts,
            status=UserStatus.ACTIVE,
        )
        await api.modify_user_by_username(
            username=username,
            user=modify,
            token=token.access_token,
        )

        # عمداً مصرف را صفر نمی‌کنیم — دلیل در docstring بالا توضیح داده شد

        return {
            "success": True,
            "error": "",
            "data_limit_gb": new_limit_gb,
            "expire": new_expire_ts,
        }


async def _apply_volume_increase_async(panel, username, add_volume_gb):
    """
    افزایش حجم روی خود پنل، بدون تغییر تاریخ انقضا یا صفر کردن مصرف.
    """
    base_url = _normalize_url(panel["url"])
    async with PasarguardAPI(
        base_url=base_url,
        verify=VERIFY_SSL,
        timeout=REQUEST_TIMEOUT,
    ) as api:
        token = await api.get_token(
            username=panel["username"],
            password=panel["password"],
        )
        current = await api.get_user_by_username(username=username, token=token.access_token)

        current_limit_gb = (getattr(current, "data_limit", 0) or 0) / (1024 ** 3)
        new_limit_gb = current_limit_gb + float(add_volume_gb)

        modify = UserModify(
            data_limit=Tools.gb(new_limit_gb),
        )
        await api.modify_user_by_username(
            username=username,
            user=modify,
            token=token.access_token,
        )
        return {
            "success": True,
            "error": "",
            "data_limit_gb": new_limit_gb,
        }


async def _delete_service_async(panel, username):
    """
    حذف کامل کاربر از روی پنل.
    نام متد حذف بین نسخه‌های مختلف SDK پاسارگارد فرق دارد،
    بنابراین رایج‌ترین نام‌های ممکن را به ترتیب امتحان می‌کنیم.
    """
    base_url = _normalize_url(panel["url"])
    async with PasarguardAPI(
        base_url=base_url,
        verify=VERIFY_SSL,
        timeout=REQUEST_TIMEOUT,
    ) as api:
        token = await api.get_token(
            username=panel["username"],
            password=panel["password"],
        )

        delete_fn = (
            getattr(api, "remove_user_by_username", None)
            or getattr(api, "delete_user_by_username", None)
            or getattr(api, "remove_user", None)
            or getattr(api, "delete_user", None)
        )
        if not delete_fn:
            return {
                "success": False,
                "error": (
                    "متد حذف کاربر در SDK پیدا نشد. "
                    "برای پیدا کردن نام درست متد این دستور را اجرا کنید: "
                    "python3 -c \"from pasarguard import PasarguardAPI; "
                    "print([m for m in dir(PasarguardAPI) if 'user' in m.lower()])\""
                ),
            }

        await delete_fn(username=username, token=token.access_token)
        return {"success": True, "error": ""}


# ============================================================
# SYNC WRAPPERS (used by the rest of the bot)
# ============================================================
def pasarguard_test_panel(panel):
    panel = dict(panel)
    if not _panel_credentials_ok(panel):
        return {"success": False, "error": "آدرس/یوزرنیم/پسورد پنل کامل نیست."}
    try:
        return asyncio.run(_test_panel_async(panel))
    except Exception as e:
        return {"success": False, "error": str(e)}


def pasarguard_create_service(panel, telegram_user, plan, desired_username=None):
    panel = dict(panel)
    telegram_user = dict(telegram_user)
    plan = dict(plan)
    if not _panel_credentials_ok(panel):
        return {"success": False, "error": "اطلاعات اتصال پنل (URL/Username/Password) کامل نیست."}
    try:
        return asyncio.run(
            _create_service_async(panel, telegram_user, plan, desired_username)
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def pasarguard_get_user_usage(panel, username):
    panel = dict(panel)
    if not _panel_credentials_ok(panel) or not username:
        return {"success": False, "error": "اطلاعات پنل یا نام کاربری ناقص است."}
    try:
        return asyncio.run(_get_user_usage_async(panel, username))
    except Exception as e:
        return {"success": False, "error": str(e)}


def pasarguard_apply_renewal(panel, username, add_volume_gb, add_days):
    panel = dict(panel)
    if not _panel_credentials_ok(panel) or not username:
        return {"success": False, "error": "اطلاعات پنل یا نام کاربری ناقص است."}
    try:
        return asyncio.run(
            _apply_renewal_async(panel, username, add_volume_gb, add_days)
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def pasarguard_apply_volume_increase(panel, username, add_volume_gb):
    panel = dict(panel)
    if not _panel_credentials_ok(panel) or not username:
        return {"success": False, "error": "اطلاعات پنل یا نام کاربری ناقص است."}
    try:
        return asyncio.run(
            _apply_volume_increase_async(panel, username, add_volume_gb)
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def pasarguard_delete_service(panel, username):
    panel = dict(panel)
    if not _panel_credentials_ok(panel) or not username:
        return {"success": False, "error": "اطلاعات پنل یا نام کاربری ناقص است."}
    try:
        return asyncio.run(_delete_service_async(panel, username))
    except Exception as e:
        return {"success": False, "error": str(e)}
