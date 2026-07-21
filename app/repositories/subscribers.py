"""Subscriber persistence helpers."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import User as TelegramUser

from app.models import Subscriber, utcnow


async def upsert_subscriber(
    session: AsyncSession,
    telegram_user: TelegramUser,
    chat_id: int,
) -> Subscriber:
    subscriber = await session.get(Subscriber, telegram_user.id)
    now = utcnow()
    if subscriber is None:
        subscriber = Subscriber(
            user_id=telegram_user.id,
            chat_id=chat_id,
            username=telegram_user.username,
            first_name=telegram_user.first_name or "",
            last_name=telegram_user.last_name,
            started_at=now,
            last_seen_at=now,
            is_active=True,
            blocked_at=None,
        )
        session.add(subscriber)
        return subscriber
    subscriber.chat_id = chat_id
    subscriber.username = telegram_user.username
    subscriber.first_name = telegram_user.first_name or ""
    subscriber.last_name = telegram_user.last_name
    subscriber.last_seen_at = now
    subscriber.is_active = True
    subscriber.blocked_at = None
    return subscriber


async def mark_inactive(session: AsyncSession, user_id: int, *, blocked: bool = False) -> None:
    subscriber = await session.get(Subscriber, user_id)
    if subscriber is None:
        return
    subscriber.is_active = False
    subscriber.last_seen_at = utcnow()
    if blocked:
        subscriber.blocked_at = utcnow()


async def active_subscribers(session: AsyncSession) -> list[Subscriber]:
    return list(
        await session.scalars(
            select(Subscriber).where(Subscriber.is_active.is_(True)).order_by(Subscriber.user_id)
        )
    )


async def subscriber_counts(session: AsyncSession) -> tuple[int, int, int]:
    total = await session.scalar(select(func.count()).select_from(Subscriber)) or 0
    active = (
        await session.scalar(
            select(func.count()).select_from(Subscriber).where(Subscriber.is_active.is_(True))
        )
        or 0
    )
    inactive = total - active
    return total, active, inactive
