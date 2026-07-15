import pytest

from app.config import ConfigurationError, Settings


def test_required_environment_validation(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("OWNER_USER_ID", raising=False)
    with pytest.raises(ConfigurationError, match="BOT_TOKEN"):
        Settings.from_env(tmp_path / "missing.env")


def test_owner_id_must_be_positive(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("OWNER_USER_ID", "0")
    with pytest.raises(ConfigurationError, match="positive integer"):
        Settings.from_env(tmp_path / "missing.env")
