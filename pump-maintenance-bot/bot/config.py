"""Configuration loaded from environment variables (see .env.example)."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Comma-separated Telegram user IDs that are administrators.
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x
}

DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "bppm.sqlite3"))

# Sabah, Malaysia
TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Kuching"))

# Hour (local time) at which the daily progress digest is sent to admins.
DAILY_DIGEST_HOUR = int(os.environ.get("DAILY_DIGEST_HOUR", "18"))
