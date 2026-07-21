"""Print safe queue and subscriber health counts for the Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.database import create_engine_and_session
from app.models import (
    BroadcastDelivery,
    BroadcastJob,
    BroadcastStatus,
    DeliveryStatus,
    SourcePost,
    SourcePostStatus,
    Subscriber,
)


async def _main() -> None:
    logging.getLogger("app.config").setLevel(logging.ERROR)
    settings = Settings.from_env()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            active_subscribers = await session.scalar(
                select(func.count()).select_from(Subscriber).where(Subscriber.is_active.is_(True))
            )
            pending_source_posts = await session.scalar(
                select(func.count())
                .select_from(SourcePost)
                .where(SourcePost.status == SourcePostStatus.PENDING)
            )
            failed_source_posts = await session.scalar(
                select(func.count())
                .select_from(SourcePost)
                .where(SourcePost.status == SourcePostStatus.FAILED)
            )
            pending_broadcasts = await session.scalar(
                select(func.count())
                .select_from(BroadcastJob)
                .where(BroadcastJob.status == BroadcastStatus.PENDING)
            )
            pending_deliveries = await session.scalar(
                select(func.count())
                .select_from(BroadcastDelivery)
                .where(BroadcastDelivery.status == DeliveryStatus.PENDING)
            )
        print(f"ACTIVE SUBSCRIBERS: {active_subscribers or 0}")
        print(f"PENDING SOURCE POSTS: {pending_source_posts or 0}")
        print(f"FAILED SOURCE POSTS: {failed_source_posts or 0}")
        print(f"PENDING BROADCASTS: {pending_broadcasts or 0}")
        print(f"PENDING BROADCAST DELIVERIES: {pending_deliveries or 0}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
