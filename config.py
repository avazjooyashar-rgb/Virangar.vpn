# ============================================================
# config.py
# تنظیمات کلی، متغیرهای محیطی و ساخت نمونه‌ی bot
# ============================================================

import os
import logging

import telebot
from dotenv import load_dotenv

load_dotenv()

# ---------------- ENV VARS ----------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "0") or 0)

DB_PATH = os.getenv("DATABASE_URL", "sqlite:///virangarvpn.db")
if DB_PATH.startswith("sqlite:///"):
    DB_PATH = DB_PATH.replace("sqlite:///", "", 1)

BOT_NAME = os.getenv("BOT_NAME", "VirangarVPN")

# ---------------- LOGGING ----------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is empty")

# ---------------- BOT INSTANCE ----------------

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML",
    threaded=True,
)
