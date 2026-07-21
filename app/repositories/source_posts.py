"""Source-channel queue persistence helpers."""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import LinkStatus, SourceLink, SourcePost, SourcePostStatus, utcnow
from app.services.post_processor import process_source_text
from app.utils.terminal import terminal_log

logger = logging.getLogger(__name__)


async def create_or_update_source_post(
    session: AsyncSession,
    settings: Settings,
    *,
    source_chat_id: int,
    source_message_id: int,
    source_message_date,
    text: str,
    entities: list[object] | tuple[object, ...] | None,
    edited: bool = False,
) -> SourcePost:
    post = await session.scalar(
        select(SourcePost).where(
            SourcePost.source_chat_id == source_chat_id,
            SourcePost.source_message_id == source_message_id,
        )
    )
    processed = process_source_text(text, entities, settings.diskwala_allowed_hosts)
    logger.info(
        "Source post received. chat_id=%s message_id=%s disk_wala_links=%s",
        source_chat_id,
        source_message_id,
        len(processed.original_diskwala_links),
    )
    for position, original_url in enumerate(processed.original_diskwala_links, start=1):
        logger.info(
            "DiskWala URL found. chat_id=%s message_id=%s position=%s url=%s",
            source_chat_id,
            source_message_id,
            position,
            original_url,
        )
        terminal_log(
            "DISKWALA LINK FOUND",
            f"Message ID: {source_message_id}",
            f"Link position: {position}",
        )
    now = utcnow()
    if post is None:
        post = SourcePost(
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            source_message_date=source_message_date or now,
            received_at=now,
            due_at=now,
            original_text_or_caption=text,
            cleaned_text=processed.cleaned_text,
            status=SourcePostStatus.SKIPPED if processed.skipped else SourcePostStatus.PENDING,
            completed_at=now if processed.skipped else None,
        )
        session.add(post)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            post = await session.scalar(
                select(SourcePost).where(
                    SourcePost.source_chat_id == source_chat_id,
                    SourcePost.source_message_id == source_message_id,
                )
            )
            if post is None:
                raise
            return post
    elif edited and post.status is SourcePostStatus.PENDING:
        post.original_text_or_caption = text
        post.cleaned_text = processed.cleaned_text
        post.last_error = None
        post.status = SourcePostStatus.SKIPPED if processed.skipped else SourcePostStatus.PENDING
        post.completed_at = now if processed.skipped else None
        await session.execute(delete(SourceLink).where(SourceLink.source_post_id == post.id))
        await session.flush()
    else:
        return post

    for position, original_url in enumerate(processed.original_diskwala_links, start=1):
        session.add(
            SourceLink(
                source_post_id=post.id,
                position=position,
                original_url=original_url,
                conversion_status=LinkStatus.PENDING,
            )
        )
    return post


async def next_due_posts(session: AsyncSession, limit: int = 10) -> list[SourcePost]:
    return list(
        await session.scalars(
            select(SourcePost)
            .where(SourcePost.status == SourcePostStatus.PENDING, SourcePost.due_at <= utcnow())
            .order_by(SourcePost.source_message_date, SourcePost.source_message_id)
            .limit(limit)
        )
    )


async def links_for_post(session: AsyncSession, source_post_id: int) -> list[SourceLink]:
    return list(
        await session.scalars(
            select(SourceLink)
            .where(SourceLink.source_post_id == source_post_id)
            .order_by(SourceLink.position)
        )
    )


async def retry_post(session: AsyncSession, source_post_id: int) -> bool:
    post = await session.get(SourcePost, source_post_id)
    if post is None or post.status not in {SourcePostStatus.FAILED, SourcePostStatus.COMPLETED}:
        return False
    post.status = SourcePostStatus.PENDING
    post.last_error = None
    post.completed_at = None
    links = await links_for_post(session, post.id)
    for link in links:
        if link.conversion_status is LinkStatus.FAILED:
            link.conversion_status = LinkStatus.PENDING
            link.last_error = None
    return True
