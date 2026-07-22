"""Private subscriber commands and active-post delivery for late joiners."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import CommandHandler, ContextTypes

from app.config import Settings
from app.models import (
    BroadcastDelivery,
    DeliveryStatus,
    Subscriber,
    utcnow,
)
from app.repositories.subscribers import mark_inactive, upsert_subscriber

logger = logging.getLogger(__name__)


def _dependencies(
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[Settings, async_sessionmaker[AsyncSession]]:
    return (
        context.application.bot_data["settings"],
        context.application.bot_data["session_factory"],
    )


async def _send_active_posts_to_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    user = update.effective_user
    chat = update.effective_chat

    if user is None or chat is None:
        return 0

    now = utcnow()
    sent_count = 0

    async with session_factory() as session:
        active_deliveries = list(
            await session.scalars(
                select(BroadcastDelivery)
                .where(
                    BroadcastDelivery.status == DeliveryStatus.SENT,
                    BroadcastDelivery.deleted_at.is_(None),
                    BroadcastDelivery.expires_at.is_not(None),
                    BroadcastDelivery.expires_at > now,
                )
                .order_by(BroadcastDelivery.broadcast_job_id, BroadcastDelivery.id)
            )
        )

        job_ids: list[int] = []
        template_by_job: dict[int, BroadcastDelivery] = {}

        for delivery in active_deliveries:
            if delivery.broadcast_job_id not in template_by_job:
                template_by_job[delivery.broadcast_job_id] = delivery
                job_ids.append(delivery.broadcast_job_id)

        for job_id in job_ids:
            existing = await session.scalar(
                select(BroadcastDelivery).where(
                    BroadcastDelivery.broadcast_job_id == job_id,
                    BroadcastDelivery.subscriber_id == user.id,
                )
            )

            if existing is not None:
                continue

            template = template_by_job[job_id]
            template_subscriber = await session.get(
                Subscriber,
                template.subscriber_id,
            )

            if template_subscriber is None:
                continue

            try:
                source_message_ids = json.loads(template.message_ids or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                source_message_ids = []

            if not source_message_ids:
                continue

            copied_message_ids: list[int] = []

            try:
                for source_message_id in source_message_ids:
                    copied = await context.bot.copy_message(
                        chat_id=chat.id,
                        from_chat_id=template_subscriber.chat_id,
                        message_id=int(source_message_id),
                    )
                    copied_message_ids.append(int(copied.message_id))

                session.add(
                    BroadcastDelivery(
                        broadcast_job_id=job_id,
                        subscriber_id=user.id,
                        status=DeliveryStatus.SENT,
                        attempt_count=1,
                        sent_at=utcnow(),
                        message_ids=json.dumps(copied_message_ids),
                        expires_at=template.expires_at,
                    )
                )

                await session.commit()
                sent_count += 1

            except TelegramError as exc:
                await session.rollback()
                logger.warning(
                    "Could not send active broadcast job %s to late user %s: %s",
                    job_id,
                    user.id,
                    type(exc).__name__,
                )

                for copied_message_id in copied_message_ids:
                    try:
                        await context.bot.delete_message(
                            chat_id=chat.id,
                            message_id=copied_message_id,
                        )
                    except TelegramError:
                        pass

    return sent_count


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if (
        not update.effective_user
        or not update.effective_chat
        or not update.effective_message
    ):
        return

    _, session_factory = _dependencies(context)

    async with session_factory() as session:
        await upsert_subscriber(
            session,
            update.effective_user,
            update.effective_chat.id,
        )
        await session.commit()

    await update.effective_message.reply_text(
        "Welcome. You will receive automatic updates here when new posts are ready."
    )

    delivered = await _send_active_posts_to_user(
        update,
        context,
        session_factory,
    )

    if delivered > 0:
        await update.effective_message.reply_text(
            f"\U0001F4E5 {delivered} active update(s) from earlier have been sent to you."
        )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return

    _, session_factory = _dependencies(context)

    async with session_factory() as session:
        await mark_inactive(session, update.effective_user.id)
        await session.commit()

    await update.effective_message.reply_text(
        "Automatic updates are stopped."
    )


async def help_command(
    update: Update,
    _context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "This bot sends automatic updates. "
            "Use /stop any time to unsubscribe."
        )


async def myid(
    update: Update,
    _context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_user and update.effective_message:
        await update.effective_message.reply_text(
            f"Your Telegram ID is {update.effective_user.id}."
        )


def handlers() -> list[object]:
    return [
        CommandHandler("start", start),
        CommandHandler("stop", stop),
        CommandHandler("help", help_command),
        CommandHandler("myid", myid),
    ]
