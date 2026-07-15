"""Environment-backed application configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

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
    enable_telegram_stars: bool = False
    enable_paddle: bool = False
    paddle_env: str = "sandbox"
    paddle_api_key: str = ""
    paddle_client_token: str = ""
    paddle_webhook_secret: str = ""
    base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:8000"
    paddle_webhook_tolerance_seconds: int = 5
    api_host: str = "127.0.0.1"
    api_port: int = 8000

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

        paddle_env = os.getenv("PADDLE_ENV", "sandbox").strip().lower()
        if paddle_env not in {"sandbox", "live"}:
            raise ConfigurationError("PADDLE_ENV must be sandbox or live.")
        base_url = _http_url("BASE_URL", "http://localhost:8000", paddle_env)
        frontend_url = _http_url("FRONTEND_URL", base_url, paddle_env)

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
            enable_telegram_stars=_boolean("ENABLE_TELEGRAM_STARS", False),
            enable_paddle=_boolean("ENABLE_PADDLE", False),
            paddle_env=paddle_env,
            paddle_api_key=os.getenv("PADDLE_API_KEY", "").strip(),
            paddle_client_token=os.getenv("PADDLE_CLIENT_TOKEN", "").strip(),
            paddle_webhook_secret=os.getenv("PADDLE_WEBHOOK_SECRET", "").strip(),
            base_url=base_url,
            frontend_url=frontend_url,
            paddle_webhook_tolerance_seconds=_positive_int("PADDLE_WEBHOOK_TOLERANCE_SECONDS", 5),
            api_host=os.getenv("API_HOST", "127.0.0.1").strip(),
            api_port=_positive_int("API_PORT", 8000),
        )

    @property
    def async_database_url(self) -> str:
        if self.database_url.startswith("sqlite+aiosqlite://"):
            return self.database_url
        if self.database_url.startswith("sqlite://"):
            return self.database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        raise ConfigurationError("Version 1 supports only SQLite DATABASE_URL values.")

    @property
    def paddle_api_base_url(self) -> str:
        if self.paddle_env == "sandbox":
            return "https://sandbox-api.paddle.com"
        return "https://api.paddle.com"

    def require_paddle_checkout(self) -> None:
        if not self.enable_paddle:
            raise ConfigurationError("Paddle payments are disabled.")
        if not self.paddle_api_key:
            raise ConfigurationError("PADDLE_API_KEY is required for Paddle checkout.")
        if not self.paddle_client_token:
            raise ConfigurationError("PADDLE_CLIENT_TOKEN is required for Paddle checkout.")

    def require_paddle_webhook(self) -> None:
        if not self.enable_paddle:
            raise ConfigurationError("Paddle payments are disabled.")
        if not self.paddle_webhook_secret:
            raise ConfigurationError("PADDLE_WEBHOOK_SECRET is required for Paddle webhooks.")


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


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false.")


def _http_url(name: str, default: str, paddle_env: str) -> str:
    value = os.getenv(name, default).strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ConfigurationError(f"{name} must be a complete HTTP or HTTPS URL.")
    if paddle_env == "live" and parsed.scheme != "https":
        raise ConfigurationError(f"{name} must use HTTPS when PADDLE_ENV=live.")
    return value
