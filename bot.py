"""Welcome / onboarding bot.

Flow:
    /start
        -> greeting: the "Hi <name> ..." offer message
           + button [New Joinee]  -> asks for name, then phone number,
                                      then "Pick your broker"
                                      [Current Follower] [Elefin] [XM]
           + button [Verify, if under us!]  -> opens the verification bot
                                                directly (no data collected)
        -> Current Follower  -> saves the lead, opens the verification bot
        -> Elefin / XM       -> saves the lead, shows the referral link
                                 + the 5x community form
"""

from __future__ import annotations

import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LinkPreviewOptions,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import settings
from db import check_connection, save_lead

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("welcome-bot")

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# --- Callback data -----------------------------------------------------------
PATH_NEW = "path:new"
REG_CANCEL = "reg:cancel"           # "‹ Back" while registering (name step)
VERIFY_MISSING = "verify:missing"   # fallback when VERIFICATION_BOT is unset
BROKER_FOLLOWER = "broker:follower"
BROKER_ELEFIN = "broker:elefin"
BROKER_XM = "broker:xm"
NAV_START = "nav:start"       # back to the welcome screen
NAV_BROKERS = "nav:brokers"   # back to the broker list

# --- Registration conversation states ---------------------------------------
ASK_NAME, ASK_PHONE = range(2)
PHONE_BUTTON_TEXT = "📱 Share phone number"

# --- Copy ------------------------------------------------------------------
# Plain text (no parse mode), so the "&" in the copy needs no escaping.
GREETING_TEXT = (
    "Hi {name},\n\n"
    "Curious to join my 5x community at just a deposit of $100? 🧐\n\n"
    "The steps are simple: ⤵️\n\n"
    "1. Open an account on Elefin or XM!\n\n"
    "2. Deposit $100 in case of Elefin & $500 in case of XM and then take a "
    "trade 💰\n\n"
    "3. Fill out the 5x community form to get added to the channel 📝\n\n"
    "⚠️ Offer is valid only for a limited time. 🕘"
)

BROKER_LIST_TEXT = "Pick your broker 👇"

BROKER_DETAIL = (
    "To open an account on <b>{broker}</b> using our referral, click on the "
    "button.\n\n"
    "Once done, fill out the <b>5x community</b> form to get added in the "
    "channel.\n"
)

FOLLOWER_DETAIL = (
    "Thanks, <b>{name}</b>! Since you're already one of our followers, tap "
    "below to complete verification.\n"
)

# callback data -> (display name, referral url)
BROKERS: dict[str, tuple[str, str | None]] = {
    BROKER_ELEFIN: ("Elefin", settings.elefin_url),
    BROKER_XM: ("XM", settings.xm_url),
}


# --- Keyboards -------------------------------------------------------------
def choice_keyboard() -> InlineKeyboardMarkup:
    if settings.verification_url:
        verify_btn = InlineKeyboardButton(
            "Verify, if under us!", url=settings.verification_url
        )
    else:
        verify_btn = InlineKeyboardButton(
            "Verify, if under us!", callback_data=VERIFY_MISSING
        )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("New Joinee", callback_data=PATH_NEW)],
            [verify_btn],
        ]
    )


def ask_name_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("‹ Back", callback_data=REG_CANCEL)]]
    )


def phone_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(PHONE_BUTTON_TEXT, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def broker_list_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("✅ Current Follower", callback_data=BROKER_FOLLOWER)]]
    rows += [
        [InlineKeyboardButton(name, callback_data=cb)]
        for cb, (name, url) in BROKERS.items()
        if url
    ]
    rows.append([InlineKeyboardButton("‹ Back", callback_data=NAV_START)])
    return InlineKeyboardMarkup(rows)


def broker_detail_keyboard(broker_name: str, url: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"🔗 Open {broker_name} link", url=url)]]
    if settings.form_url:
        rows.append(
            [InlineKeyboardButton("📝 5x community form", url=settings.form_url)]
        )
    rows.append([InlineKeyboardButton("‹ Back", callback_data=NAV_BROKERS)])
    return InlineKeyboardMarkup(rows)


def follower_detail_keyboard() -> InlineKeyboardMarkup:
    if settings.verification_url:
        verify_row = [
            InlineKeyboardButton("🔗 Open verification bot", url=settings.verification_url)
        ]
    else:
        verify_row = [
            InlineKeyboardButton("🔗 Open verification bot", callback_data=VERIFY_MISSING)
        ]
    return InlineKeyboardMarkup([verify_row, [InlineKeyboardButton("‹ Back", callback_data=NAV_BROKERS)]])


# --- Rendering -----------------------------------------------------------
def _display_name(user) -> str:
    return user.first_name or user.username or "there"


def _ud(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """`context.user_data` is a dict for every real update; this just gives
    the type checker that guarantee without an assert in every handler."""
    assert context.user_data is not None
    return context.user_data


async def _safe_edit(
    query,
    text: str,
    keyboard: InlineKeyboardMarkup,
    parse_mode: str | None = None,
) -> None:
    """Edit a message, ignoring Telegram's 'message is not modified' error."""
    try:
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=parse_mode,
            link_preview_options=NO_PREVIEW,
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


async def _ack(query, text: str | None = None, show_alert: bool = False) -> None:
    """Answer a callback query, ignoring it when Telegram considers it stale.

    Happens when a user taps a button on a message from before the last
    restart: the query id has expired by the time we process it.
    """
    try:
        await query.answer(text=text, show_alert=show_alert)
    except BadRequest as exc:
        logger.debug("Ignoring stale callback answer: %s", exc)


async def show_welcome(query) -> None:
    text = GREETING_TEXT.format(name=_display_name(query.from_user))
    await _safe_edit(query, text, choice_keyboard())


async def show_broker_list(query) -> None:
    await _safe_edit(query, BROKER_LIST_TEXT, broker_list_keyboard())


async def show_broker_detail(query, cb: str) -> None:
    broker_name, url = BROKERS[cb]
    if not url:
        await _ack(query, "That link isn't available right now.", show_alert=True)
        return
    text = BROKER_DETAIL.format(broker=broker_name)
    await _safe_edit(
        query,
        text,
        broker_detail_keyboard(broker_name, url),
        parse_mode=ParseMode.HTML,
    )


async def show_follower_detail(query, name: str) -> None:
    text = FOLLOWER_DETAIL.format(name=name)
    await _safe_edit(query, text, follower_detail_keyboard(), parse_mode=ParseMode.HTML)


# --- Registration conversation (name -> phone -> broker choice) ----------
async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await _ack(query)
    logger.info("User %s (%s) started registration", query.from_user.id, query.from_user.username)

    _ud(context).pop("lead_name", None)
    _ud(context).pop("lead_phone", None)
    await _safe_edit(
        query,
        "Great! Let's get you set up.\n\nWhat's your name?",
        ask_name_keyboard(),
    )
    return ASK_NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    if message is None or not message.text or not message.text.strip():
        if message is not None:
            await message.reply_text("Please type your name as text.")
        return ASK_NAME

    name = message.text.strip()
    _ud(context)["lead_name"] = name
    await message.reply_text(
        f"Thanks, {name}! Now share your phone number using the button below, "
        "or type it.\n\n(/cancel to go back)",
        reply_markup=phone_request_keyboard(),
    )
    return ASK_PHONE


async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    if message is None:
        return ASK_PHONE

    if message.contact is not None:
        phone = message.contact.phone_number
    else:
        phone = (message.text or "").strip()

    digits = sum(ch.isdigit() for ch in phone)
    if digits < 7:
        await message.reply_text(
            "That doesn't look like a valid phone number — please try again, "
            "or tap the button to share it.",
            reply_markup=phone_request_keyboard(),
        )
        return ASK_PHONE

    _ud(context)["lead_phone"] = phone
    await message.reply_text("Got it, thanks!", reply_markup=ReplyKeyboardRemove())
    await message.reply_text(BROKER_LIST_TEXT, reply_markup=broker_list_keyboard())
    return ConversationHandler.END


async def cancel_registration_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await _ack(query)
    _ud(context).pop("lead_name", None)
    _ud(context).pop("lead_phone", None)
    await show_welcome(query)
    return ConversationHandler.END


async def cancel_registration_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _ud(context).pop("lead_name", None)
    _ud(context).pop("lead_phone", None)
    if update.message is not None:
        await update.message.reply_text(
            "No problem — send /start whenever you're ready.",
            reply_markup=ReplyKeyboardRemove(),
        )
    return ConversationHandler.END


async def restart_from_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _ud(context).pop("lead_name", None)
    _ud(context).pop("lead_phone", None)
    if update.message is not None:
        await update.message.reply_text("Starting over.", reply_markup=ReplyKeyboardRemove())
        await start(update, context)
    return ConversationHandler.END


# --- Handlers ------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        GREETING_TEXT.format(name=_display_name(update.effective_user)),
        reply_markup=choice_keyboard(),
        link_preview_options=NO_PREVIEW,
    )


async def on_broker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await _ack(query)

    name = _ud(context).get("lead_name")
    phone = _ud(context).get("lead_phone")
    broker_key = query.data.split(":", 1)[1]  # "follower" | "elefin" | "xm"

    if name and phone:
        await save_lead(
            telegram_id=query.from_user.id,
            telegram_username=query.from_user.username,
            name=name,
            phone=phone,
            broker=broker_key,
        )
    else:
        logger.warning(
            "Broker choice %s without a captured lead (user %s) — not saved",
            query.data,
            query.from_user.id,
        )

    if query.data == BROKER_FOLLOWER:
        await show_follower_detail(query, name or _display_name(query.from_user))
    else:
        await show_broker_detail(query, query.data)


async def on_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await _ack(query)
    if query.data == NAV_START:
        await show_welcome(query)
    else:
        await show_broker_list(query)


async def on_verify_missing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await _ack(
        query,
        "Verification isn't set up yet — please contact an admin.",
        show_alert=True,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text("Send /start to see the welcome menu again.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, BadRequest) and "query is too old" in str(err).lower():
        return  # stale button tap from before a restart; nothing to do
    logger.error("Error while handling an update: %s", err, exc_info=err)


async def post_init(app: Application) -> None:
    # Runs once, right after the bot starts. Pings MongoDB immediately so a
    # bad MONGODB_URI / network / auth issue is obvious in the log at
    # startup, instead of only surfacing later as an unexplained "lead not
    # saved".
    await check_connection()


# --- Entry point --------------------------------------------------------
def main() -> None:
    if settings.missing_links:
        logger.warning(
            "Not set in .env (related buttons hidden or disabled): %s",
            ", ".join(settings.missing_links),
        )

    app = Application.builder().token(settings.bot_token).post_init(post_init).build()

    # PTB warns at startup: "If 'per_message=False', 'CallbackQueryHandler'
    # will not be tracked for every message." That's expected here and
    # harmless: per_message=True is only for conversations where EVERY
    # state is purely inline-button-driven. This one mixes a button entry
    # point with text/contact states (name, phone), so per_message=False
    # (the default) is the correct setting, not a bug.
    registration_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_registration, pattern=rf"^{PATH_NEW}$")],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            ASK_PHONE: [
                MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), receive_phone)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_registration_button, pattern=rf"^{REG_CANCEL}$"),
            CommandHandler("cancel", cancel_registration_command),
            CommandHandler("start", restart_from_start),
        ],
        conversation_timeout=1800,
    )

    # Registered first so its fallbacks (Back / /cancel / /start) get first
    # refusal while a user is mid-registration; it yields (returns no match)
    # for anything else, which then reaches the handlers below as normal.
    app.add_handler(registration_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(on_verify_missing, pattern=rf"^{VERIFY_MISSING}$"))
    app.add_handler(CallbackQueryHandler(on_broker, pattern=r"^broker:"))
    app.add_handler(CallbackQueryHandler(on_nav, pattern=r"^nav:"))
    app.add_error_handler(on_error)

    logger.info("Bot starting (polling)…")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
