"""Lead storage in MongoDB (name, phone, chosen broker).

Leads are deduplicated by EITHER phone number or Telegram id: submitting
the same number again (even from a different Telegram account), or the
same Telegram account again (even with a different typed number), updates
the existing document instead of creating a new one. Unique indexes on
both `phone_normalized` and `telegram_id` make that a hard database-level
guarantee, not just application logic.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError

from config import settings

logger = logging.getLogger("welcome-bot.db")

LEADS_COLLECTION = "leads"

_collection: Any = None
_indexes_ready = False

if settings.mongodb_uri and settings.mongodb_db:
    try:
        _client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)
        _collection = _client[settings.mongodb_db][LEADS_COLLECTION]
    except PyMongoError:
        logger.exception("Could not set up the MongoDB client from MONGODB_URI")
else:
    logger.warning(
        "MONGODB_URI / MONGODB_DB not set in .env — leads will be logged only, "
        "not saved to a database."
    )


def _normalize_phone(phone: str) -> str:
    """Digits-only form used as the dedup key, so '+91 98765-43210' and
    '919876543210' are treated as the same phone number."""
    return re.sub(r"\D", "", phone)


async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready or _collection is None:
        return
    try:
        await _collection.create_index("phone_normalized", unique=True)
        await _collection.create_index("telegram_id", unique=True)
    except PyMongoError:
        # Most likely cause: pre-existing documents already share a phone
        # number or telegram_id, so a unique index can't be built until
        # those are cleaned up. Saving still works, just without the hard
        # DB-level guarantee until that's resolved.
        logger.exception("Could not create unique indexes on the leads collection")
    finally:
        _indexes_ready = True


async def get_lead_by_telegram_id(telegram_id: int) -> dict[str, Any] | None:
    """Look up a previously saved lead so a returning user doesn't have to
    retype their name/phone. Returns None on any failure (never raises)."""
    if _collection is None:
        return None
    try:
        return await _collection.find_one({"telegram_id": telegram_id})
    except PyMongoError:
        logger.exception("Failed to look up lead for telegram_id=%s", telegram_id)
        return None


async def check_connection() -> bool:
    """Ping MongoDB and log a clear, unmissable result. Call this once at
    bot startup (see bot.py's post_init) so a bad connection string,
    network issue, or auth/IP-allowlist problem shows up immediately in
    the log — instead of only surfacing later as a silent "lead not
    saved" with no obvious cause.
    """
    if _collection is None:
        logger.warning(
            "MongoDB check: NOT CONFIGURED (MONGODB_URI/MONGODB_DB blank in "
            ".env) — leads will only be logged, never saved."
        )
        return False
    try:
        await _collection.database.client.admin.command("ping")
    except PyMongoError:
        logger.exception(
            "MongoDB check: PING FAILED for db=%s collection=%s — leads will "
            "NOT be saved until this is fixed. Check MONGODB_URI (host, "
            "username/password, IP allowlist) and MONGODB_DB.",
            settings.mongodb_db,
            LEADS_COLLECTION,
        )
        return False
    logger.info(
        "MongoDB check: connected OK — db=%s collection=%s",
        settings.mongodb_db,
        LEADS_COLLECTION,
    )
    return True


async def save_lead(
    *,
    telegram_id: int,
    telegram_username: str | None,
    name: str,
    phone: str,
    broker: str,
) -> None:
    """Upsert a lead, deduplicated by phone number OR Telegram id — whichever
    matches an existing document. Never raises — a DB outage or a
    duplicate-key race must not block the chat flow."""
    if _collection is None:
        logger.info(
            "Lead (not saved, no DB configured): id=%s name=%r phone=%r broker=%s",
            telegram_id,
            name,
            phone,
            broker,
        )
        return

    phone_key = _normalize_phone(phone)
    if not phone_key:
        logger.warning(
            "Lead for telegram_id=%s has no usable digits in phone %r — not saved",
            telegram_id,
            phone,
        )
        return

    await _ensure_indexes()

    now = datetime.now(timezone.utc)
    try:
        # The filter is an $or, so — unlike a plain equality filter — Mongo
        # won't auto-populate phone_normalized/telegram_id on insert; both
        # must be explicit in $set.
        result = await _collection.update_one(
            {"$or": [{"telegram_id": telegram_id}, {"phone_normalized": phone_key}]},
            {
                "$set": {
                    "telegram_id": telegram_id,
                    "telegram_username": telegram_username,
                    "name": name,
                    "phone": phone,
                    "phone_normalized": phone_key,
                    "broker": broker,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    except PyMongoError:
        # Can happen if this telegram_id and this phone number each already
        # belong to two DIFFERENT existing documents (a genuine conflict) —
        # updating one to match both would violate a unique index. Logged
        # and dropped rather than guessing which record should "win".
        logger.exception(
            "Failed to save lead (phone=%s, telegram_id=%s) to MongoDB",
            phone_key,
            telegram_id,
        )
        return

    action = "inserted new" if result.upserted_id is not None else "updated existing"
    logger.info(
        "Lead saved (%s document): phone=%s broker=%s telegram_id=%s",
        action,
        phone_key,
        broker,
        telegram_id,
    )
