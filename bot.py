"""Welcome / onboarding bot.

Flow:
    /start
        -> greeting: the "Hi <name> ..." offer message
           + buttons [1. Already under Us] [2. New Joinee]
        -> "Pick your broker" + buttons [Elefin] [XM]
        -> tapping a broker shows ITS referral link + the 5x community form,
           with an "Open link" button and a Back button.
"""

from __future__ import annotations

import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import settings

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("welcome-bot")

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# --- Callback data -----------------------------------------------------------
PATH_ALREADY = "path:already"
PATH_NEW = "path:new"
BROKER_ELEFIN = "broker:elefin"
BROKER_XM = "broker:xm"
NAV_START = "nav:start"       # back to the welcome screen
NAV_BROKERS = "nav:brokers"   # back to the broker list

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

# callback data -> (display name, referral url)
BROKERS: dict[str, tuple[str, str | None]] = {
    BROKER_ELEFIN: ("Elefin", settings.elefin_url),
    BROKER_XM: ("XM", settings.xm_url),
}


# --- Keyboards -------------------------------------------------------------
def choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("1. Already under Us", callback_data=PATH_ALREADY)],
            [InlineKeyboardButton("2. New Joinee", callback_data=PATH_NEW)],
        ]
    )


def broker_list_keyboard() -> InlineKeyboardMarkup:
    rows = [
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


# --- Rendering -----------------------------------------------------------
def _display_name(user) -> str:
    return user.first_name or user.username or "there"


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


# --- Handlers ------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        GREETING_TEXT.format(name=_display_name(update.effective_user)),
        reply_markup=choice_keyboard(),
        link_preview_options=NO_PREVIEW,
    )


async def on_path(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await _ack(query)
    logger.info(
        "User %s (%s) chose %s",
        query.from_user.id,
        query.from_user.username,
        query.data,
    )
    await show_broker_list(query)


async def on_broker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await _ack(query)
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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text("Send /start to see the welcome menu again.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, BadRequest) and "query is too old" in str(err).lower():
        return  # stale button tap from before a restart; nothing to do
    logger.error("Error while handling an update: %s", err, exc_info=err)


# --- Entry point --------------------------------------------------------
def main() -> None:
    if settings.missing_links:
        logger.warning(
            "These links are not set in .env, related buttons are hidden: %s",
            ", ".join(settings.missing_links),
        )

    app = Application.builder().token(settings.bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(on_path, pattern=r"^path:"))
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
