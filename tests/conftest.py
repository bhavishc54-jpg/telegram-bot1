from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, BotSetting


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as database_session:
        database_session.add_all(
            [
                BotSetting(key="free_daily_limit", value="2"),
                BotSetting(key="premium_daily_limit", value="4"),
            ]
        )
        await database_session.commit()
        yield database_session
