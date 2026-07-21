"""Delete expired broadcast and scheduled messages."""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Bot
from telegram.error import Forbidden, TelegramError

from app.models import BroadcastDelivery, DeliveryStatus, ScheduledDeletion, utcnow
from app.utils.terminal import terminal_log

logger = logging.getLogger(__name__)


class DeleteWorker:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        interval_seconds: int = 60,
    ) -> None:
        self._bot = bot
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        terminal_log("DELETE WORKER STARTED")
        while not self._stop_event.is_set():
            try:
                await self.delete_expired_messages()
            except Exception as exc:
                logger.exception("Delete worker failed: %s", type(exc).__name__)
                terminal_log(f"DELETE WORKER FAILED: {type(exc).__name__}")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                pass

    async def delete_expired_messages(self) -> None:
        now = utcnow()
        async with self._session_factory() as session:
            deliveries = list(
                await session.scalars(
                    select(BroadcastDelivery).where(
                        BroadcastDelivery.status == DeliveryStatus.SENT,
                        BroadcastDelivery.expires_at.is_not(None),
                        BroadcastDelivery.expires_at <= now,
                        BroadcastDelivery.deleted_at.is_(None),
                    )
                )
            )
            for delivery in deliveries:
                for message_id in _parse_message_ids(delivery.message_ids):
                    await _safe_delete(self._bot, delivery.subscriber_id, message_id)
                delivery.deleted_at = now
                terminal_log(f"EXPIRED BROADCAST DELETED: delivery_id={delivery.id}")

            scheduled = list(
                await session.scalars(
                    select(ScheduledDeletion).where(
                        ScheduledDeletion.delete_at <= now,
                        ScheduledDeletion.deleted_at.is_(None),
                    )
                )
            )
            for item in scheduled:
                await _safe_delete(self._bot, item.chat_id, item.message_id)
                item.deleted_at = now
                terminal_log(
                    f"SCHEDULED MESSAGE DELETED: kind={item.kind} chat={item.chat_id} msg={item.message_id}"
                )

            if deliveries or scheduled:
                await session.commit()


async def _safe_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Forbidden:
        pass
    except TelegramError as exc:
        logger.warning(
            "Could not delete message. chat_id=%s message_id=%s error=%s",
            chat_id,
            message_id,
            type(exc).__name__,
        )


def _parse_message_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [int(item) for item in data if isinstance(item, (int, str)) and str(item).isdigit()]
