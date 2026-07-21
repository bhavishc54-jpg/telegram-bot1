"""Numeric-admin-only commands."""

from __future__ import annotations

import json
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.config import Settings
from app.models import (
    BotSetting,
    BroadcastDelivery,
    BroadcastJob,
    SourceLink,
    SourcePost,
    SourcePostStatus,
    Subscriber,
    utcnow,
)
from app.repositories.source_posts import retry_post
from app.services.manual_broadcast import queue_manual_broadcast
from app.workers.queue_worker import set_broadcasts_paused


def _dependencies(
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[Settings, async_sessionmaker[AsyncSession]]:
    return context.application.bot_data["settings"], context.application.bot_data["session_factory"]


async def _authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings, _ = _dependencies(context)
    if update.effective_user and update.effective_user.id == settings.admin_user_id:
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Not allowed.")
    return False


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorized(update, context) or not update.effective_message:
        return
    _, session_factory = _dependencies(context)
    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(Subscriber)) or 0
        active = (
            await session.scalar(
                select(func.count()).select_from(Subscriber).where(Subscriber.is_active.is_(True))
            )
            or 0
        )
        status_counts = {}
        for status in SourcePostStatus:
            status_counts[status.value] = (
                await session.scalar(
                    select(func.count()).select_from(SourcePost).where(SourcePost.status == status)
                )
                or 0
            )
    await update.effective_message.reply_text(
        "Bot statistics\n"
        f"Total stored users: {total}\n"
        f"Active subscribers: {active}\n"
        f"Inactive or blocked subscribers: {total - active}\n"
        f"Pending posts: {status_counts['pending']}\n"
        f"Processing posts: {status_counts['processing']}\n"
        f"Completed posts: {status_counts['completed']}\n"
        f"Failed posts: {status_counts['failed']}\n"
        f"Skipped posts: {status_counts['skipped']}"
    )


async def queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorized(update, context) or not update.effective_message:
        return
    _, session_factory = _dependencies(context)
    lines = ["Next pending jobs"]
    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(SourcePost)
                .where(SourcePost.status == SourcePostStatus.PENDING)
                .order_by(
                    SourcePost.due_at, SourcePost.source_message_date, SourcePost.source_message_id
                )
                .limit(10)
            )
        )
        for post in rows:
            link_count = (
                await session.scalar(
                    select(func.count())
                    .select_from(SourceLink)
                    .where(SourceLink.source_post_id == post.id)
                )
                or 0
            )
            lines.append(
                f"ID {post.id} | msg {post.source_message_id} | due {post.due_at:%Y-%m-%d %H:%M} | "
                f"links {link_count} | {post.status.value}"
            )
    if len(lines) == 1:
        lines.append("No pending jobs.")
    await update.effective_message.reply_text("\n".join(lines))


async def retry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorized(update, context) or not update.effective_message:
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text("Usage: /retry JOB_ID")
        return
    try:
        job_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("JOB_ID must be numeric.")
        return
    _, session_factory = _dependencies(context)
    async with session_factory() as session:
        broadcast_job = await session.get(BroadcastJob, job_id)
        source_post_id = broadcast_job.source_post_id if broadcast_job else job_id
        ok = await retry_post(session, source_post_id)
        await session.commit()
    await update.effective_message.reply_text("Job queued for retry." if ok else "Job not found.")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorized(update, context) or not update.effective_message:
        return
    text = _broadcast_text_from_command(update, context)
    if not text:
        await update.effective_message.reply_text("There is no text to broadcast.")
        return
    settings, session_factory = _dependencies(context)
    async with session_factory() as session:
        queued = await queue_manual_broadcast(
            session,
            settings,
            text=text,
            command_message_id=update.effective_message.message_id,
        )
        await session.commit()
    await update.effective_message.reply_text(
        "Broadcast queued.\n"
        f"Active subscribers: {queued.active_subscribers}\n"
        f"Broadcast job ID: {queued.job_id}\n"
        f"Status: {queued.status}"
    )


def _broadcast_text_from_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    message = update.effective_message
    if message is None:
        return ""
    command_text = " ".join(context.args).strip()
    if command_text:
        return command_text
    replied = getattr(message, "reply_to_message", None)
    if replied is None:
        return ""
    return (replied.text or replied.caption or "").strip()


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_paused(update, context, paused=True)


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_paused(update, context, paused=False)


async def _set_paused(update: Update, context: ContextTypes.DEFAULT_TYPE, *, paused: bool) -> None:
    if not await _authorized(update, context) or not update.effective_message:
        return
    _, session_factory = _dependencies(context)
    async with session_factory() as session:
        await set_broadcasts_paused(session, paused)
        await session.commit()
    await update.effective_message.reply_text(
        "Broadcasts paused." if paused else "Broadcasts resumed."
    )


async def paused_setting(session: AsyncSession) -> bool:
    setting = await session.get(BotSetting, "broadcast_paused")
    return bool(setting and setting.value.lower() == "true")



async def delete_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorized(update, context) or not update.effective_message:
        return

    message = update.effective_message
    replied = message.reply_to_message
    if replied is None:
        await message.reply_text(
            "Reply to a broadcast success message or one of your received broadcast posts with /delete."
        )
        return

    _, session_factory = _dependencies(context)
    job_id: int | None = None

    if replied.text:
        match = re.search(r"Broadcast Job ID:\s*(\d+)", replied.text)
        if match:
            job_id = int(match.group(1))

    async with session_factory() as session:
        if job_id is None:
            rows = list(
                await session.scalars(
                    select(BroadcastDelivery).where(
                        BroadcastDelivery.subscriber_id == message.chat_id
                    )
                )
            )
            for row in rows:
                try:
                    ids = [int(x) for x in json.loads(row.message_ids or "[]")]
                except (ValueError, TypeError, json.JSONDecodeError):
                    ids = []
                if replied.message_id in ids:
                    job_id = row.broadcast_job_id
                    break

        if job_id is None:
            await message.reply_text("Could not identify that broadcast.")
            return

        deliveries = list(
            await session.scalars(
                select(BroadcastDelivery).where(
                    BroadcastDelivery.broadcast_job_id == job_id
                )
            )
        )

        deleted = 0
        for delivery in deliveries:
            try:
                ids = [int(x) for x in json.loads(delivery.message_ids or "[]")]
            except (ValueError, TypeError, json.JSONDecodeError):
                ids = []
            for message_id in ids:
                try:
                    await context.bot.delete_message(
                        chat_id=delivery.subscriber_id,
                        message_id=message_id,
                    )
                    deleted += 1
                except Exception:
                    pass
            delivery.deleted_at = delivery.deleted_at or utcnow()

        await session.commit()

    await message.reply_text(
        f"\u2705 Broadcast Job {job_id} deleted from {deleted} stored message copies."
    )

def handlers() -> list[object]:
    return [
        CommandHandler("stats", stats),
        CommandHandler("queue", queue),
        CommandHandler("retry", retry),
        CommandHandler("broadcast", broadcast),
        CommandHandler("pause", pause),
        CommandHandler("resume", resume),
        CommandHandler("delete", delete_broadcast),
    ]
