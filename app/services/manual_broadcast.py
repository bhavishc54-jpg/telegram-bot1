"""Admin-created text-only manual broadcasts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import SourcePost, SourcePostStatus, utcnow
from app.repositories.subscribers import active_subscribers
from app.services.broadcast_service import ensure_deliveries, get_or_create_broadcast_job


@dataclass(frozen=True, slots=True)
class ManualBroadcastQueued:
    job_id: int
    active_subscribers: int
    status: str


async def queue_manual_broadcast(
    session: AsyncSession,
    settings: Settings,
    *,
    text: str,
    command_message_id: int,
) -> ManualBroadcastQueued:
    now = utcnow()
    post = SourcePost(
        source_chat_id=settings.admin_user_id,
        source_message_id=command_message_id,
        original_text_or_caption=text,
        cleaned_text=text,
        received_at=now,
        source_message_date=now,
        due_at=now,
        status=SourcePostStatus.PENDING,
    )
    session.add(post)
    await session.flush()
    job = await get_or_create_broadcast_job(session, post)
    deliveries = await ensure_deliveries(session, job)
    active_count = len(await active_subscribers(session)) if not deliveries else len(deliveries)
    return ManualBroadcastQueued(
        job_id=job.id,
        active_subscribers=active_count,
        status=job.status.value,
    )
