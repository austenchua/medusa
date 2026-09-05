# BPPM — Booster Pump Maintenance Telegram Mini App

Telegram Mini App (+ bot) for daily preventive-maintenance data collection
across 72 booster pump houses. Workers open a real app UI inside Telegram —
searchable pump house list, tappable checklist, camera photos for defects.
Issues are pushed to admins instantly; the monthly Excel work report is
generated automatically. See [DESIGN.md](DESIGN.md) for the full design.

## Quick start

1. **Create the bot**: message [@BotFather](https://t.me/BotFather) → `/newbot`
   → copy the token.
2. **Find your admin ID**: message [@userinfobot](https://t.me/userinfobot) —
   it replies with your numeric Telegram ID.
3. **Run it** (Python 3.11+):

```bash
cd pump-maintenance-bot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export BOT_TOKEN="123456:ABC..."     # from BotFather
export ADMIN_IDS="11111111"          # your Telegram ID(s), comma-separated

# Mini App UI (recommended): public HTTPS URL that reaches this machine's
# port 8080 — see "Exposing the Mini App" below. Omit to run chat-only.
export WEBAPP_URL="https://your-domain.example"

python -m bot.main
```

4. Open your bot in Telegram, send `/start`, and tap **📱 Open BPPM App**
   (also available from the bot's menu button). Admins listed in `ADMIN_IDS`
   are registered automatically; workers register with their name in the app
   and wait for your **Approve** tap.

## Exposing the Mini App

Telegram requires Mini Apps to be served over **HTTPS**. The bot has a
built-in web server on `WEBAPP_PORT` (default 8080); put any HTTPS front in
front of it:

- **Cloudflare Tunnel** (free, no public IP):
  `cloudflared tunnel --url http://localhost:8080` — use the printed
  `https://…trycloudflare.com` URL as `WEBAPP_URL` for testing, or a named
  tunnel + your domain for production.
- **Caddy / nginx + Let's Encrypt** on a VPS, proxying to `localhost:8080`.
- **ngrok** for quick trials: `ngrok http 8080`.

If `WEBAPP_URL` is not set, the bot still provides the full checklist flow in
chat (inline buttons), so nothing blocks field work.

## Commands

| Command | Who | What |
|---|---|---|
| `/start` | everyone | register / show menu |
| `/new` | worker | start (or resume) a pump-house inspection |
| `/today` | worker | inspections submitted today |
| `/help` | worker | short field guide |
| `/status` | admin | month coverage (x/72) + stations not yet visited |
| `/report [YYYY-MM]` | admin | Excel work report for the month |
| `/pending` | admin | approve waiting worker registrations |

## Configuration

Environment variables (see `.env.example`): `BOT_TOKEN`, `ADMIN_IDS`,
`WEBAPP_URL`, `WEBAPP_PORT` (default 8080 when `WEBAPP_URL` is set),
`PHOTO_DIR` (default `photos/`), `DB_PATH` (default `bppm.sqlite3` in the
project folder), `TIMEZONE` (default `Asia/Kuching`), `DAILY_DIGEST_HOUR`
(default 18).

## Editing the checklist / pump houses

- `data/checklists.json` — categories, tasks, frequencies (`M`, `3M`, `6M`, `Y`)
- `data/pump_houses.json` — station codes and names

Restart the bot after editing. Existing recorded data is unaffected.

## Running in production

Any always-on machine works (the bot uses long polling — no public IP needed).
Example systemd unit:

```ini
[Unit]
Description=BPPM Telegram bot
After=network-online.target

[Service]
WorkingDirectory=/opt/pump-maintenance-bot
Environment=BOT_TOKEN=... ADMIN_IDS=...
ExecStart=/opt/pump-maintenance-bot/venv/bin/python -m bot.main
Restart=always

[Install]
WantedBy=multi-user.target
```

Back up by copying the SQLite file (`bppm.sqlite3`) and the `photos/` folder.
