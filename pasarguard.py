# ============================================================
# pasarguard.py
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
# ============================================================

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


async def _create_service_async(panel, telegram_user, plan, username=None):
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

        # اگر یوزرنیم دلخواه (مثلاً برای تست رایگان: virangarvpn.ali)
        # پاس داده شده باشد از همان استفاده می‌کنیم، در غیر این صورت
        # مثل قبل یک یوزرنیم رندوم ساخته می‌شود (رفتار پلن‌های خرید عادی).
        final_username = (username or "").strip()

        if not final_username:
            final_username = Tools.random_username(
                prefix=f"tg{telegram_user['telegram_id']}"
            )

        user_create = UserCreate(
            username=final_username,
            data_limit=Tools.gb(int(plan["volume"])),
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
    ادمین لاگین‌شده. برخلاف نسخه قبلی، این فقط ping ساده نیست.
    """

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


def pasarguard_create_service(panel, telegram_user, plan, username=None):
    """
    ساخت واقعی کاربر روی پنل PasarGuard و دریافت لینک اشتراک (subscription).

    پارامتر username اختیاری است:
    - برای پلن‌های عادی خالی می‌ماند و یوزرنیم رندوم ساخته می‌شود.
    - برای تست رایگان، یوزرنیمی که خود کاربر انتخاب کرده
      (مثلاً virangarvpn.ali) پاس داده می‌شود.
    """

    if not _panel_credentials_ok(panel):
        return {
            "success": False,
            "error": "اطلاعات اتصال پنل (URL/Username/Password) کامل نیست."
        }

    try:
        return asyncio.run(
            _create_service_async(panel, telegram_user, plan, username=username)
        )

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
