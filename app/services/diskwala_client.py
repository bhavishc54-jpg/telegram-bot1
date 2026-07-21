"""DiskWala link conversion through the saved Telethon user session."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import RPCError

from app.config import Settings
from app.models import ConversionCache
from app.services.post_processor import extract_links, ordered_unique_diskwala_links
from app.utils.terminal import terminal_log

logger = logging.getLogger(__name__)


class DiskWalaError(RuntimeError):
    """Base class for safe DiskWala conversion errors."""


class DiskWalaConfigurationError(DiskWalaError):
    """Raised when Telethon converter settings are incomplete."""


class DiskWalaConversionError(DiskWalaError):
    """Raised when a link cannot be converted."""


class TelethonClientProtocol(Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def is_user_authorized(self) -> bool: ...

    async def get_entity(self, entity: str): ...

    def conversation(self, entity, *, timeout: int): ...


class DiskWalaClient:
    def __init__(
        self,
        settings: Settings,
        telethon_client: TelethonClientProtocol | None = None,
    ) -> None:
        self._settings = settings
        self._client = telethon_client
        self._owns_client = telethon_client is None
        self._connected = False
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._client is not None and self._connected:
            await self._client.disconnect()
            self._connected = False

    async def start(self) -> None:
        self._ensure_configured()
        await self._connected_client()

    async def convert_link(self, original_url: str) -> str:
        self._ensure_configured()
        async with self._lock:
            return await self._convert_with_retry(original_url)

    async def convert_links(self, original_urls: list[str] | tuple[str, ...]) -> list[str]:
        self._ensure_configured()
        async with self._lock:
            return await self._convert_many_with_retry(list(original_urls))

    async def _convert_many_with_retry(self, original_urls: list[str]) -> list[str]:
        if not original_urls:
            return []
        terminal_log("MULTI LINK BATCH STARTED", f"SOURCE LINKS: {len(original_urls)}")
        try:
            converted = await self._convert_many_once(original_urls)
            terminal_log(
                f"CONVERTED LINKS EXTRACTED: {len(converted)}",
                "MULTI LINK BATCH COMPLETED",
            )
            return converted
        except DiskWalaError as exc:
            terminal_log(f"MULTI LINK BATCH FAILED: {str(exc) or type(exc).__name__}")
            raise

    async def _convert_with_retry(self, original_url: str) -> str:
        last_error = "converter_timeout"
        for attempt in range(2):
            try:
                logger.info("DiskWala conversion started. attempt=%s", attempt + 1)
                terminal_log("CONVERSION STARTED", f"Attempt: {attempt + 1}")
                return await self._convert_once(original_url)
            except TimeoutError:
                last_error = "converter_timeout"
                logger.warning("DiskWala conversion failed at stage=converter_timeout.")
                if attempt == 0:
                    terminal_log("CONVERSION TIMEOUT; RETRYING")
                    continue
                terminal_log("BROADCAST FAILED: converter_timeout")
            except (RPCError, OSError) as exc:
                last_error = type(exc).__name__
                logger.exception("DiskWala conversion failed at stage=telethon_rpc.")
                terminal_log(f"BROADCAST FAILED: telethon_rpc:{type(exc).__name__}")
                break
            except DiskWalaConversionError as exc:
                last_error = str(exc) or type(exc).__name__
                logger.exception("DiskWala conversion failed at stage=reply_parsing.")
                terminal_log(f"BROADCAST FAILED: reply_parsing:{last_error}")
                break
        logger.warning("DiskWala converter failed: %s", last_error)
        raise DiskWalaConversionError(last_error)

    async def _convert_once(self, original_url: str) -> str:
        client = await self._connected_client()
        entity = await client.get_entity(self._settings.diskwala_converter_bot)
        async with client.conversation(
            entity, timeout=self._settings.diskwala_converter_timeout_seconds
        ) as conversation:
            await conversation.send_message(original_url)
            response = await conversation.get_response()
        logger.info("DiskWala converter reply received.")
        terminal_log("CONVERSION REPLY RECEIVED")
        converted_links = _diskwala_links_from_converter_reply(
            response.raw_text or "", self._settings.diskwala_allowed_hosts
        )
        if not converted_links:
            raise DiskWalaConversionError("converter_reply_missing_diskwala_link")
        logger.info("Converted DiskWala URL extracted.")
        terminal_log("CONVERTED LINK EXTRACTED")
        return converted_links[0]

    async def _convert_many_once(self, original_urls: list[str]) -> list[str]:
        client = await self._connected_client()
        entity = await client.get_entity(self._settings.diskwala_converter_bot)
        request_text = "\n".join(original_urls)
        responses: list[str] = []
        async with client.conversation(
            entity, timeout=self._settings.diskwala_converter_timeout_seconds
        ) as conversation:
            await conversation.send_message(request_text)
            terminal_log("CONVERTER REQUEST SENT")
            first_response = await conversation.get_response()
            responses.append(first_response.raw_text or "")
            extracted = _diskwala_links_from_converter_reply(
                "\n".join(responses), self._settings.diskwala_allowed_hosts
            )
            if len(extracted) >= len(original_urls):
                terminal_log(f"CONVERTER REPLIES RECEIVED: {len(responses)}")
                return list(extracted[: len(original_urls)])
            while True:
                try:
                    response = await asyncio.wait_for(conversation.get_response(), timeout=1.5)
                except TimeoutError:
                    break
                responses.append(response.raw_text or "")
                extracted = _diskwala_links_from_converter_reply(
                    "\n".join(responses), self._settings.diskwala_allowed_hosts
                )
                if len(extracted) >= len(original_urls):
                    break
        terminal_log(f"CONVERTER REPLIES RECEIVED: {len(responses)}")
        converted_links = _diskwala_links_from_converter_reply(
            "\n".join(responses), self._settings.diskwala_allowed_hosts
        )
        if len(converted_links) < len(original_urls):
            raise DiskWalaConversionError("converter_batch_incomplete")
        return list(converted_links[: len(original_urls)])

    async def _connected_client(self) -> TelethonClientProtocol:
        if self._client is None:
            self._client = TelegramClient(
                str(_session_path(self._settings.telethon_session_name)),
                self._settings.telegram_api_id,
                self._settings.telegram_api_hash,
            )
        if not self._connected:
            await self._client.connect()
            self._connected = True
            logger.info("Telethon client connected using saved session.")
            terminal_log("TELETHON CONNECTED")
        if not await self._client.is_user_authorized():
            terminal_log("BROADCAST FAILED: telethon_session_unauthorized")
            raise DiskWalaConfigurationError(
                "Telethon session is not logged in. Run scripts/telethon_login.py first."
            )
        return self._client

    def _ensure_configured(self) -> None:
        if not self._settings.diskwala_conversion_configured:
            raise DiskWalaConfigurationError("Telethon DiskWala converter settings are incomplete.")


async def convert_with_cache(
    session: AsyncSession,
    client: DiskWalaClient,
    original_url: str,
) -> str:
    cached = await session.get(ConversionCache, original_url)
    if cached is not None:
        return cached.converted_url
    converted = await client.convert_link(original_url)
    session.add(ConversionCache(original_url=original_url, converted_url=converted))
    return converted


async def convert_many_with_cache(
    session: AsyncSession,
    client: DiskWalaClient,
    original_urls: list[str] | tuple[str, ...],
) -> list[str]:
    converted_by_original: dict[str, str] = {}
    missing: list[str] = []
    for original_url in original_urls:
        cached = await session.get(ConversionCache, original_url)
        if cached is None:
            missing.append(original_url)
        else:
            converted_by_original[original_url] = cached.converted_url

    unique_missing = list(dict.fromkeys(missing))
    last_error = "all_conversions_failed"
    if unique_missing:
        try:
            converted_missing = await client.convert_links(unique_missing)
        except DiskWalaError:
            logger.exception(
                "Batch conversion failed; falling back to ordered single-link retries."
            )
            converted_missing = []
            for original_url in unique_missing:
                try:
                    converted_missing.append(await client.convert_link(original_url))
                except DiskWalaError as exc:
                    logger.exception("Single-link fallback conversion failed.")
                    last_error = str(exc) or type(exc).__name__
                    converted_missing.append("")
        for original_url, converted_url in zip(unique_missing, converted_missing, strict=False):
            if not converted_url:
                continue
            converted_by_original[original_url] = converted_url
            session.add(ConversionCache(original_url=original_url, converted_url=converted_url))

    ordered_converted: list[str] = []
    seen_converted: set[str] = set()
    for original_url in original_urls:
        converted_url = converted_by_original.get(original_url)
        if converted_url and converted_url not in seen_converted:
            seen_converted.add(converted_url)
            ordered_converted.append(converted_url)
    if original_urls and not ordered_converted:
        raise DiskWalaConversionError(last_error)
    return ordered_converted


def _diskwala_links_from_converter_reply(
    reply_text: str, allowed_hosts: tuple[str, ...]
) -> tuple[str, ...]:
    links = extract_links(reply_text, None, allowed_hosts)
    return ordered_unique_diskwala_links(links)


def _session_path(session_name: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_name).strip("._")
    if not safe_name:
        raise DiskWalaConfigurationError("TELETHON_SESSION_NAME is invalid.")
    return Path("data") / "telethon_sessions" / safe_name
