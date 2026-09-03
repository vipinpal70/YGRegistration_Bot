# Welcome Bot

Telegram onboarding bot for the community.

## Flow

```
/start  →  greeting: "Hi <name>, Curious to join my 5x community ..."
           (steps 1–3 + limited-time note)
        →  [New Joinee]              → "Pick your broker 👇"
        →  [Verify, if under us!]    → opens the verification bot (VERIFICATION_BOT)

     "Pick your broker 👇"
             • Elefin  → its detail screen
             • XM      → its detail screen
             • ‹ Back  → greeting

     broker detail screen:
        "To open an account on <broker> using our referral, click on the button.
         Once done, fill out the 5x community form ..."
             • 🔗 Open <broker> link   (referral URL)
             • 📝 5x community form     (Google Form URL)
             • ‹ Back                  → broker list
```

`GREETING_TEXT` / `BROKER_LIST_TEXT` are plain text (URLs auto-link); the
greeting is personalised with the user's first name. `BROKER_DETAIL` uses
HTML for the bold broker name and "5x community". If `VERIFICATION_BOT` is
unset, the Verify button shows a "not set up yet" alert instead of a link.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then edit .env
```

Fill in `.env`:

| Variable           | Meaning                                                  |
|--------------------|---------------------------------------------------------|
| `BOT_TOKEN`        | Token from [@BotFather](https://t.me/BotFather)        |
| `XM_URL`           | XM referral URL (blank = section + button hidden)      |
| `ELEFIN_URL`       | Elefin referral URL (blank = section + button hidden)  |
| `FORM_URL`         | 5x community Google Form — how users get added         |
| `VERIFICATION_BOT` | Verification bot: `https://t.me/...` URL or `@username` |

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
