"""Telegram handlers: worker inspection flow + admin tools."""
import html
import logging
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from . import checklists, config, db, keyboards, reports

log = logging.getLogger(__name__)


def esc(s) -> str:
    return html.escape(str(s))


def _conn(context: ContextTypes.DEFAULT_TYPE):
    """One shared SQLite connection kept on bot_data."""
    conn = context.bot_data.get("conn")
    if conn is None:
        conn = db.connect()
        context.bot_data["conn"] = conn
    return conn


async def _notify_admins(context, text, photo_file_id=None, reply_markup=None):
    conn = _conn(context)
    admin_ids = {r["telegram_id"] for r in db.list_admins(conn)} | config.ADMIN_IDS
    for admin_id in admin_ids:
        try:
            if photo_file_id:
                await context.bot.send_photo(
                    admin_id, photo_file_id, caption=text,
                    parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            else:
                await context.bot.send_message(
                    admin_id, text, parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup)
        except Exception:
            log.warning("Could not notify admin %s", admin_id, exc_info=True)


# ------------------------------------------------------------------ /start

WELCOME_WORKER = (
    "👋 Hi <b>{name}</b>!\n\n"
    "This bot records your daily booster-pump preventive maintenance.\n\n"
    "▪️ /new — start a pump house inspection\n"
    "▪️ /today — what you have submitted today\n"
    "▪️ /help — how it works"
)

WELCOME_ADMIN = (
    "\n\n<b>Admin commands</b>\n"
    "▪️ /status — this month's coverage (x/72)\n"
    "▪️ /report — Excel report for a month\n"
    "▪️ /pending — approve new workers"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = _conn(context)
    user = update.effective_user
    worker = db.get_worker(conn, user.id)

    if worker is None:
        if user.id in config.ADMIN_IDS:
            db.upsert_worker(conn, user.id, user.full_name, is_admin=True, approved=True)
            worker = db.get_worker(conn, user.id)
        else:
            context.user_data["awaiting"] = ("name",)
            await update.message.reply_text(
                "👋 Welcome! You are not registered yet.\n\n"
                "Please reply with your <b>full name</b> so the admin can approve you.",
                parse_mode=ParseMode.HTML)
            return

    if not worker["approved"]:
        await update.message.reply_text(
            "⏳ Your registration is waiting for admin approval. "
            "You will be notified once approved.")
        return

    text = WELCOME_WORKER.format(name=esc(worker["name"]))
    if worker["is_admin"]:
        text += WELCOME_ADMIN
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>How to record an inspection</b>\n\n"
        "1️⃣ Send /new and pick the pump house (tap it, or type e.g. "
        "<code>BPH23</code> or <code>likas</code> to search).\n"
        "2️⃣ The bot shows only the tasks <b>due today</b> — monthly tasks plus "
        "any 3-monthly / 6-monthly / yearly tasks that have come due.\n"
        "3️⃣ Open each equipment category. If everything is fine, tap "
        "<b>✅ All remaining OK</b> — one tap per category.\n"
        "4️⃣ Found a problem? Tap the task → <b>⚠️ Issue</b> → type what's wrong "
        "(you can attach a photo with your text as its caption).\n"
        "5️⃣ When every category shows ✅, tap <b>Review &amp; Submit</b>.\n\n"
        "You can leave and come back any time — /new resumes an unfinished "
        "inspection.",
        parse_mode=ParseMode.HTML)


async def _require_worker(update, context):
    conn = _conn(context)
    worker = db.get_worker(conn, update.effective_user.id)
    if worker is None or not worker["approved"]:
        await update.effective_message.reply_text(
            "You are not registered/approved yet — send /start first.")
        return None
    return worker


# --------------------------------------------------------- inspection flow

async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    worker = await _require_worker(update, context)
    if worker is None:
        return
    conn = _conn(context)
    draft = db.get_draft(conn, worker["telegram_id"])
    if draft:
        ph = db.get_pump_house(conn, draft["pump_house"])
        await update.message.reply_text(
            f"You have an unfinished inspection at <b>{esc(ph['code'])} · "
            f"{esc(ph['name'])}</b> (started {esc(draft['started_at'][:16])}).",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.resume_or_new())
        return
    await _ask_pump_house(update.message, context)


async def _ask_pump_house(message, context):
    conn = _conn(context)
    houses = db.list_pump_houses(conn)
    context.user_data["awaiting"] = ("pump_search",)
    await message.reply_text(
        "🏠 <b>Which pump house?</b>\n\n"
        "Tap it below, or just type its number/name to search "
        "(e.g. <code>23</code>, <code>BPH23</code>, <code>likas</code>).",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.pump_house_page(houses, 0))


async def _open_inspection(message, context, worker, code: str):
    """Create (or reuse) the draft for this pump house and show the overview."""
    conn = _conn(context)
    ph = db.get_pump_house(conn, code)
    if ph is None:
        await message.reply_text("Unknown pump house code.")
        return
    context.user_data.pop("awaiting", None)

    draft = db.get_draft(conn, worker["telegram_id"])
    if draft and draft["pump_house"] == code:
        insp_id = draft["id"]
    else:
        if draft:
            db.delete_inspection(conn, draft["id"])
        due = checklists.due_items(conn, code)
        if not due:
            await message.reply_text(
                f"🎉 Nothing is due at <b>{esc(code)} · {esc(ph['name'])}</b> — "
                "everything was already completed this period.",
                parse_mode=ParseMode.HTML)
            return
        insp_id = db.create_inspection(conn, code, worker["telegram_id"], due)

    await _show_overview(message, context, insp_id, edit=False)


def _overview_text(conn, insp) -> str:
    ph = db.get_pump_house(conn, insp["pump_house"])
    items = db.get_items(conn, insp["id"])
    done = sum(1 for i in items if i["result"] is not None)
    issues = sum(1 for i in items if i["result"] == "issue")
    extra = [i for i in items if i["freq"] != "M"]
    text = (
        f"🔧 <b>{esc(ph['code'])} · {esc(ph['name'])}</b>\n"
        f"Progress: <b>{done}/{len(items)}</b> tasks"
    )
    if issues:
        text += f" · ⚠️ {issues} issue(s)"
    if extra:
        labels = sorted({checklists.FREQ_LABELS[i['freq']] for i in extra})
        text += f"\n📅 Includes due periodic checks: {esc(', '.join(labels))}"
    text += "\n\nTap a category, then ✅ All remaining OK or flag issues:"
    return text


async def _show_overview(message_or_query, context, insp_id: int, edit: bool):
    conn = _conn(context)
    insp = db.get_inspection(conn, insp_id)
    items = db.get_items(conn, insp_id)
    text = _overview_text(conn, insp)
    markup = keyboards.category_overview(items)
    if edit:
        await message_or_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await message_or_query.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _show_category(query, context, insp_id: int, cat_key: str):
    conn = _conn(context)
    items = db.get_items(conn, insp_id, cat_key)
    cat = checklists.CATEGORY_BY_KEY[cat_key]
    await query.edit_message_text(
        f"{cat['emoji']} <b>{esc(cat['name'])}</b>\n"
        "Tap a task to answer it (⬜ = not answered):",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.category_tasks(cat_key, items))


async def _show_summary(query, context, insp_id: int):
    conn = _conn(context)
    insp = db.get_inspection(conn, insp_id)
    ph = db.get_pump_house(conn, insp["pump_house"])
    items = db.get_items(conn, insp_id)
    unanswered = [i for i in items if i["result"] is None]
    issues = [i for i in items if i["result"] == "issue"]
    skipped = [i for i in items if i["result"] == "skipped"]
    ok = sum(1 for i in items if i["result"] == "ok")

    lines = [
        f"📋 <b>Summary — {esc(ph['code'])} · {esc(ph['name'])}</b>",
        f"✅ OK: {ok}   ⚠️ Issues: {len(issues)}   ⏭ Skipped: {len(skipped)}",
    ]
    if issues:
        lines.append("\n<b>Issues found:</b>")
        for i in issues:
            task = checklists.task_of(i["category"], i["task_id"])
            cat = checklists.CATEGORY_BY_KEY[i["category"]]
            note = f" — {esc(i['note'])}" if i["note"] else ""
            lines.append(f"• {esc(cat['name'])}: {esc(task['desc'])}{note}")
    if unanswered:
        lines.append(f"\n⬜ <b>{len(unanswered)} task(s) not answered yet</b> — "
                     "finish them before submitting.")
    await query.edit_message_text(
        "\n".join(lines), parse_mode=ParseMode.HTML,
        reply_markup=keyboards.summary_actions(all_done=not unanswered))


async def _submit(query, context, insp_id: int):
    conn = _conn(context)
    insp = db.get_inspection(conn, insp_id)
    ph = db.get_pump_house(conn, insp["pump_house"])
    worker = db.get_worker(conn, insp["worker_id"])
    db.set_inspection_status(conn, insp_id, "submitted")

    items = db.get_items(conn, insp_id)
    issues = [i for i in items if i["result"] == "issue"]
    await query.edit_message_text(
        f"✅ <b>Submitted!</b> {esc(ph['code'])} · {esc(ph['name'])}\n"
        f"{len(items)} tasks recorded"
        + (f", ⚠️ {len(issues)} issue(s) reported." if issues else "."),
        parse_mode=ParseMode.HTML)

    # Alert admins about issues immediately.
    if issues:
        header = (f"⚠️ <b>Issues at {esc(ph['code'])} · {esc(ph['name'])}</b>\n"
                  f"Reported by {esc(worker['name'])}, {esc(db.now_iso()[:16])}\n")
        body = []
        for i in issues:
            task = checklists.task_of(i["category"], i["task_id"])
            cat = checklists.CATEGORY_BY_KEY[i["category"]]
            note = f"\n  📝 {esc(i['note'])}" if i["note"] else ""
            body.append(f"• {esc(cat['name'])}: {esc(task['desc'])}{note}")
        await _notify_admins(context, header + "\n".join(body))
        for i in issues:
            if i["photo_file_id"]:
                task = checklists.task_of(i["category"], i["task_id"])
                await _notify_admins(
                    context,
                    f"📷 {esc(ph['code'])} — {esc(task['desc'])}",
                    photo_file_id=i["photo_file_id"])


# ------------------------------------------------------------ callbacks

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    conn = _conn(context)
    await query.answer()

    if data == "noop":
        return

    # Admin approval buttons work without a draft.
    if data.startswith(("approve:", "reject:")):
        await _handle_approval(update, context, data)
        return

    worker = db.get_worker(conn, update.effective_user.id)
    if worker is None or not worker["approved"]:
        await query.edit_message_text("You are not approved yet — send /start.")
        return

    if data.startswith("ph:"):
        houses = db.list_pump_houses(conn)
        await query.edit_message_reply_markup(
            keyboards.pump_house_page(houses, int(data.split(":")[1])))
        return

    if data.startswith("sel:"):
        await _open_inspection(query.message, context, worker, data.split(":")[1])
        return

    draft = db.get_draft(conn, worker["telegram_id"])

    if data == "resume":
        if draft:
            await _show_overview(query, context, draft["id"], edit=True)
        else:
            await query.edit_message_text("No unfinished inspection — send /new.")
        return

    if data == "newinsp":
        if draft:
            db.delete_inspection(conn, draft["id"])
        await _ask_pump_house(query.message, context)
        return

    if draft is None:
        await query.edit_message_text("This inspection is closed — send /new to start.")
        return
    insp_id = draft["id"]

    if data.startswith("cat:"):
        await _show_category(query, context, insp_id, data.split(":")[1])
    elif data.startswith("allok:"):
        cat_key = data.split(":")[1]
        db.set_category_ok(conn, insp_id, cat_key)
        await _show_overview(query, context, insp_id, edit=True)
    elif data.startswith("task:"):
        _, cat_key, task_id = data.split(":")
        task = checklists.task_of(cat_key, int(task_id))
        cat = checklists.CATEGORY_BY_KEY[cat_key]
        await query.edit_message_text(
            f"{cat['emoji']} <b>{esc(cat['name'])}</b> — task {task['id']}\n"
            f"({esc(checklists.FREQ_LABELS[task['freq']])})\n\n"
            f"<b>{esc(task['desc'])}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.task_actions(cat_key, int(task_id)))
    elif data.startswith("res:"):
        _, cat_key, task_id, result = data.split(":")
        task_id = int(task_id)
        if result == "issue":
            context.user_data["awaiting"] = ("issue", insp_id, cat_key, task_id)
            task = checklists.task_of(cat_key, task_id)
            await query.edit_message_text(
                f"⚠️ <b>{esc(task['desc'])}</b>\n\n"
                "Describe the issue in one message. To include a photo, send the "
                "photo with your description as its caption.",
                parse_mode=ParseMode.HTML)
        else:
            db.set_item_result(conn, insp_id, cat_key, task_id,
                               "ok" if result == "ok" else "skipped")
            items = db.get_items(conn, insp_id, cat_key)
            if all(i["result"] is not None for i in items):
                await _show_overview(query, context, insp_id, edit=True)
            else:
                await _show_category(query, context, insp_id, cat_key)
    elif data == "back:cats":
        await _show_overview(query, context, insp_id, edit=True)
    elif data == "summary":
        await _show_summary(query, context, insp_id)
    elif data == "submit":
        await _submit(query, context, insp_id)
    elif data == "cancel":
        db.delete_inspection(conn, insp_id)
        await query.edit_message_text("🗑 Inspection discarded. Send /new to start again.")


async def _handle_approval(update, context, data):
    conn = _conn(context)
    admin = db.get_worker(conn, update.effective_user.id)
    if not admin or not admin["is_admin"]:
        return
    action, uid = data.split(":")
    uid = int(uid)
    worker = db.get_worker(conn, uid)
    if worker is None:
        await update.callback_query.edit_message_text("Worker no longer exists.")
        return
    if action == "approve":
        db.set_worker_approved(conn, uid, True)
        await update.callback_query.edit_message_text(
            f"✅ Approved {esc(worker['name'])}.", parse_mode=ParseMode.HTML)
        try:
            await context.bot.send_message(
                uid, "✅ You are approved! Send /new to start your first inspection.")
        except Exception:
            log.warning("Could not message approved worker %s", uid)
    else:
        db.set_worker_approved(conn, uid, False)
        await update.callback_query.edit_message_text(
            f"❌ Rejected {esc(worker['name'])}.", parse_mode=ParseMode.HTML)


# ----------------------------------------------------- text & photo input

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return
    conn = _conn(context)
    msg = update.message
    kind = awaiting[0]

    if kind == "name":
        name = (msg.text or "").strip()
        if not name:
            await msg.reply_text("Please send your full name as text.")
            return
        db.upsert_worker(conn, update.effective_user.id, name,
                         is_admin=False, approved=False)
        context.user_data.pop("awaiting", None)
        await msg.reply_text(
            "Thanks! Your registration was sent to the admin — "
            "you'll get a message once approved. ⏳")
        await _notify_admins(
            context,
            f"🆕 <b>New worker registration</b>\n{esc(name)} "
            f"(id <code>{update.effective_user.id}</code>)",
            reply_markup=keyboards.approval(update.effective_user.id))
        return

    if kind == "pump_search":
        text = (msg.text or "").strip()
        if not text:
            return
        if text.isdigit():
            text = f"BPH{int(text):02d}"
        matches = db.search_pump_houses(conn, text)
        worker = db.get_worker(conn, update.effective_user.id)
        if not matches:
            await msg.reply_text("No pump house matches — try again (e.g. BPH23 or likas).")
        elif len(matches) == 1:
            await _open_inspection(msg, context, worker, matches[0]["code"])
        else:
            await msg.reply_text(
                f"Found {len(matches)} matches:",
                reply_markup=keyboards.pump_house_page(matches, 0))
        return

    if kind == "issue":
        _, insp_id, cat_key, task_id = awaiting
        note = (msg.text or msg.caption or "").strip()
        photo_id = msg.photo[-1].file_id if msg.photo else None
        if not note and not photo_id:
            await msg.reply_text("Please send a text description (or photo with caption).")
            return
        db.set_item_result(conn, insp_id, cat_key, task_id, "issue",
                           note=note or None, photo_file_id=photo_id)
        context.user_data.pop("awaiting", None)
        await msg.reply_text("⚠️ Issue recorded.")
        await _show_overview(msg, context, insp_id, edit=False)
        return


# -------------------------------------------------------------- /today

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    worker = await _require_worker(update, context)
    if worker is None:
        return
    conn = _conn(context)
    today = db.now_iso()[:10]
    rows = conn.execute(
        """SELECT i.*, p.name AS ph_name FROM inspections i
           JOIN pump_houses p ON p.code = i.pump_house
           WHERE i.worker_id = ? AND i.status = 'submitted'
             AND substr(i.submitted_at, 1, 10) = ?
           ORDER BY i.submitted_at""",
        (worker["telegram_id"], today)).fetchall()
    if not rows:
        await update.message.reply_text("No inspections submitted today yet. Send /new!")
        return
    lines = [f"📅 <b>Submitted today ({esc(today)}):</b>"]
    for r in rows:
        lines.append(f"• {esc(r['submitted_at'][11:16])} — "
                     f"{esc(r['pump_house'])} · {esc(r['ph_name'])}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ------------------------------------------------------------ admin cmds

async def _require_admin(update, context):
    conn = _conn(context)
    worker = db.get_worker(conn, update.effective_user.id)
    if worker is None or not worker["is_admin"]:
        await update.message.reply_text("Admins only.")
        return None
    return worker


def month_status_text(conn) -> str:
    now = datetime.now(config.TIMEZONE)
    rows = db.submitted_in_month(conn, now.year, now.month)
    covered = {r["pump_house"] for r in rows}
    houses = db.list_pump_houses(conn)
    missing = [h for h in houses if h["code"] not in covered]
    issue_count = sum(
        1 for it in db.items_for_inspections(conn, [r["id"] for r in rows])
        if it["result"] == "issue")
    text = (f"📊 <b>{now.strftime('%B %Y')}</b>\n"
            f"Pump houses inspected: <b>{len(covered)}/{len(houses)}</b>\n"
            f"Issues reported: <b>{issue_count}</b>\n")
    if missing:
        text += "\n<b>Not yet inspected:</b>\n" + "\n".join(
            f"• {esc(h['code'])} · {esc(h['name'])}" for h in missing[:20])
        if len(missing) > 20:
            text += f"\n…and {len(missing) - 20} more"
    else:
        text += "\n🎉 All pump houses covered this month!"
    return text


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _require_admin(update, context) is None:
        return
    await update.message.reply_text(
        month_status_text(_conn(context)), parse_mode=ParseMode.HTML)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _require_admin(update, context) is None:
        return
    conn = _conn(context)
    now = datetime.now(config.TIMEZONE)
    year, month = now.year, now.month
    if context.args:
        try:
            year, month = map(int, context.args[0].split("-"))
        except ValueError:
            await update.message.reply_text("Usage: /report or /report 2026-08")
            return
    await update.message.reply_text("⏳ Generating report…")
    path = reports.monthly_report(conn, year, month)
    with open(path, "rb") as f:
        await update.message.reply_document(
            f, filename=path.name,
            caption=f"📊 BPPM report — {year:04d}-{month:02d}")


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _require_admin(update, context) is None:
        return
    conn = _conn(context)
    rows = conn.execute(
        "SELECT * FROM workers WHERE approved = 0 ORDER BY created_at").fetchall()
    if not rows:
        await update.message.reply_text("No pending registrations.")
        return
    for r in rows:
        await update.message.reply_text(
            f"🆕 {esc(r['name'])} (id <code>{r['telegram_id']}</code>)",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.approval(r["telegram_id"]))


# --------------------------------------------------------- daily digest

async def daily_digest(context: ContextTypes.DEFAULT_TYPE):
    conn = _conn(context)
    await _notify_admins(context, "🌆 <b>Daily digest</b>\n\n" + month_status_text(conn))
