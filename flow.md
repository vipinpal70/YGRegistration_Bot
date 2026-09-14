# Bot Flow

Step-by-step walkthrough of `bot.py`, in the order a user actually experiences it.
Function and callback-data names are the real ones in the code, so you can jump
straight to the source for any step.

## 1. `/start` — the greeting

Handler: `start()`

The user sends `/start`. The bot replies with `GREETING_TEXT`, personalised
with their Telegram first name (falls back to `@username`, then "there"):

> Hi Yash,
>
> Curious to join my 5x community at just a deposit of $100? 🧐
>
> The steps are simple: ⤵️
>
> 1. Open an account on Elefin or XM!
>
> 2. Deposit $100 in case of Elefin & $500 in case of XM and then take a trade 💰
>
> 3. Fill out the 5x community form to get added to the channel 📝
>
> ⚠️ Offer is valid only for a limited time. 🕘

Two buttons, built by `choice_keyboard()`:

| Button | callback_data / url | Goes to |
|---|---|---|
| **New Joinee** | `path:new` | Step 2 — starts registration |
| **Verify, if under us!** | URL → `VERIFICATION_BOT` (or `verify:missing` if that env var is blank) | Opens the verification bot directly. **No name/phone is collected on this path** — it's an instant link out, unchanged from before this feature existed. |

## 2. Tap "New Joinee" — registration starts

Handler: `start_registration()` (the **entry point** of `registration_conv`, a `ConversationHandler`)

- Clears any `lead_name` / `lead_phone` left over from a previous attempt (`context.user_data`).
- Edits the greeting message to: **"Great! Let's get you set up.\n\nWhat's your name?"**
- Shows one button: **‹ Back** (`reg:cancel`) — bails out to step 1.
- Conversation state becomes `ASK_NAME`.

From here the bot is waiting for a **typed reply**, not a button tap.

## 3. User types their name

Handler: `receive_name()` (runs while state = `ASK_NAME`)

- Any non-empty text message is accepted as the name and stored in `context.user_data["lead_name"]`.
- If the message isn't usable text, it re-asks and stays in `ASK_NAME`.
- On success, replies:
  > Thanks, {name}! Now share your phone number using the button below, or type it.
  >
  > (/cancel to go back)
- Shows a **reply keyboard** (not inline) with one button: **📱 Share phone number** — a Telegram "share contact" button, which sends the user's real phone number with one tap.
- Conversation state becomes `ASK_PHONE`.

## 4. User provides their phone number

Handler: `receive_phone()` (runs while state = `ASK_PHONE`)

Accepts **either**:
- Tapping "📱 Share phone number" → reads `message.contact.phone_number`, or
- Typing the number as text.

Validation: the value must contain at least 7 digit characters, otherwise it
re-prompts and stays in `ASK_PHONE`.

On success:
- Stores it in `context.user_data["lead_phone"]`.
- Sends "Got it, thanks!" and removes the reply keyboard (`ReplyKeyboardRemove`).
- Sends `BROKER_LIST_TEXT` ("Pick your broker 👇") with the broker-choice buttons (step 5).
- Conversation **ends** (`ConversationHandler.END`) — from here on the bot is back to normal button-driven handling, no longer "mid-conversation".

At this point the bot has **name + phone** for this user, held in `context.user_data` for the rest of the chat session (not written to the database yet).

## 5. "Pick your broker 👇"

Keyboard: `broker_list_keyboard()`. Three choices, all routed through the single handler **`on_broker()`**:

| Button | callback_data |
|---|---|
| ✅ **Current Follower** | `broker:follower` |
| **Elefin** | `broker:elefin` |
| **XM** | `broker:xm` |
| ‹ Back | `nav:start` → back to the greeting (step 1) |

(Elefin/XM buttons only appear if `ELEFIN_URL` / `XM_URL` are set in `.env`.)

## 6. Whichever broker is tapped — `on_broker()`

This is the one place everything converges:

1. **Save the lead.** If both `lead_name` and `lead_phone` are present in
   `context.user_data`, calls `save_lead(telegram_id, telegram_username, name,
   phone, broker)` (see `db.py` → MongoDB, step 7 below). If either is
   missing (e.g. someone reached this screen without going through
   registration), it skips the save and just logs a warning — never crashes.
2. **Branch on which broker was chosen:**
   - `broker:follower` → `show_follower_detail()`:
     > Thanks, **{name}**! Since you're already one of our followers, tap below to complete verification.

     Button: **🔗 Open verification bot** (URL → `VERIFICATION_BOT`, or a
     "not set up yet" alert if unset) + **‹ Back** (`nav:brokers` → step 5).
   - `broker:elefin` / `broker:xm` → `show_broker_detail()`:
     > To open an account on **{broker}** using our referral, click on the button.
     >
     > Once done, fill out the **5x community** form to get added in the channel.

     Buttons: **🔗 Open {broker} link** (referral URL) + **📝 5x community
     form** (`FORM_URL`, if set) + **‹ Back** (`nav:brokers` → step 5).

## 7. Where the lead ends up — MongoDB

`db.py` → `save_lead()`. One document **per phone number**, upserted into
the `leads` collection of `MONGODB_DB`:

```json
{
  "phone_normalized": "919876543210",  // digits-only dedup key (not shown, but this is the _document identity_)
  "telegram_id": 123456789,
  "telegram_username": "rohan_v",
  "name": "Rohan Verma",
  "phone": "+91 98765 43210",          // as typed/shared, kept for display
  "broker": "xm",                      // "follower" | "elefin" | "xm"
  "created_at": "...",                 // set once, on first insert
  "updated_at": "..."                  // refreshed on every save
}
```

**Deduplication is by phone number, not by Telegram account.** The number
is normalized to digits-only (`_normalize_phone()` strips everything but
digits, so `"+91 98765-43210"` and `"919876543210"` resolve to the same
key) and that key carries a **unique index** in MongoDB — so even a second
Telegram account submitting the same number updates the one existing
document instead of creating a duplicate. This was verified against a real
MongoDB instance: two different `telegram_id`s with the same phone (in
different formats) collapsed to one document; a genuinely different phone
number correctly created a second one; and a direct insert bypassing
`save_lead()` was rejected by the index itself (`DuplicateKeyError`).

The index is created lazily (`_ensure_indexes()`, on the first save of a
process) rather than at import time, since index creation is an async
MongoDB call. If the collection already has duplicate phone numbers from
*before* this dedup logic existed, index creation will fail (logged, not
fatal) until that old data is cleaned up.

If `MONGODB_URI`/`MONGODB_DB` are blank, or a write fails for any reason,
the lead is just logged and the chat continues normally; a database problem
never blocks or crashes the bot.

## Getting unstuck / edge cases

- **`/cancel`** at any point during registration → ends it, keeps whatever
  was typed so far out of `context.user_data`, tells the user to `/start`
  again when ready.
- **`/start`** during registration → restarts cleanly (clears any partial
  name/phone, re-shows the greeting) instead of leaving the conversation
  half-open.
- **‹ Back** on the "What's your name?" screen (`reg:cancel`) → same clean
  exit back to the greeting.
- **A stale button tap** (from a message sent before the bot's last
  restart) never crashes the bot: `_ack()` swallows Telegram's "query is too
  old" error, and `on_error` silences it globally too.
- **Registration is not remembered** between attempts or restarts — every
  "New Joinee" tap starts the name/phone questions over from scratch.

## Config that drives this flow (`.env`)

| Variable | Used for |
|---|---|
| `BOT_TOKEN` | Talking to Telegram at all |
| `XM_URL`, `ELEFIN_URL` | The two broker referral buttons (step 5/6) |
| `FORM_URL` | The "5x community form" button (step 6) |
| `VERIFICATION_BOT` | Both "Verify, if under us!" (step 1) and "Open verification bot" (step 6, Current Follower) |
| `MONGODB_URI`, `MONGODB_DB` | Lead storage (step 7); collection name `leads` is hardcoded in `db.py` |
