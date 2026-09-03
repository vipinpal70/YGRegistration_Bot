"""Loads and validates configuration from environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _clean(value: str | None) -> str | None:
    """Trim whitespace and turn empty strings into None."""
    value = (value or "").strip()
    return value or None


def _resolve_bot_link(value: str | None) -> str | None:
    """Accept a full URL or a bare @username and return a usable https link."""
    value = _clean(value)
    if not value:
        return None
    if value.startswith(("http://", "https://", "tg://")):
        return value
    return f"https://t.me/{value.lstrip('@')}"


@dataclass(frozen=True)
class Settings:
    bot_token: str
    xm_url: str | None
    elefin_url: str | None
    form_url: str | None
    verification_url: str | None

    @property
    def missing_links(self) -> list[str]:
        pairs = {
            "XM_URL": self.xm_url,
            "ELEFIN_URL": self.elefin_url,
            "FORM_URL": self.form_url,
            "VERIFICATION_BOT": self.verification_url,
        }
        return [name for name, url in pairs.items() if not url]


def load_settings() -> Settings:
    token = _clean(os.getenv("BOT_TOKEN"))
    if not token:
        raise SystemExit(
            "BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )
    return Settings(
        bot_token=token,
        xm_url=_clean(os.getenv("XM_URL")),
        elefin_url=_clean(os.getenv("ELEFIN_URL")),
        form_url=_clean(os.getenv("FORM_URL")),
        verification_url=_resolve_bot_link(os.getenv("VERIFICATION_BOT")),
    )


settings = load_settings()
