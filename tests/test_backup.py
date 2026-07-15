import sqlite3

from scripts.backup_database import create_backup, sqlite_path_from_url


def test_sqlite_backup(tmp_path) -> None:
    source = tmp_path / "bot.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('safe')")
    destination = create_backup(source, tmp_path / "backups")
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("safe",)


def test_database_url_to_path() -> None:
    assert sqlite_path_from_url("sqlite:///data/bot.db").name == "bot.db"
