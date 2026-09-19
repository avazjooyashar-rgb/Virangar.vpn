# ============================================================
# pasarguard_api.py
# اتصال واقعی به پنل PasarGuard با استفاده از SDK رسمی
# پکیج پایتون: pip install pasarguard   (https://pypi.org/project/pasarguard/)
# ============================================================
#
# نکات مهم:
# 1) یوزر/پسوردی که موقع افزودن پنل وارد می‌کنید باید مربوط به
#    یک ادمین «sudo» در پنل PasarGuard باشد، نه یک اپراتور محدود؛
#    چون برای اضافه‌کردن کاربر به همه‌ی گروه‌ها به دسترسی کامل نیاز است.
# 2) کاربر تازه‌ساخته‌شده با create_user_in_all_groups به تمام
#    گروه‌ها (و در نتیجه هاست‌هایی که روی پنل تعریف کرده‌اید) اضافه می‌شود.
# 3) اگر ارتباط SSL پنل گواهی معتبر ندارد (self-signed)، مقدار
#    VERIFY_SSL را در همین فایل False کنید.
# 4) پنل PasarGuard نقطه (.) را در یوزرنیم قبول نمی‌کند، پس نام
#    دلخواه کاربر (مثلاً virangarvpn.ali) قبل از ارسال به پنل به
#    virangarvpn_ali تبدیل می‌شود.
# ============================================================
import re
import asyncio
from pasarguard import PasarguardAPI, Tools, UserCreate, UserStatus

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
    """
    یوزرنیم پنل باید فقط شامل حروف/عدد/آندرلاین باشد.
    نقطه و کاراکترهای غیرمجاز با _ جایگزین می‌شوند.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", raw or "")
    cleaned = cleaned.strip("_")
    return cleaned or None


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

        # نکته: اینجا از int() استفاده نمی‌کنیم چون حجم می‌تواند
        # اعشاری هم باشد (مثلاً 0.5 گیگ برای تست رایگان). با int()
        # مقادیر کمتر از 1 به صفر رند می‌شدند و پنل PasarGuard
        # data_limit=0 را «نامحدود» تفسیر می‌کند.
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


# ============================================================
# SYNC WRAPPERS (used by the rest of the bot)
# ============================================================
def pasarguard_test_panel(panel):
    """
    تست واقعی اتصال: گرفتن توکن ادمین از پنل و خواندن اطلاعات
    ادمین لاگین‌شده.
    """
    panel = dict(panel)
    if not _panel_credentials_ok(panel):
        return {
            "success": False,
            "error": "آدرس/یوزرنیم/پسورد پنل کامل نیست."
        }
    try:
        return asyncio.run(_test_panel_async(panel))
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def pasarguard_create_service(panel, telegram_user, plan, desired_username=None):
    """
    ساخت واقعی کاربر روی پنل PasarGuard و دریافت لینک اشتراک (subscription).
    اگر desired_username داده شود، همان (پس از پاکسازی) به‌عنوان
    یوزرنیم نهایی روی پنل استفاده می‌شود؛ در غیر این صورت یک یوزرنیم
    تصادفی ساخته می‌شود.
    """
    panel = dict(panel)
    telegram_user = dict(telegram_user)
    plan = dict(plan)
    if not _panel_credentials_ok(panel):
        return {
            "success": False,
            "error": "اطلاعات اتصال پنل (URL/Username/Password) کامل نیست."
        }
    try:
        return asyncio.run(
            _create_service_async(panel, telegram_user, plan, desired_username)
        )
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
