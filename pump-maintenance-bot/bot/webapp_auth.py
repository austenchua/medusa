"""Validation of Telegram Mini App initData.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str,
                       max_age_seconds: int = 86400) -> dict | None:
    """Return the Telegram user dict if init_data is authentic, else None."""
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
    except ValueError:
        return None
    given_hash = data.pop("hash", None)
    if not given_hash:
        return None

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, given_hash):
        return None

    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        return None
    if max_age_seconds and time.time() - auth_date > max_age_seconds:
        return None

    try:
        user = json.loads(data.get("user", ""))
    except (ValueError, TypeError):
        return None
    return user if isinstance(user, dict) and "id" in user else None
