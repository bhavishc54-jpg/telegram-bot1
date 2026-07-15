"""Alembic migration runner used by startup and command-line workflows."""

from alembic.config import Config

from alembic import command


def run_migrations(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
