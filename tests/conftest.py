from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.models import Base, BotSetting


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bot_token="123:test",
        admin_user_id=100,
        source_channel_id=-100123,
        diskwala_api_base_url="https://api.diskwala.example",
        diskwala_api_endpoint="/convert",
        diskwala_api_key="secret-key",
        diskwala_api_response_field="data.url",
        post_delay_minutes=0,
        telegram_api_id=123456,
        telegram_api_hash="api-hash",
        telegram_phone="+10000000000",
        telethon_session_name="test-session",
        diskwala_converter_bot="DW2DW_LinkConverterBot",
        diskwala_converter_timeout_seconds=1,
    )


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
    async with factory() as session:
        session.add(BotSetting(key="broadcast_paused", value="false"))
        await session.commit()
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as database_session:
        yield database_session
