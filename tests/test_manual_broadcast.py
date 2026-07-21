from types import SimpleNamespace

from sqlalchemy import select
from telegram import User as TelegramUser

from app.handlers import admin, private_messages
from app.models import SourcePost, Subscriber
from app.workers.queue_worker import QueueWorker


class FakeMessage:
    def __init__(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str | None = None,
        caption: str | None = None,
        reply_to_message=None,
    ) -> None:
        self.chat_id = chat_id
        self.message_id = message_id
        self.text = text
        self.caption = caption
        self.reply_to_message = reply_to_message
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_kwargs) -> None:
        self.replies.append(text)


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.copied: list[tuple[int, int, int]] = []

    async def send_message(self, chat_id: int, text: str, **_kwargs) -> None:
        self.sent.append((chat_id, text))

    async def copy_message(self, chat_id: int, from_chat_id: int, message_id: int) -> None:
        self.copied.append((chat_id, from_chat_id, message_id))


class PassthroughDiskWalaClient:
    async def convert_links(self, original_urls: list[str]) -> list[str]:
        return original_urls


def _context(settings, session_factory, *, args=None, bot=None):
    return SimpleNamespace(
        application=SimpleNamespace(
            bot_data={"settings": settings, "session_factory": session_factory}
        ),
        args=args or [],
        bot=bot or FakeBot(),
    )


def _update(user_id: int, message: FakeMessage):
    user = TelegramUser(id=user_id, first_name=f"User{user_id}", is_bot=False)
    return SimpleNamespace(
        effective_user=user,
        effective_chat=SimpleNamespace(id=message.chat_id),
        effective_message=message,
    )


async def _add_subscribers(session_factory, *user_ids: int) -> None:
    async with session_factory() as session:
        for user_id in user_ids:
            session.add(
                Subscriber(
                    user_id=user_id,
                    chat_id=user_id,
                    first_name=f"User {user_id}",
                    is_active=True,
                )
            )
        await session.commit()


async def _process_queued_broadcast(session_factory, settings, bot: FakeBot) -> None:
    worker = QueueWorker(bot, session_factory, settings, PassthroughDiskWalaClient())
    await worker.process_once()


async def test_admin_can_broadcast_text(session_factory, settings) -> None:
    await _add_subscribers(session_factory, 10, 11)
    bot = FakeBot()
    message = FakeMessage(chat_id=settings.admin_user_id, message_id=1)
    await admin.broadcast(
        _update(settings.admin_user_id, message),
        _context(settings, session_factory, args=["Hello", "everyone"], bot=bot),
    )
    assert "Active subscribers: 2" in message.replies[0]
    assert "Broadcast job ID:" in message.replies[0]
    assert "Status: pending" in message.replies[0]

    await _process_queued_broadcast(session_factory, settings, bot)
    assert bot.sent == [(10, "Hello everyone"), (11, "Hello everyone")]


async def test_normal_user_cannot_broadcast(session_factory, settings) -> None:
    await _add_subscribers(session_factory, 12)
    bot = FakeBot()
    message = FakeMessage(chat_id=99, message_id=2)
    await admin.broadcast(
        _update(99, message),
        _context(settings, session_factory, args=["Nope"], bot=bot),
    )
    assert message.replies == ["Not allowed."]
    async with session_factory() as session:
        queued = list(await session.scalars(select(SourcePost)))
    assert queued == []


async def test_reply_broadcast_works(session_factory, settings) -> None:
    await _add_subscribers(session_factory, 13)
    bot = FakeBot()
    replied = FakeMessage(chat_id=settings.admin_user_id, message_id=3, text="Reply text")
    command = FakeMessage(
        chat_id=settings.admin_user_id,
        message_id=4,
        text="/broadcast",
        reply_to_message=replied,
    )
    await admin.broadcast(
        _update(settings.admin_user_id, command),
        _context(settings, session_factory, bot=bot),
    )
    await _process_queued_broadcast(session_factory, settings, bot)
    assert bot.sent == [(13, "Reply text")]


async def test_media_only_reply_is_rejected(session_factory, settings) -> None:
    await _add_subscribers(session_factory, 14)
    bot = FakeBot()
    replied = FakeMessage(chat_id=settings.admin_user_id, message_id=5)
    command = FakeMessage(
        chat_id=settings.admin_user_id,
        message_id=6,
        text="/broadcast",
        reply_to_message=replied,
    )
    await admin.broadcast(
        _update(settings.admin_user_id, command),
        _context(settings, session_factory, bot=bot),
    )
    assert command.replies == ["There is no text to broadcast."]
    async with session_factory() as session:
        queued = list(await session.scalars(select(SourcePost)))
    assert queued == []


async def test_caption_only_reply_broadcasts_text_only(session_factory, settings) -> None:
    await _add_subscribers(session_factory, 15)
    bot = FakeBot()
    replied = FakeMessage(
        chat_id=settings.admin_user_id,
        message_id=7,
        caption="Caption text only",
    )
    command = FakeMessage(
        chat_id=settings.admin_user_id,
        message_id=8,
        text="/broadcast",
        reply_to_message=replied,
    )
    await admin.broadcast(
        _update(settings.admin_user_id, command),
        _context(settings, session_factory, bot=bot),
    )
    await _process_queued_broadcast(session_factory, settings, bot)
    assert bot.sent == [(15, "Caption text only")]
    assert bot.copied == []


async def test_normal_admin_private_message_without_broadcast_is_not_public(
    session_factory, settings
) -> None:
    await _add_subscribers(session_factory, 16)
    bot = FakeBot()
    message = FakeMessage(chat_id=settings.admin_user_id, message_id=9, text="Do not publish")
    await private_messages.forward_private_message(
        _update(settings.admin_user_id, message),
        _context(settings, session_factory, bot=bot),
    )
    await _process_queued_broadcast(session_factory, settings, bot)
    assert bot.sent == []
    async with session_factory() as session:
        queued = list(await session.scalars(select(SourcePost)))
    assert queued == []
