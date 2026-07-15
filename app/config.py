"""Environment-backed application configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings loaded from environment variables."""

    bot_token: str
    owner_user_id: int
    support_username: str = ""
    database_url: str = "sqlite:///data/bot.db"
    free_daily_limit: int = 5
    premium_daily_limit: int = 100
    log_level: str = "INFO"
    request_cooldown_seconds: float = 3.0
    broadcast_delay_seconds: float = 0.08

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> Settings:
        load_dotenv(env_file, override=False)

        token = os.getenv("BOT_TOKEN", "").strip()
        owner_raw = os.getenv("OWNER_USER_ID", "").strip()
        if not token:
            raise ConfigurationError("BOT_TOKEN is required. Copy .env.example to .env.")
        if not owner_raw:
            raise ConfigurationError("OWNER_USER_ID is required and must be numeric.")
        try:
            owner_id = int(owner_raw)
        except ValueError as exc:
            raise ConfigurationError("OWNER_USER_ID must be a positive integer.") from exc
        if owner_id <= 0:
            raise ConfigurationError("OWNER_USER_ID must be a positive integer.")

        free_limit = _positive_int("FREE_DAILY_LIMIT", 5)
        premium_limit = _positive_int("PREMIUM_DAILY_LIMIT", 100)
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        if log_level not in logging.getLevelNamesMapping():
            raise ConfigurationError(f"Unsupported LOG_LEVEL: {log_level}")

        return cls(
            bot_token=token,
            owner_user_id=owner_id,
            support_username=os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@"),
            database_url=os.getenv("DATABASE_URL", "sqlite:///data/bot.db").strip(),
            free_daily_limit=free_limit,
            premium_daily_limit=premium_limit,
            log_level=log_level,
            request_cooldown_seconds=_positive_float("REQUEST_COOLDOWN_SECONDS", 3.0),
            broadcast_delay_seconds=_positive_float("BROADCAST_DELAY_SECONDS", 0.08),
        )

    @property
    def async_database_url(self) -> str:
        if self.database_url.startswith("sqlite+aiosqlite://"):
            return self.database_url
        if self.database_url.startswith("sqlite://"):
            return self.database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        raise ConfigurationError("Version 1 supports only SQLite DATABASE_URL values.")


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero.")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number.") from exc
    if value < 0:
        raise ConfigurationError(f"{name} cannot be negative.")
    return value
