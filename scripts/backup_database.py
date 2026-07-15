"""Create a consistent SQLite backup without stopping the bot."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv


def sqlite_path_from_url(database_url: str) -> Path:
    for prefix in ("sqlite:///", "sqlite+aiosqlite:///"):
        if database_url.startswith(prefix):
            path = Path(database_url.removeprefix(prefix)).resolve()
            if str(path).endswith(":memory:"):
                raise ValueError("An in-memory database cannot be backed up.")
            return path
    raise ValueError("The backup tool supports only local SQLite database URLs.")


def create_backup(source: Path, backup_directory: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Database not found: {source}")
    backup_directory.mkdir(parents=True, exist_ok=True)
    destination = backup_directory / f"bot-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"
    with (
        sqlite3.connect(source) as source_connection,
        sqlite3.connect(destination) as destination_connection,
    ):
        source_connection.backup(destination_connection)
    return destination


def main() -> None:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "sqlite:///data/bot.db")
    destination = create_backup(sqlite_path_from_url(database_url), Path("data/backups"))
    print(f"Backup created: {destination}")


if __name__ == "__main__":
    main()
