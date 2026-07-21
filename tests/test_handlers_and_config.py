from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from telegram import User as TelegramUser

from app.config import ConfigurationError, Settings
from app.handlers import admin, private_messages, subscribers
from app.models import SourcePost, SourcePostStatus, Subscriber, utcnow
from app.repositories.source_posts import create_or_update_source_post


class FakeMessage:
    def __init__(self, chat_id: int = 1, message_id: int = 10) -> None:
        self.chat_id = chat_id
        self.message_id = message_id
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_kwargs) -> None:
        self.replies.append(text)


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.copied: list[tuple[int, int, int]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    async def copy_message(self, chat_id: int, from_chat_id: int, message_id: int) -> None:
        self.copied.append((chat_id, from_chat_id, message_id))


def _context(settings, session_factory, *, args=None, bot=None):
    return SimpleNamespace(
        application=SimpleNamespace(
            bot_data={"settings": settings, "session_factory": session_factory}
        ),
        args=args or [],
        bot=bot or FakeBot(),
    )


def _update(user_id: int, message: FakeMessage | None = None, username: str | None = None):
    user = TelegramUser(id=user_id, first_name=f"User{user_id}", is_bot=False, username=username)
    msg = message or FakeMessage(chat_id=user_id)
    return SimpleNamespace(
        effective_user=user, effective_chat=SimpleNamespace(id=msg.chat_id), effective_message=msg
    )


async def test_user_start_creates_active_subscriber(session_factory, settings) -> None:
    message = FakeMessage(chat_id=10)
    await subscribers.start(_update(10, message, "alice"), _context(settings, session_factory))
    async with session_factory() as session:
        subscriber = await session.get(Subscriber, 10)
    assert subscriber is not None
    assert subscriber.is_active is True
    assert message.replies


async def test_existing_user_start_updates_without_duplication(session_factory, settings) -> None:
    message = FakeMessage(chat_id=11)
    context = _context(settings, session_factory)
    await subscribers.start(_update(11, message, "old"), context)
    await subscribers.start(_update(11, message, "new"), context)
    async with session_factory() as session:
        subscriber = await session.get(Subscriber, 11)
    assert subscriber is not None
    assert subscriber.username == "new"


async def test_stop_disables_broadcasts(session_factory, settings) -> None:
    context = _context(settings, session_factory)
    await subscribers.start(_update(12), context)
    await subscribers.stop(_update(12), context)
    async with session_factory() as session:
        subscriber = await session.get(Subscriber, 12)
    assert subscriber is not None
    assert subscriber.is_active is False


async def test_myid_shows_numeric_id(settings, session_factory) -> None:
    message = FakeMessage(chat_id=13)
    await subscribers.myid(_update(13, message), _context(settings, session_factory))
    assert message.replies == ["Your Telegram ID is 13."]


async def test_normal_user_cannot_run_admin_commands(settings, session_factory) -> None:
    message = FakeMessage(chat_id=14)
    await admin.stats(_update(14, message), _context(settings, session_factory))
    assert message.replies == ["Not allowed."]


async def test_admin_can_run_stats(session_factory, settings) -> None:
    message = FakeMessage(chat_id=settings.admin_user_id)
    await admin.stats(_update(settings.admin_user_id, message), _context(settings, session_factory))
    assert "Bot statistics" in message.replies[0]


async def test_pause_and_resume(session_factory, settings) -> None:
    context = _context(settings, session_factory)
    pause_message = FakeMessage(chat_id=settings.admin_user_id)
    await admin.pause(_update(settings.admin_user_id, pause_message), context)
    resume_message = FakeMessage(chat_id=settings.admin_user_id)
    await admin.resume(_update(settings.admin_user_id, resume_message), context)
    assert pause_message.replies == ["Broadcasts paused."]
    assert resume_message.replies == ["Broadcasts resumed."]


async def test_retry_failed_post(session_factory, settings) -> None:
    async with session_factory() as session:
        post = await create_or_update_source_post(
            session,
            settings,
            source_chat_id=settings.source_channel_id,
            source_message_id=50,
            source_message_date=utcnow(),
            text="https://diskwala.com/file",
            entities=None,
        )
        post.status = SourcePostStatus.FAILED
        await session.commit()
        post_id = post.id
    message = FakeMessage(chat_id=settings.admin_user_id)
    await admin.retry(
        _update(settings.admin_user_id, message),
        _context(settings, session_factory, args=[str(post_id)]),
    )
    async with session_factory() as session:
        post = await session.get(SourcePost, post_id)
    assert message.replies == ["Job queued for retry."]
    assert post is not None and post.status is SourcePostStatus.PENDING


async def test_private_text_goes_only_to_admin(settings, session_factory) -> None:
    bot = FakeBot()
    message = FakeMessage(chat_id=200, message_id=99)
    await private_messages.forward_private_message(
        _update(200, message, "bob"),
        _context(settings, session_factory, bot=bot),
    )
    assert bot.sent[0][0] == settings.admin_user_id
    assert bot.copied == [(settings.admin_user_id, 200, 99)]


async def test_admin_private_message_does_not_loop(settings, session_factory) -> None:
    bot = FakeBot()
    await private_messages.forward_private_message(
        _update(settings.admin_user_id, FakeMessage(chat_id=settings.admin_user_id)),
        _context(settings, session_factory, bot=bot),
    )
    assert bot.sent == []
    assert bot.copied == []


async def test_user_private_message_is_never_public_queue(settings, session_factory) -> None:
    bot = FakeBot()
    await private_messages.forward_private_message(
        _update(300, FakeMessage(chat_id=300, message_id=33)),
        _context(settings, session_factory, bot=bot),
    )
    async with session_factory() as session:
        queued = list(await session.scalars(select(SourcePost)))
    assert queued == []


def test_env_example_values_are_placeholders() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "8865412843:" not in text
    assert "your_botfather_token_here" in text


def test_owner_user_id_fallback(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.delenv("ADMIN_USER_ID", raising=False)
    monkeypatch.setenv("OWNER_USER_ID", "42")
    settings = Settings.from_env(env_file=".missing-env")
    assert settings.admin_user_id == 42


def test_invalid_admin_id_fails(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setenv("ADMIN_USER_ID", "not-number")
    with pytest.raises(ConfigurationError):
        Settings.from_env(env_file=".missing-env")


def test_nonzero_post_delay_fails_loudly(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setenv("ADMIN_USER_ID", "42")
    monkeypatch.setenv("POST_DELAY_MINUTES", "20")
    monkeypatch.delenv("BROADCAST_DELAY_MINUTES", raising=False)

    with pytest.raises(ConfigurationError, match="POST_DELAY_MINUTES must be 0"):
        Settings.from_env(env_file=".missing-env")


def test_legacy_broadcast_delay_fails_loudly(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setenv("ADMIN_USER_ID", "42")
    monkeypatch.setenv("POST_DELAY_MINUTES", "0")
    monkeypatch.setenv("BROADCAST_DELAY_MINUTES", "20")

    with pytest.raises(ConfigurationError, match="BROADCAST_DELAY_MINUTES"):
        Settings.from_env(env_file=".missing-env")
