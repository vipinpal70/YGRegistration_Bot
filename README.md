# Welcome Bot

Telegram onboarding bot for the community.

## Flow

```
/start  →  greeting: "Hi <name>, Curious to join my 5x community ..."
           (steps 1–3 + limited-time note)
        →  [New Joinee]              → registration (below)
        →  [Verify, if under us!]    → opens the verification bot directly
                                        (VERIFICATION_BOT; no data collected)

     registration (New Joinee tapped):
        "What's your name?"               (‹ Back → greeting, /cancel)
     →  "What's your phone number?"        [📱 Share phone number] or type it
     →  "Pick your broker 👇"
             • ✅ Current Follower  → saves the lead → opens the
                                       verification bot
             • Elefin / XM          → saves the lead → broker detail screen
             • ‹ Back               → greeting

     broker detail screen (Elefin / XM):
        "To open an account on <broker> using our referral, click on the button.
         Once done, fill out the 5x community form ..."
             • 🔗 Open <broker> link   (referral URL)
             • 📝 5x community form     (Google Form URL)
             • ‹ Back                  → broker list
```

`GREETING_TEXT` / `BROKER_LIST_TEXT` are plain text (URLs auto-link); the
greeting is personalised with the user's first name. `BROKER_DETAIL` /
`FOLLOWER_DETAIL` use HTML for bold. If `VERIFICATION_BOT` is unset, every
"open verification" button shows a "not set up yet" alert instead of a link.

Name + phone are collected via a `ConversationHandler` in `bot.py` (states
`ASK_NAME` → `ASK_PHONE`). **Returning users skip this**: tapping "New
Joinee" first looks the user up in MongoDB by Telegram id, and if a lead
already exists, jumps straight to "Pick your broker" instead of re-asking.
As soon as a broker (or "Current Follower") is chosen, the lead is upserted
into MongoDB, **deduplicated by phone number OR Telegram id** — whichever
matches — via unique indexes on a normalized `phone_normalized` field and
on `telegram_id` — see `db.py`. See `flow.md` for the full step-by-step
walkthrough.

You'll see a `PTBUserWarning` about `per_message=False` on startup — that's
expected: the registration conversation mixes a button entry point with
text/contact states, so `per_message=False` (the default) is correct, not a
bug.

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
| `MONGODB_URI`      | MongoDB connection string for storing leads              |
| `MONGODB_DB`       | MongoDB database name (collection used is `leads`)       |

If `MONGODB_URI` / `MONGODB_DB` are left blank, leads are just logged
(`logger.info`) instead of saved — the bot still runs fine.

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
