"""Async SQLAlchemy engine and session setup."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.models import Base, BotSetting

DEFAULT_SETTINGS = {
    "welcome_message": "Welcome! Send me a public DiskWala link and I will validate it safely.",
    "help_message": (
        "Send a complete https://diskwala.com link to validate it.\n\n"
        "Commands: /start, /help, /status, /account, /plans, /support"
    ),
    "support_username": "",
    "free_daily_limit": "5",
    "premium_daily_limit": "100",
    "sponsored_messages_enabled": "true",
    "maintenance_enabled": "false",
    "maintenance_message": "The bot is under maintenance. Please try again later.",
    "premium_plan_name": "Premium",
    "premium_price_text": "Coming soon",
}


def create_engine_and_session(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    _ensure_sqlite_parent(settings.database_url)
    engine = create_async_engine(settings.async_database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def initialize_database(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    values = dict(DEFAULT_SETTINGS)
    values.update(
        {
            "support_username": settings.support_username,
            "free_daily_limit": str(settings.free_daily_limit),
            "premium_daily_limit": str(settings.premium_daily_limit),
        }
    )
    async with session_factory() as session:
        for key, value in values.items():
            if await session.get(BotSetting, key) is None:
                session.add(BotSetting(key=key, value=value))
        await session.commit()


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _ensure_sqlite_parent(database_url: str) -> None:
    prefixes = ("sqlite:///", "sqlite+aiosqlite:///")
    for prefix in prefixes:
        if database_url.startswith(prefix):
            path = Path(database_url.removeprefix(prefix))
            if str(path) != ":memory:":
                path.parent.mkdir(parents=True, exist_ok=True)
            return
