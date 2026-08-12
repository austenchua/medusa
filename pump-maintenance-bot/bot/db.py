"""SQLite storage layer.

All timestamps are stored as ISO-8601 strings in local (site) time so that
"this month" comparisons match the site calendar.
"""
import json
import sqlite3
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS workers (
    telegram_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    is_admin    INTEGER NOT NULL DEFAULT 0,
    approved    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pump_houses (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inspections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pump_house   TEXT NOT NULL REFERENCES pump_houses(code),
    worker_id    INTEGER NOT NULL REFERENCES workers(telegram_id),
    status       TEXT NOT NULL DEFAULT 'draft',   -- draft | submitted | cancelled
    started_at   TEXT NOT NULL,
    submitted_at TEXT
);

CREATE TABLE IF NOT EXISTS inspection_items (
    inspection_id INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    category      TEXT NOT NULL,
    task_id       INTEGER NOT NULL,
    freq          TEXT NOT NULL,
    result        TEXT,          -- ok | issue | skipped (NULL = not answered yet)
    value         TEXT,          -- formatted readings, e.g. "Current L1: 5.2 A; ..."
    note          TEXT,
    photo_file_id TEXT,          -- legacy single photo (chat flow)
    photos        TEXT,          -- JSON [{"label": "Before", "ref": "local:..."}]
    PRIMARY KEY (inspection_id, category, task_id)
);

CREATE INDEX IF NOT EXISTS idx_inspections_month
    ON inspections (pump_house, status, submitted_at);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the bot and the Mini App web server share the file safely.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def now_iso() -> str:
    return datetime.now(config.TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def init_db() -> None:
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        # Migrations for databases created before newer columns existed.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(inspection_items)")}
        if "value" not in cols:
            conn.execute("ALTER TABLE inspection_items ADD COLUMN value TEXT")
        if "photos" not in cols:
            conn.execute("ALTER TABLE inspection_items ADD COLUMN photos TEXT")
        houses = json.loads(
            (config.DATA_DIR / "pump_houses.json").read_text(encoding="utf-8")
        )
        conn.executemany(
            "INSERT OR IGNORE INTO pump_houses (code, name) VALUES (:code, :name)",
            houses,
        )
    conn.close()


# ---------------------------------------------------------------- workers

def get_worker(conn, telegram_id: int):
    return conn.execute(
        "SELECT * FROM workers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()


def upsert_worker(conn, telegram_id: int, name: str, is_admin: bool, approved: bool):
    with conn:
        conn.execute(
            """INSERT INTO workers (telegram_id, name, is_admin, approved, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(telegram_id) DO UPDATE
               SET name = excluded.name""",
            (telegram_id, name, int(is_admin), int(approved), now_iso()),
        )


def set_worker_approved(conn, telegram_id: int, approved: bool):
    with conn:
        conn.execute(
            "UPDATE workers SET approved = ? WHERE telegram_id = ?",
            (int(approved), telegram_id),
        )


def list_admins(conn):
    return conn.execute("SELECT * FROM workers WHERE is_admin = 1").fetchall()


# ------------------------------------------------------------ pump houses

def list_pump_houses(conn):
    return conn.execute("SELECT * FROM pump_houses ORDER BY code").fetchall()


def get_pump_house(conn, code: str):
    return conn.execute(
        "SELECT * FROM pump_houses WHERE code = ?", (code,)
    ).fetchone()


def search_pump_houses(conn, text: str):
    like = f"%{text.upper()}%"
    return conn.execute(
        "SELECT * FROM pump_houses WHERE code LIKE ? OR UPPER(name) LIKE ? ORDER BY code",
        (like, like),
    ).fetchall()


# ------------------------------------------------------------ inspections

def get_draft(conn, worker_id: int):
    """The worker's current unfinished inspection, if any."""
    return conn.execute(
        "SELECT * FROM inspections WHERE worker_id = ? AND status = 'draft' "
        "ORDER BY id DESC LIMIT 1",
        (worker_id,),
    ).fetchone()


def create_inspection(conn, pump_house: str, worker_id: int, items) -> int:
    """items: iterable of (category, task_id, freq)."""
    with conn:
        cur = conn.execute(
            "INSERT INTO inspections (pump_house, worker_id, status, started_at) "
            "VALUES (?, ?, 'draft', ?)",
            (pump_house, worker_id, now_iso()),
        )
        insp_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO inspection_items (inspection_id, category, task_id, freq) "
            "VALUES (?, ?, ?, ?)",
            [(insp_id, c, t, f) for (c, t, f) in items],
        )
    return insp_id


def get_inspection(conn, insp_id: int):
    return conn.execute(
        "SELECT * FROM inspections WHERE id = ?", (insp_id,)
    ).fetchone()


def get_items(conn, insp_id: int, category: str | None = None):
    if category:
        return conn.execute(
            "SELECT * FROM inspection_items WHERE inspection_id = ? AND category = ? "
            "ORDER BY task_id",
            (insp_id, category),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM inspection_items WHERE inspection_id = ? ORDER BY category, task_id",
        (insp_id,),
    ).fetchall()


def set_item_result(conn, insp_id: int, category: str, task_id: int,
                    result: str | None, note: str | None = None,
                    photo_file_id: str | None = None,
                    value: str | None = None,
                    photos: str | None = None):
    with conn:
        conn.execute(
            """UPDATE inspection_items
               SET result = ?, note = ?, photo_file_id = ?, value = ?, photos = ?
               WHERE inspection_id = ? AND category = ? AND task_id = ?""",
            (result, note, photo_file_id, value, photos, insp_id, category, task_id),
        )


def set_category_ok(conn, insp_id: int, category: str):
    """Mark every still-unanswered task in the category as OK."""
    with conn:
        conn.execute(
            "UPDATE inspection_items SET result = 'ok' "
            "WHERE inspection_id = ? AND category = ? AND result IS NULL",
            (insp_id, category),
        )


def set_inspection_status(conn, insp_id: int, status: str):
    with conn:
        conn.execute(
            "UPDATE inspections SET status = ?, submitted_at = ? WHERE id = ?",
            (status, now_iso() if status == "submitted" else None, insp_id),
        )


def delete_inspection(conn, insp_id: int):
    with conn:
        conn.execute("DELETE FROM inspection_items WHERE inspection_id = ?", (insp_id,))
        conn.execute("DELETE FROM inspections WHERE id = ?", (insp_id,))


# ------------------------------------------------------- due computation

def last_done_months(conn, pump_house: str):
    """Map (category, task_id) -> year*12+month of the most recent submitted
    inspection in which the task was answered OK."""
    rows = conn.execute(
        """SELECT it.category, it.task_id, MAX(i.submitted_at) AS last_at
           FROM inspection_items it
           JOIN inspections i ON i.id = it.inspection_id
           WHERE i.pump_house = ? AND i.status = 'submitted' AND it.result = 'ok'
           GROUP BY it.category, it.task_id""",
        (pump_house,),
    ).fetchall()
    out = {}
    for r in rows:
        dt = datetime.strptime(r["last_at"][:7], "%Y-%m")
        out[(r["category"], r["task_id"])] = dt.year * 12 + dt.month
    return out


# ------------------------------------------------------------- reporting

def month_bounds(year: int, month: int) -> tuple[str, str]:
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"
    return start, end


def submitted_in_month(conn, year: int, month: int):
    start, end = month_bounds(year, month)
    return conn.execute(
        """SELECT i.*, w.name AS worker_name, p.name AS pump_house_name
           FROM inspections i
           JOIN workers w ON w.telegram_id = i.worker_id
           JOIN pump_houses p ON p.code = i.pump_house
           WHERE i.status = 'submitted' AND i.submitted_at >= ? AND i.submitted_at < ?
           ORDER BY i.pump_house, i.submitted_at""",
        (start, end),
    ).fetchall()


def items_for_inspections(conn, insp_ids: list[int]):
    if not insp_ids:
        return []
    qs = ",".join("?" * len(insp_ids))
    return conn.execute(
        f"SELECT * FROM inspection_items WHERE inspection_id IN ({qs}) "
        "ORDER BY inspection_id, category, task_id",
        insp_ids,
    ).fetchall()
