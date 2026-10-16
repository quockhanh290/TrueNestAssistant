"""Configuration for TrueNest Assistant bot."""
import os

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_NAME = "Linh"
BOT_FULL_NAME = "Linh - Trợ lý TrueNest"

DB_PATH = os.environ.get("BOT_DB_PATH", "broker_bot.db")

# Policies (Khanh to confirm)
MIN_PHOTOS = 3
# Rate limits per tier: listings per hour
RATE_LIMITS_PER_HOUR = {
    "free": 10,
    "pro": 20,
    "max": 30,
    "enterprise": 50,
}
# Backward compat
RATE_LIMIT_PER_HOUR = 5
QUALIFY_APPROVED_COUNT = 3
NUDGE_DAYS = 7
MAX_MISSING_QUESTIONS = 2

# Critical fields — bot asks if missing (max 2)
CRITICAL_FIELDS = ["price_vnd", "primary_phone", "photos"]

# Response delay to feel natural (seconds) — kept short; the longer
# "writing" pause lives only in the FB-post generator.
REPLY_DELAY_MIN = 0.5
REPLY_DELAY_MAX = 1.5

# Private broker group for cross-broker matching broadcasts.
# Set to the group's chat id (e.g. -1001234567890). Empty = feature disabled.
BROKER_GROUP_ID = os.getenv("BROKER_GROUP_ID", "")

# Anti-spam for cross-broker broadcasts.
BROADCAST_DAILY_LIMIT = int(os.getenv("BROADCAST_DAILY_LIMIT", "3"))      # max broadcasts/broker/day
BROADCAST_WEEKLY_LIMIT = int(os.getenv("BROADCAST_WEEKLY_LIMIT", "10"))   # max broadcasts/broker/week
BROADCAST_COOLDOWN_HOURS = int(os.getenv("BROADCAST_COOLDOWN_HOURS", "6")) # min hours between broadcasts

# Premium tiers
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))  # Khanh's Telegram user id
FREE_LISTING_LIMIT = int(os.getenv("FREE_LISTING_LIMIT", "20"))  # max active listings for free tier

# Payment info for premium upgrades (shown in /premium)
PAYMENT_BANK = os.getenv("PAYMENT_BANK", "VCB 1234567890 - NGUYEN VAN A")
PAYMENT_MOMO = os.getenv("PAYMENT_MOMO", "0905123456")

# Platform commission on closed deals (20%). Broker transfers this amount
# after closing; receipt photo is verified by admin on phone.
PLATFORM_FEE_RATE = float(os.getenv("PLATFORM_FEE_RATE", "0.20"))

# Free translation for saved posts (MyMemory primary, Lingva fallback).
# When a broker edits the Vietnamese post, other language versions are
# auto-translated. Set TRANSLATION_EMAIL for MyMemory 50k chars/day
# (anonymous = 5k chars/day).
TRANSLATION_ENABLED = os.getenv("TRANSLATION_ENABLED", "1") == "1"
TRANSLATION_EMAIL = os.getenv("TRANSLATION_EMAIL", "sapnhami@gmail.com")

# Telegram WebApp for listing management. Telegram requires HTTPS for the
# public URL; localhost is fine for local dev/testing.
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:8080")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8080"))
