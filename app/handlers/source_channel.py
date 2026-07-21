"""Source-channel post intake and edit handling."""

from __future__ import annotations

import logging
import traceback

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Chat, Message, Update
from telegram.ext import ContextTypes, MessageHandler, filters

from app.config import Settings
from app.models import SourcePostStatus
from app.repositories.source_posts import create_or_update_source_post
from app.utils.terminal import terminal_log

logger = logging.getLogger(__name__)


def _dependencies(
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[Settings, async_sessionmaker[AsyncSession]]:
    return context.application.bot_data["settings"], context.application.bot_data["session_factory"]


async def channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.channel_post
    await _handle_channel_message(message, context, edited=False)


async def edited_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.edited_channel_post
    await _handle_channel_message(message, context, edited=True)


async def _handle_channel_message(
    message: Message | None,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edited: bool,
) -> None:
    try:
        await _handle_channel_message_inner(message, context, edited=edited)
    except Exception as exc:
        terminal_log(
            "SOURCE HANDLER EXCEPTION",
            f"Exception type: {type(exc).__name__}",
            f"Safe message: {_safe_exception_message(exc)}",
            "Traceback:",
            traceback.format_exc(),
        )
        logger.exception("Source-channel handler failed.")
        return


async def _handle_channel_message_inner(
    message: Message | None,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edited: bool,
) -> None:
    if message is None:
        terminal_log("SOURCE POST IGNORED", "Reason: missing message")
        return
    if message.chat.type != Chat.CHANNEL:
        terminal_log("SOURCE POST IGNORED", f"Reason: chat type is {message.chat.type}")
        return
    settings, session_factory = _dependencies(context)
    if message.from_user and message.from_user.is_bot:
        terminal_log("SOURCE POST IGNORED", "Reason: sender is bot")
        return
    terminal_log(
        "SOURCE POST RECEIVED",
        f"Channel ID: {message.chat.id}",
        f"Message ID: {message.message_id}",
    )
    terminal_log(
        "SOURCE CHANNEL CHECK",
        f"Received channel ID: {message.chat.id}",
        f"Configured SOURCE_CHANNEL_ID: {settings.source_channel_id}",
    )
    if settings.source_channel_id is None:
        terminal_log(
            "SOURCE CHANNEL DETECTED",
            f"Channel title: {message.chat.title or ''}",
            f"Channel ID: {message.chat.id}",
            f"Message ID: {message.message_id}",
        )
        logger.warning("Source channel detected while SOURCE_CHANNEL_ID is empty.")
        return
    if message.chat.id != settings.source_channel_id:
        terminal_log(
            "SOURCE POST IGNORED",
            f"Received channel ID: {message.chat.id}",
            f"Configured source channel ID: {settings.source_channel_id}",
        )
        logger.info("Source post ignored because channel ID did not match.")
        return
    terminal_log("SOURCE CHANNEL MATCHED", f"Channel ID: {message.chat.id}")

    terminal_log("SOURCE TEXT READ STARTED", f"Message ID: {message.message_id}")
    text = message.text or message.caption or ""
    entities = message.entities if message.text else message.caption_entities
    terminal_log(
        "SOURCE TEXT EXTRACTED",
        f"Message ID: {message.message_id}",
        f"Text length: {len(text)}",
        f"Has entities: {bool(entities)}",
    )
    terminal_log("SOURCE DUPLICATE CHECK STARTED", f"Message ID: {message.message_id}")
    async with session_factory() as session:
        existing = await _existing_source_post(session, message.chat.id, message.message_id)
        terminal_log(
            "SOURCE DUPLICATE CHECK FINISHED",
            f"Message ID: {message.message_id}",
            f"Duplicate: {existing is not None}",
        )
        terminal_log("SOURCE DATABASE SAVE STARTED", f"Message ID: {message.message_id}")
        post = await create_or_update_source_post(
            session,
            settings,
            source_chat_id=message.chat.id,
            source_message_id=message.message_id,
            source_message_date=message.date,
            text=text,
            entities=entities,
            edited=edited,
        )
        terminal_log(
            "SOURCE DATABASE SAVE FINISHED",
            f"Source post ID: {post.id}",
            f"Status: {_status_value(post.status)}",
        )
        await session.commit()
        terminal_log("SOURCE DATABASE COMMIT FINISHED", f"Source post ID: {post.id}")
    terminal_log(
        "SOURCE POST SAVED",
        f"Source post ID: {post.id}",
        f"Status: {_status_value(post.status)}",
    )
    due_line = (
        "Broadcasting immediately..."
        if settings.post_delay_minutes == 0
        else f"Due in: {settings.post_delay_minutes} minutes"
    )
    terminal_log(
        "SOURCE POST ACCEPTED",
        f"Channel ID: {message.chat.id}",
        f"Message ID: {message.message_id}",
        due_line,
    )
    if edited and post.status is not SourcePostStatus.PENDING:
        logger.info("Received edit after delivery or skip for source_post_id=%s.", post.id)
    else:
        logger.info("Queued source_post_id=%s status=%s.", post.id, _status_value(post.status))


def handlers() -> list[object]:
    return [
        MessageHandler(filters.UpdateType.CHANNEL_POST, channel_post),
        MessageHandler(filters.UpdateType.EDITED_CHANNEL_POST, edited_channel_post),
    ]


async def _existing_source_post(
    session: AsyncSession, source_chat_id: int, source_message_id: int
) -> object | None:
    from sqlalchemy import select

    from app.models import SourcePost

    return await session.scalar(
        select(SourcePost).where(
            SourcePost.source_chat_id == source_chat_id,
            SourcePost.source_message_id == source_message_id,
        )
    )


def _status_value(status: object) -> str:
    return str(getattr(status, "value", status))


def _safe_exception_message(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    return message[:500] if message else type(exc).__name__
