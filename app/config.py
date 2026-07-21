"""Environment-backed application configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

DEFAULT_BROADCAST_HEADER = (
    "📢 <b>BROADCAST</b>\n\n"
    "Instagram Me Reels Dalkar Paise Kamao ✅ Earn Weekly ₹10,000 💰\n"
    "DM: @RolexWorkZ_01"
)


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings loaded from environment variables."""

    bot_token: str
    admin_user_id: int
    source_channel_id: int | None
    bot_username: str = ""
    admin_username: str = ""
    source_channel_username: str = ""
    post_delay_minutes: int = 0
    diskwala_api_base_url: str = ""
    diskwala_api_endpoint: str = ""
    diskwala_api_key: str = ""
    diskwala_api_auth_header: str = "Authorization"
    diskwala_api_auth_scheme: str = "Bearer"
    diskwala_api_request_field: str = "url"
    diskwala_api_response_field: str = ""
    diskwala_allowed_hosts: tuple[str, ...] = ("diskwala.com", "www.diskwala.com")
    database_url: str = "sqlite:///data/bot.db"
    broadcast_rate_per_second: int = 25
    broadcast_header: str = DEFAULT_BROADCAST_HEADER
    allow_paid_broadcast: bool = False
    app_mode: str = "polling"
    webhook_url: str = ""
    webhook_secret: str = ""
    log_level: str = "INFO"
    diskwala_timeout_seconds: float = 10.0
    diskwala_max_attempts: int = 3
    telegram_api_id: int | None = None
    telegram_api_hash: str = ""
    telegram_phone: str = ""
    telethon_session_name: str = ""
    diskwala_converter_bot: str = "DW2DW_LinkConverterBot"
    diskwala_converter_timeout_seconds: int = 60

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> Settings:
        load_dotenv(env_file, override=False)

        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise ConfigurationError("BOT_TOKEN is required. Copy .env.example to .env.")

        admin_raw = os.getenv("ADMIN_USER_ID", "").strip()
        owner_raw = os.getenv("OWNER_USER_ID", "").strip()
        if not admin_raw and owner_raw:
            logging.getLogger(__name__).warning(
                "OWNER_USER_ID is deprecated; use ADMIN_USER_ID instead."
            )
            admin_raw = owner_raw
        admin_user_id = _optional_int("ADMIN_USER_ID", admin_raw)
        if admin_user_id is None or admin_user_id <= 0:
            raise ConfigurationError("ADMIN_USER_ID is required and must be a positive integer.")

        source_raw = os.getenv("SOURCE_CHANNEL_ID", "").strip()
        source_channel_id = _optional_int("SOURCE_CHANNEL_ID", source_raw)
        if source_channel_id == 0:
            raise ConfigurationError("SOURCE_CHANNEL_ID must be a non-zero numeric channel ID.")

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        if log_level not in logging.getLevelNamesMapping():
            raise ConfigurationError(f"Unsupported LOG_LEVEL: {log_level}")

        allowed_hosts = tuple(
            dict.fromkeys(
                host.strip().lower().rstrip(".")
                for host in os.getenv(
                    "DISKWALA_ALLOWED_HOSTS", "diskwala.com,www.diskwala.com"
                ).split(",")
                if host.strip()
            )
        )
        if not allowed_hosts:
            raise ConfigurationError("DISKWALA_ALLOWED_HOSTS must contain at least one host.")

        app_mode = os.getenv("APP_MODE", "polling").strip().lower()
        if app_mode not in {"polling", "webhook"}:
            raise ConfigurationError("APP_MODE must be polling or webhook.")
        webhook_url = os.getenv("WEBHOOK_URL", "").strip()
        webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
        if app_mode == "webhook":
            _validate_http_url("WEBHOOK_URL", webhook_url, require_https=True)
            if not webhook_secret:
                raise ConfigurationError("WEBHOOK_SECRET is required when APP_MODE=webhook.")

        base_url = os.getenv("DISKWALA_API_BASE_URL", "").strip().rstrip("/")
        endpoint = os.getenv("DISKWALA_API_ENDPOINT", "").strip()
        if base_url:
            _validate_http_url("DISKWALA_API_BASE_URL", base_url, require_https=False)
        if endpoint and not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"

        return cls(
            bot_token=token,
            bot_username=os.getenv("BOT_USERNAME", "").strip().lstrip("@"),
            admin_user_id=admin_user_id,
            admin_username=os.getenv("ADMIN_USERNAME", "").strip().lstrip("@"),
            source_channel_id=source_channel_id,
            source_channel_username=os.getenv("SOURCE_CHANNEL_USERNAME", "").strip().lstrip("@"),
            post_delay_minutes=_immediate_delay_minutes(),
            diskwala_api_base_url=base_url,
            diskwala_api_endpoint=endpoint,
            diskwala_api_key=os.getenv("DISKWALA_API_KEY", "").strip(),
            diskwala_api_auth_header=os.getenv("DISKWALA_API_AUTH_HEADER", "Authorization").strip()
            or "Authorization",
            diskwala_api_auth_scheme=os.getenv("DISKWALA_API_AUTH_SCHEME", "Bearer").strip(),
            diskwala_api_request_field=os.getenv("DISKWALA_API_REQUEST_FIELD", "url").strip()
            or "url",
            diskwala_api_response_field=os.getenv("DISKWALA_API_RESPONSE_FIELD", "").strip(),
            diskwala_allowed_hosts=allowed_hosts,
            database_url=os.getenv("DATABASE_URL", "sqlite:///data/bot.db").strip(),
            broadcast_rate_per_second=_positive_int("BROADCAST_RATE_PER_SECOND", 25),
            broadcast_header=_env_text("BROADCAST_HEADER", DEFAULT_BROADCAST_HEADER),
            allow_paid_broadcast=_boolean("ALLOW_PAID_BROADCAST", False),
            app_mode=app_mode,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            log_level=log_level,
            diskwala_timeout_seconds=_positive_float("DISKWALA_TIMEOUT_SECONDS", 10.0),
            diskwala_max_attempts=_positive_int("DISKWALA_MAX_ATTEMPTS", 3),
            telegram_api_id=_optional_int(
                "TELEGRAM_API_ID", os.getenv("TELEGRAM_API_ID", "").strip()
            ),
            telegram_api_hash=os.getenv("TELEGRAM_API_HASH", "").strip(),
            telegram_phone=os.getenv("TELEGRAM_PHONE", "").strip(),
            telethon_session_name=os.getenv("TELETHON_SESSION_NAME", "").strip(),
            diskwala_converter_bot=os.getenv("DISKWALA_CONVERTER_BOT", "DW2DW_LinkConverterBot")
            .strip()
            .lstrip("@")
            or "DW2DW_LinkConverterBot",
            diskwala_converter_timeout_seconds=_positive_int(
                "DISKWALA_CONVERTER_TIMEOUT_SECONDS", 60
            ),
        )

    @property
    def async_database_url(self) -> str:
        if self.database_url.startswith("sqlite+aiosqlite://"):
            return self.database_url
        if self.database_url.startswith("sqlite://"):
            return self.database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        raise ConfigurationError("This bot currently supports SQLite DATABASE_URL values.")

    @property
    def diskwala_conversion_configured(self) -> bool:
        return bool(
            self.telegram_api_id
            and self.telegram_api_hash
            and self.telegram_phone
            and self.telethon_session_name
            and self.diskwala_converter_bot
        )


def _optional_int(name: str, raw: str) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric.") from exc


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero.")
    return value


def _nonnegative_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc
    if value < 0:
        raise ConfigurationError(f"{name} cannot be negative.")
    return value


def _immediate_delay_minutes() -> int:
    legacy_raw = os.getenv("BROADCAST_DELAY_MINUTES", "").strip()
    if legacy_raw:
        legacy_value = _nonnegative_int("BROADCAST_DELAY_MINUTES", 0)
        if legacy_value != 0:
            raise ConfigurationError(
                "BROADCAST_DELAY_MINUTES is no longer supported. "
                "Remove it or set POST_DELAY_MINUTES=0."
            )

    value = _nonnegative_int("POST_DELAY_MINUTES", 0)
    if value != 0:
        raise ConfigurationError(
            "POST_DELAY_MINUTES must be 0 so source-channel broadcasts process immediately."
        )
    return 0


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number.") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero.")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false.")


def _env_text(name: str, default: str) -> str:
    return os.getenv(name, default).replace("\\n", "\n").strip()


def _validate_http_url(name: str, value: str, *, require_https: bool) -> None:
    parsed = urlsplit(value)
    schemes = {"https"} if require_https else {"http", "https"}
    if parsed.scheme not in schemes or not parsed.hostname or parsed.username:
        protocol = "HTTPS" if require_https else "HTTP or HTTPS"
        raise ConfigurationError(f"{name} must be a complete {protocol} URL.")
