"""Async SQLAlchemy engine and session setup."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.models import Base, BotSetting, PaymentProvider, Product

DEFAULT_SETTINGS = {
    "welcome_message": "Welcome! Send me a public DiskWala link and I will validate it safely.",
    "help_message": (
        "Send a complete https://diskwala.com link to validate it.\n\n"
        "Commands: /start, /help, /status, /account, /plans, /buy, /credits, /support"
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

DEFAULT_PRODUCTS = (
    {
        "product_code": "stars_10",
        "name": "Stars 10 credits",
        "description": "10 link-validation credits",
        "provider": PaymentProvider.TELEGRAM_STARS,
        "credits": 10,
        "stars_price": 10,
        "currency": "XTR",
        "is_active": True,
    },
    {
        "product_code": "stars_50",
        "name": "Stars 50 credits",
        "description": "50 link-validation credits",
        "provider": PaymentProvider.TELEGRAM_STARS,
        "credits": 50,
        "stars_price": 45,
        "currency": "XTR",
        "is_active": True,
    },
    {
        "product_code": "stars_100",
        "name": "Stars 100 credits",
        "description": "100 link-validation credits",
        "provider": PaymentProvider.TELEGRAM_STARS,
        "credits": 100,
        "stars_price": 80,
        "currency": "XTR",
        "is_active": True,
    },
    {
        "product_code": "paddle_starter",
        "name": "Paddle starter pack",
        "description": "Starter credit pack through Paddle",
        "provider": PaymentProvider.PADDLE,
        "credits": 25,
        "currency": "USD",
        "is_active": False,
    },
    {
        "product_code": "paddle_100",
        "name": "Paddle 100 credits",
        "description": "100 link-validation credits",
        "provider": PaymentProvider.PADDLE,
        "credits": 100,
        "currency": "USD",
        "is_active": False,
    },
    {
        "product_code": "paddle_500",
        "name": "Paddle 500 credits",
        "description": "500 link-validation credits",
        "provider": PaymentProvider.PADDLE,
        "credits": 500,
        "currency": "USD",
        "is_active": False,
    },
    {
        "product_code": "paddle_premium_monthly",
        "name": "Paddle monthly premium",
        "description": "30 days of Premium access",
        "provider": PaymentProvider.PADDLE,
        "premium_duration_days": 30,
        "currency": "USD",
        "is_active": False,
    },
    {
        "product_code": "paddle_premium_yearly",
        "name": "Paddle yearly premium",
        "description": "365 days of Premium access",
        "provider": PaymentProvider.PADDLE,
        "premium_duration_days": 365,
        "currency": "USD",
        "is_active": False,
    },
)


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
        for values in DEFAULT_PRODUCTS:
            existing = await session.scalar(
                select(Product).where(Product.product_code == values["product_code"])
            )
            if existing is None:
                session.add(Product(**values))
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
