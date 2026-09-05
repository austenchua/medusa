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

# --- Mini App (in-Telegram UI) ---
# Public HTTPS URL where the Mini App is reachable (Telegram requires HTTPS),
# e.g. https://bppm.example.com — leave empty to run chat-only.
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").rstrip("/")
# Local port the built-in web server listens on (put a reverse proxy or
# Cloudflare tunnel in front of it for HTTPS). 0 disables the server.
WEBAPP_PORT = int(os.environ.get("WEBAPP_PORT", "8080" if WEBAPP_URL else "0"))
WEBAPP_DIR = BASE_DIR / "webapp"
# Where issue photos uploaded through the Mini App are stored.
PHOTO_DIR = Path(os.environ.get("PHOTO_DIR", str(BASE_DIR / "photos")))
