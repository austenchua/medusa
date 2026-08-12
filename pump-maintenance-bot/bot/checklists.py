"""Checklist definitions (from BQ Bill U2) and due-task computation."""
import json
from datetime import datetime

from . import config, db

FREQ_MONTHS = {"M": 1, "3M": 3, "6M": 6, "Y": 12}

_data = json.loads((config.DATA_DIR / "checklists.json").read_text(encoding="utf-8"))

CATEGORIES: list[dict] = _data["categories"]
CATEGORY_BY_KEY = {c["key"]: c for c in CATEGORIES}
FREQ_LABELS: dict[str, str] = _data["frequencies"]


def task_of(category_key: str, task_id: int) -> dict:
    cat = CATEGORY_BY_KEY[category_key]
    return next(t for t in cat["tasks"] if t["id"] == task_id)


def due_items(conn, pump_house: str) -> list[tuple[str, int, str]]:
    """Tasks due for this pump house right now, as (category, task_id, freq).

    Monthly tasks are due unless already completed this calendar month;
    3M/6M/Y tasks are due when their last OK completion is at least that many
    months old (or has never happened).
    """
    now = datetime.now(config.TIMEZONE)
    current_ym = now.year * 12 + now.month
    last_done = db.last_done_months(conn, pump_house)

    due = []
    for cat in CATEGORIES:
        for task in cat["tasks"]:
            interval = FREQ_MONTHS[task["freq"]]
            last_ym = last_done.get((cat["key"], task["id"]))
            if last_ym is None or current_ym - last_ym >= interval:
                due.append((cat["key"], task["id"], task["freq"]))
    return due
