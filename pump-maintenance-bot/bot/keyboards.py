"""Inline keyboard builders.

Callback-data grammar (kept short — Telegram caps callback data at 64 bytes):
    ph:<page>                 pump-house browser page
    sel:<code>                select pump house
    cat:<key>                 open category screen
    allok:<key>               mark remaining tasks in category OK
    task:<key>:<id>           open a single task
    res:<key>:<id>:<result>   answer a task (ok | issue | skip)
    back:cats                 back to category overview
    summary / submit / cancel / resume / newinsp
    approve:<uid> / reject:<uid>
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import checklists

PAGE_SIZE = 8

RESULT_EMOJI = {None: "⬜", "ok": "✅", "issue": "⚠️", "skipped": "⏭"}


def pump_house_page(houses, page: int) -> InlineKeyboardMarkup:
    pages = max(1, (len(houses) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = houses[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    rows = [
        [InlineKeyboardButton(f"{h['code']} · {h['name']}", callback_data=f"sel:{h['code']}")]
        for h in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"ph:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"ph:{page + 1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(rows)


def category_overview(items) -> InlineKeyboardMarkup:
    """One button per category showing progress, e.g. '⚙️ Booster Pump  3/11 ✔'."""
    by_cat: dict[str, list] = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)

    rows = []
    for cat in checklists.CATEGORIES:
        cat_items = by_cat.get(cat["key"])
        if not cat_items:
            continue  # nothing due in this category
        done = sum(1 for i in cat_items if i["result"] is not None)
        total = len(cat_items)
        flag = "✅" if done == total else f"{done}/{total}"
        rows.append([
            InlineKeyboardButton(
                f"{cat['emoji']} {cat['name']} · {flag}",
                callback_data=f"cat:{cat['key']}",
            )
        ])
    rows.append([
        InlineKeyboardButton("📋 Review & Submit", callback_data="summary"),
        InlineKeyboardButton("🗑 Cancel", callback_data="cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def category_tasks(cat_key: str, items) -> InlineKeyboardMarkup:
    rows = []
    for it in items:
        task = checklists.task_of(cat_key, it["task_id"])
        emoji = RESULT_EMOJI[it["result"]]
        label = f"{emoji} {it['task_id']}. {task['desc']}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([InlineKeyboardButton(label, callback_data=f"task:{cat_key}:{it['task_id']}")])
    if any(it["result"] is None for it in items):
        rows.append([InlineKeyboardButton("✅ All remaining OK", callback_data=f"allok:{cat_key}")])
    rows.append([InlineKeyboardButton("⬅️ Back to categories", callback_data="back:cats")])
    return InlineKeyboardMarkup(rows)


def task_actions(cat_key: str, task_id: int) -> InlineKeyboardMarkup:
    base = f"res:{cat_key}:{task_id}"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ OK", callback_data=f"{base}:ok"),
            InlineKeyboardButton("⚠️ Issue", callback_data=f"{base}:issue"),
        ],
        [
            InlineKeyboardButton("⏭ Skip / N.A.", callback_data=f"{base}:skip"),
            InlineKeyboardButton("⬅️ Back", callback_data=f"cat:{cat_key}"),
        ],
    ])


def summary_actions(all_done: bool) -> InlineKeyboardMarkup:
    rows = []
    if all_done:
        rows.append([InlineKeyboardButton("📤 Submit inspection", callback_data="submit")])
    rows.append([
        InlineKeyboardButton("⬅️ Back", callback_data="back:cats"),
        InlineKeyboardButton("🗑 Cancel", callback_data="cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def resume_or_new() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Resume unfinished inspection", callback_data="resume")],
        [InlineKeyboardButton("🆕 Discard it & start new", callback_data="newinsp")],
    ])


def approval(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{uid}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject:{uid}"),
    ]])
