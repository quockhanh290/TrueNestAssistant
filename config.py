"""Configuration for TrueNest Assistant bot."""
import os

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_NAME = "Linh"
BOT_FULL_NAME = "Linh - Trợ lý TrueNest"

DB_PATH = os.environ.get("BOT_DB_PATH", "broker_bot.db")

# Policies (Khanh to confirm)
MIN_PHOTOS = 3
RATE_LIMIT_PER_HOUR = 5
QUALIFY_APPROVED_COUNT = 3
NUDGE_DAYS = 7
MAX_MISSING_QUESTIONS = 2

# Critical fields — bot asks if missing (max 2)
CRITICAL_FIELDS = ["price_vnd", "primary_phone", "photos"]

# Response delay to feel natural (seconds)
REPLY_DELAY_MIN = 2
REPLY_DELAY_MAX = 5
