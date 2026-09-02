# Welcome Bot

Telegram onboarding bot for the community.

## Flow

```
/start  →  greeting: "Hi <name>, Curious to join my 5x community ..."
           (steps 1–3 + limited-time note)
        →  [1. Already under Us]  [2. New Joinee]

     after either choice:  "Pick your broker 👇"
             • Elefin  → its detail screen
             • XM      → its detail screen
             • ‹ Back  → greeting

     broker detail screen:
        "To open an account on <broker> using our referral, click the link: <url>
         Once done, fill out the 5x community form ...: <form url>"
             • 🔗 Open <broker> link   (referral URL)
             • 📝 5x community form     (Google Form URL)
             • ‹ Back                  → broker list
```

Both `/start` choices lead to the same broker list. To make them diverge,
branch in `on_path` in `bot.py`. Texts (`GREETING_TEXT`, `BROKER_DETAIL`) are
plain text — URLs auto-link — and the greeting is personalised with the
user's first name.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then edit .env
```

Fill in `.env`:

| Variable     | Meaning                                                    |
|--------------|-----------------------------------------------------------|
| `BOT_TOKEN`  | Token from [@BotFather](https://t.me/BotFather)          |
| `XM_URL`     | XM referral URL (blank = section + button hidden)        |
| `ELEFIN_URL` | Elefin referral URL (blank = section + button hidden)    |
| `FORM_URL`   | 5x community Google Form — how users get added to the channel |

## Run

```bash
.venv/bin/python bot.py
```

The bot uses long polling — no public URL or webhook needed. Missing link
variables are logged on startup and their buttons are simply omitted.

## Deploy (systemd example)

```ini
# /etc/systemd/system/welcome-bot.service
[Unit]
Description=Telegram Welcome Bot
After=network-online.target

[Service]
WorkingDirectory=/home/vipin/Workspace/welcome-bot
ExecStart=/home/vipin/Workspace/welcome-bot/.venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now welcome-bot
journalctl -u welcome-bot -f
```

## Security

`.env` holds the bot token and is gitignored — never commit it. If a token
is ever exposed, run `/revoke` in @BotFather to invalidate it and get a new
one, then update `.env`.
