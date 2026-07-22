"""Persistent, text-only broadcast delivery with pacing and progress tracking."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter, TelegramError

from app.models import (
    BroadcastDelivery,
    BroadcastJob,
    BroadcastStatus,
    DeliveryStatus,
    SourcePost,
    utcnow,
)
from app.repositories.subscribers import active_subscribers, mark_inactive
from app.services.post_processor import split_telegram_text
from app.utils.terminal import terminal_log

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BroadcastResult:
    sent: int
    failed: int
    blocked: int


async def get_or_create_broadcast_job(
    session: AsyncSession, source_post: SourcePost
) -> BroadcastJob:
    job = await session.scalar(
        select(BroadcastJob).where(BroadcastJob.source_post_id == source_post.id)
    )
    if job is None:
        job = BroadcastJob(source_post_id=source_post.id, status=BroadcastStatus.PENDING)
        session.add(job)
        await session.flush()
    return job


async def ensure_deliveries(session: AsyncSession, job: BroadcastJob) -> list[BroadcastDelivery]:
    subscribers = await active_subscribers(session)
    terminal_log(f"ACTIVE SUBSCRIBERS: {len(subscribers)}")
    existing = {
        delivery.subscriber_id
        for delivery in await session.scalars(
            select(BroadcastDelivery).where(BroadcastDelivery.broadcast_job_id == job.id)
        )
    }
    for subscriber in subscribers:
        if subscriber.user_id not in existing:
            session.add(
                BroadcastDelivery(
                    broadcast_job_id=job.id,
                    subscriber_id=subscriber.user_id,
                    status=DeliveryStatus.PENDING,
                )
            )
    await session.flush()
    return list(
        await session.scalars(
            select(BroadcastDelivery)
            .where(BroadcastDelivery.broadcast_job_id == job.id)
            .order_by(BroadcastDelivery.id)
        )
    )


async def deliver_job(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    job_id: int,
    text: str | list[str],
    *,
    rate_per_second: int,
) -> BroadcastResult:
    delay = 1 / max(rate_per_second, 1)
    parts = text if isinstance(text, list) else split_telegram_text(text)
    sent = failed = blocked = 0
    async with session_factory() as session:
        job = await session.get(BroadcastJob, job_id)
        if job is None:
            return BroadcastResult(0, 0, 0)
        job.status = BroadcastStatus.SENDING
        job.started_at = job.started_at or utcnow()
        await session.commit()

    while True:
        async with session_factory() as session:
            delivery = await session.scalar(
                select(BroadcastDelivery)
                .where(
                    BroadcastDelivery.broadcast_job_id == job_id,
                    BroadcastDelivery.status == DeliveryStatus.PENDING,
                )
                .order_by(BroadcastDelivery.id)
            )
            if delivery is None:
                break
            subscriber_id = delivery.subscriber_id
            delivery_id = delivery.id
            delivery.attempt_count += 1
            await session.commit()

        status, error, message_ids = await _send_parts(bot, subscriber_id, parts)
        async with session_factory() as session:
            delivery = await session.get(BroadcastDelivery, delivery_id)
            if delivery is None:
                continue
            delivery.status = status
            delivery.last_error = error
            if status is DeliveryStatus.SENT:
                sent_time = utcnow()
                delivery.sent_at = sent_time
                delivery.message_ids = json.dumps(message_ids)
                delivery.expires_at = sent_time + timedelta(hours=16)
                sent += 1
                terminal_log("BROADCAST SENT")
            elif status is DeliveryStatus.BLOCKED:
                blocked += 1
                terminal_log("BROADCAST FAILED: subscriber_blocked")
                await mark_inactive(session, delivery.subscriber_id, blocked=True)
            else:
                failed += 1
                terminal_log(f"BROADCAST FAILED: {error or 'telegram_error'}")
            await session.commit()
        if delay:
            await asyncio.sleep(delay)

    async with session_factory() as session:
        job = await session.get(BroadcastJob, job_id)
        if job is not None:
            job.sent_count = sent
            job.failed_count = failed
            job.blocked_count = blocked
            job.finished_at = utcnow()
            job.status = (
                BroadcastStatus.COMPLETED
                if failed == 0 and blocked == 0
                else BroadcastStatus.FAILED
            )
            if failed or blocked:
                job.last_error = f"{failed} deliveries failed, {blocked} subscribers blocked"
        await session.commit()
    logger.info(
        "Broadcast job %s complete: sent=%s failed=%s blocked=%s", job_id, sent, failed, blocked
    )
    return BroadcastResult(sent, failed, blocked)


async def _send_parts(
    bot: Bot,
    chat_id: int,
    parts: list[str],
) -> tuple[DeliveryStatus, str | None, list[int]]:
    sent_message_ids: list[int] = []

    for part in parts:
        try:
            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=part,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            message_id = getattr(sent_message, "message_id", None)
            if message_id is not None:
                sent_message_ids.append(int(message_id))

        except RetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 0.5)
            try:
                sent_message = await bot.send_message(
                    chat_id=chat_id,
                    text=part,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                message_id = getattr(sent_message, "message_id", None)
                if message_id is not None:
                    sent_message_ids.append(int(message_id))

            except Forbidden as retry_forbidden:
                return DeliveryStatus.BLOCKED, type(retry_forbidden).__name__, sent_message_ids
            except TelegramError as retry_error:
                return DeliveryStatus.FAILED, type(retry_error).__name__, sent_message_ids

        except Forbidden as exc:
            return DeliveryStatus.BLOCKED, type(exc).__name__, sent_message_ids
        except TelegramError as exc:
            return DeliveryStatus.FAILED, type(exc).__name__, sent_message_ids

    return DeliveryStatus.SENT, None, sent_message_ids

