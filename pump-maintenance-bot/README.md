# BPPM Bot — Booster Pump Maintenance Telegram Bot

Telegram bot for daily preventive-maintenance data collection across 72 booster
pump houses. Workers tick a smart checklist on their phone; issues (with photos)
are pushed to admins instantly; the monthly Excel work report is generated
automatically. See [DESIGN.md](DESIGN.md) for the full design.

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

python -m bot.main
```

4. Open your bot in Telegram, send `/start`. Admins listed in `ADMIN_IDS` are
   registered automatically; workers send `/start`, type their name, and wait
   for your **Approve** tap.

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
`DB_PATH` (default `bppm.sqlite3` in the project folder), `TIMEZONE`
(default `Asia/Kuching`), `DAILY_DIGEST_HOUR` (default 18).

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

Back up by copying the SQLite file (`bppm.sqlite3`).
