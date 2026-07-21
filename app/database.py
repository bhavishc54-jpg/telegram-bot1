"""Async SQLAlchemy engine, session setup, and startup defaults."""

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
    "broadcast_paused": "false",
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
    _settings: Settings,
) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        for key, value in DEFAULT_SETTINGS.items():
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
