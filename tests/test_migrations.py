import sqlite3

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.database import create_engine_and_session, initialize_database
from app.migrations import run_migrations
from app.models import Product


def sqlite_url(path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_migration_upgrades_existing_database(tmp_path) -> None:
    database = tmp_path / "existing.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE users (telegram_id BIGINT PRIMARY KEY)")
    run_migrations(sqlite_url(database))
    with sqlite3.connect(database) as connection:
        user_columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "credits" in user_columns
    assert {"products", "payments", "processed_payment_events", "pending_requests"} <= tables


@pytest.mark.asyncio
async def test_default_products_are_created(tmp_path) -> None:
    config = Settings(
        bot_token="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789",
        owner_user_id=1,
        database_url=sqlite_url(tmp_path / "products.db"),
    )
    engine, factory = create_engine_and_session(config)
    await initialize_database(engine, factory, config)
    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(Product))
    await engine.dispose()
    assert count == 8
