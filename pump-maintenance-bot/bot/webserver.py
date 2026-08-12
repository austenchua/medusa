"""Built-in web server for the Telegram Mini App: serves the UI and a JSON API.

Every API request carries the Mini App's initData in the X-Tg-Init-Data
header; it is cryptographically verified against the bot token, so the
worker's identity can't be spoofed.
"""
import logging
import secrets
from datetime import datetime

from aiohttp import web

from . import checklists, config, db, handlers
from .webapp_auth import validate_init_data

log = logging.getLogger(__name__)

MAX_UPLOAD = 20 * 1024 * 1024  # photos from phone cameras


def _auth(request: web.Request) -> dict:
    user = validate_init_data(
        request.headers.get("X-Tg-Init-Data", ""), config.BOT_TOKEN)
    if user is None:
        raise web.HTTPUnauthorized(text="Bad initData")
    return user


def _worker(request: web.Request):
    """Authenticated AND approved worker row (or 403)."""
    user = _auth(request)
    worker = db.get_worker(request.app["conn"], user["id"])
    if worker is None or not worker["approved"]:
        raise web.HTTPForbidden(text="Not an approved worker")
    return worker


# ------------------------------------------------------------------ static

async def index(request):
    return web.FileResponse(config.WEBAPP_DIR / "index.html")


# --------------------------------------------------------------------- api

async def api_me(request):
    user = _auth(request)
    worker = db.get_worker(request.app["conn"], user["id"])
    return web.json_response({
        "telegram_id": user["id"],
        "worker": None if worker is None else {
            "name": worker["name"],
            "approved": bool(worker["approved"]),
            "is_admin": bool(worker["is_admin"]),
        },
    })


async def api_register(request):
    user = _auth(request)
    conn = request.app["conn"]
    body = await request.json()
    name = str(body.get("name", "")).strip()[:100]
    if not name:
        raise web.HTTPBadRequest(text="Name required")
    existing = db.get_worker(conn, user["id"])
    if existing and existing["approved"]:
        return web.json_response({"ok": True, "approved": True})
    is_admin = user["id"] in config.ADMIN_IDS
    db.upsert_worker(conn, user["id"], name, is_admin=is_admin, approved=is_admin)
    if not is_admin:
        app_tg = request.app.get("application")
        if app_tg:
            from . import keyboards
            await handlers.notify_admins(
                app_tg.bot, conn,
                f"🆕 <b>New worker registration (via app)</b>\n"
                f"{handlers.esc(name)} (id <code>{user['id']}</code>)",
                reply_markup=keyboards.approval(user["id"]))
    return web.json_response({"ok": True, "approved": is_admin})


async def api_houses(request):
    worker = _worker(request)
    conn = request.app["conn"]
    now = datetime.now(config.TIMEZONE)
    done = {}
    for insp in db.submitted_in_month(conn, now.year, now.month):
        done[insp["pump_house"]] = insp["submitted_at"][:10]
    houses = [
        {"code": h["code"], "name": h["name"],
         "done": h["code"] in done, "done_date": done.get(h["code"])}
        for h in db.list_pump_houses(conn)
    ]
    return web.json_response({
        "worker": worker["name"],
        "month": now.strftime("%B %Y"),
        "covered": len(done),
        "total": len(houses),
        "houses": houses,
    })


async def api_checklist(request):
    _worker(request)
    conn = request.app["conn"]
    code = request.match_info["code"].upper()
    house = db.get_pump_house(conn, code)
    if house is None:
        raise web.HTTPNotFound(text="Unknown pump house")
    due = checklists.due_items(conn, code)
    by_cat: dict[str, list] = {}
    for cat_key, task_id, freq in due:
        by_cat.setdefault(cat_key, []).append((task_id, freq))
    categories = []
    for cat in checklists.CATEGORIES:
        if cat["key"] not in by_cat:
            continue
        categories.append({
            "key": cat["key"], "name": cat["name"], "emoji": cat["emoji"],
            "tasks": [
                {"id": tid, "freq": freq,
                 "desc": checklists.task_of(cat["key"], tid)["desc"]}
                for tid, freq in by_cat[cat["key"]]
            ],
        })
    return web.json_response({
        "code": house["code"], "name": house["name"],
        "categories": categories,
        "freq_labels": checklists.FREQ_LABELS,
    })


async def api_photo(request):
    _worker(request)
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "photo":
        raise web.HTTPBadRequest(text="Send multipart field 'photo'")
    ext = ".jpg"
    if field.filename and "." in field.filename:
        ext = "." + field.filename.rsplit(".", 1)[1].lower()[:5]
    name = f"{db.now_iso()[:10]}_{secrets.token_hex(8)}{ext}"
    config.PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    size = 0
    with open(config.PHOTO_DIR / name, "wb") as f:
        while chunk := await field.read_chunk():
            size += len(chunk)
            if size > MAX_UPLOAD:
                f.close()
                (config.PHOTO_DIR / name).unlink(missing_ok=True)
                raise web.HTTPRequestEntityTooLarge(
                    max_size=MAX_UPLOAD, actual_size=size)
            f.write(chunk)
    return web.json_response({"photo": f"local:{name}"})


VALID_RESULTS = {"ok", "issue", "skipped"}


async def api_submit(request):
    worker = _worker(request)
    conn = request.app["conn"]
    body = await request.json()
    code = str(body.get("house", "")).upper()
    if db.get_pump_house(conn, code) is None:
        raise web.HTTPBadRequest(text="Unknown pump house")

    due = set()
    freq_of = {}
    for cat_key, task_id, freq in checklists.due_items(conn, code):
        due.add((cat_key, task_id))
        freq_of[(cat_key, task_id)] = freq

    results = body.get("results", [])
    if not results:
        raise web.HTTPBadRequest(text="No results")
    seen = set()
    for r in results:
        key = (r.get("category"), r.get("task_id"))
        if key not in due or key in seen or r.get("result") not in VALID_RESULTS:
            raise web.HTTPBadRequest(text=f"Invalid item {key}")
        seen.add(key)
    if seen != due:
        raise web.HTTPBadRequest(text="Incomplete: answer every due task")

    # Replace any lingering chat-flow draft for this worker.
    old_draft = db.get_draft(conn, worker["telegram_id"])
    if old_draft:
        db.delete_inspection(conn, old_draft["id"])

    insp_id = db.create_inspection(
        conn, code, worker["telegram_id"],
        [(c, t, freq_of[(c, t)]) for (c, t) in due])
    for r in results:
        db.set_item_result(
            conn, insp_id, r["category"], r["task_id"], r["result"],
            note=(str(r.get("note") or "").strip()[:1000] or None),
            photo_file_id=(r.get("photo") or None))
    db.set_inspection_status(conn, insp_id, "submitted")

    items = db.get_items(conn, insp_id)
    issues = [i for i in items if i["result"] == "issue"]
    app_tg = request.app.get("application")
    if issues and app_tg:
        insp = db.get_inspection(conn, insp_id)
        summary, photos = handlers.issue_alert_texts(conn, insp, items)
        await handlers.notify_admins(app_tg.bot, conn, summary)
        for photo_ref, caption in photos:
            await handlers.notify_admins(app_tg.bot, conn, caption,
                                         photo_file_id=photo_ref)

    return web.json_response({
        "ok": True, "inspection_id": insp_id,
        "counts": {
            "ok": sum(1 for i in items if i["result"] == "ok"),
            "issue": len(issues),
            "skipped": sum(1 for i in items if i["result"] == "skipped"),
        },
    })


# ------------------------------------------------------------------- wiring

def build_app(application=None) -> web.Application:
    app = web.Application(client_max_size=MAX_UPLOAD + 1024)
    app["conn"] = db.connect()
    app["application"] = application
    app.router.add_get("/", index)
    app.router.add_get("/api/me", api_me)
    app.router.add_post("/api/register", api_register)
    app.router.add_get("/api/houses", api_houses)
    app.router.add_get("/api/checklist/{code}", api_checklist)
    app.router.add_post("/api/photo", api_photo)
    app.router.add_post("/api/submit", api_submit)
    app.router.add_static("/static", config.WEBAPP_DIR)
    return app


async def start(application) -> None:
    """Run the web server inside the bot's event loop (called from post_init)."""
    runner = web.AppRunner(build_app(application))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.WEBAPP_PORT)
    await site.start()
    log.info("Mini App server on port %s (public URL: %s)",
             config.WEBAPP_PORT, config.WEBAPP_URL or "not set")
