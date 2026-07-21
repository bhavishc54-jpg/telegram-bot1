from dataclasses import replace
from types import SimpleNamespace

from telegram.ext import MessageHandler

from app.handlers import source_channel
from app.main import POLLING_ALLOWED_UPDATES, build_application, on_error
from app.models import SourceLink, SourcePost, SourcePostStatus


def test_polling_requests_required_update_types() -> None:
    assert POLLING_ALLOWED_UPDATES == ["message", "channel_post", "edited_channel_post"]


def test_channel_post_handlers_are_registered(settings) -> None:
    application = build_application(settings)
    registered_handlers = [
        handler
        for group_handlers in application.handlers.values()
        for handler in group_handlers
        if isinstance(handler, MessageHandler)
    ]
    callbacks = {handler.callback for handler in registered_handlers}
    assert source_channel.channel_post in callbacks
    assert source_channel.edited_channel_post in callbacks


async def test_missing_source_channel_id_prints_detection(
    session_factory, settings, capsys
) -> None:
    missing_source_settings = replace(settings, source_channel_id=None)
    await source_channel._handle_channel_message(
        _channel_message(chat_id=-100777, title="Movies", message_id=42),
        _context(missing_source_settings, session_factory),
        edited=False,
    )
    output = capsys.readouterr().out
    assert "SOURCE CHANNEL DETECTED" in output
    assert "Channel title: Movies" in output
    assert "Channel ID: -100777" in output
    assert "Message ID: 42" in output
    assert missing_source_settings.bot_token not in output
    assert missing_source_settings.diskwala_api_key not in output


async def test_matching_source_channel_prints_accepted(session_factory, settings, capsys) -> None:
    await source_channel._handle_channel_message(
        _channel_message(
            chat_id=settings.source_channel_id,
            title="Source",
            message_id=43,
            text="Hello https://diskwala.com/file",
        ),
        _context(settings, session_factory),
        edited=False,
    )
    output = capsys.readouterr().out
    assert "SOURCE POST ACCEPTED" in output
    assert f"Channel ID: {settings.source_channel_id}" in output
    assert "Message ID: 43" in output
    assert "Broadcasting immediately..." in output
    async with session_factory() as session:
        post = await session.get(SourcePost, 1)
    assert post is not None


async def test_real_source_channel_handler_creates_pending_source_post(
    session_factory, settings, capsys
) -> None:
    real_channel_settings = replace(settings, source_channel_id=-1003909413317)
    await source_channel._handle_channel_message(
        _channel_message(
            chat_id=-1003909413317,
            title="Source",
            message_id=1603,
            text=("Final converter test\nhttps://www.diskwala.com/app/6a58893906ba7ea03d3163c3"),
        ),
        _context(real_channel_settings, session_factory),
        edited=False,
    )
    output = capsys.readouterr().out
    assert "SOURCE CHANNEL MATCHED" in output
    assert "SOURCE DATABASE COMMIT FINISHED" in output
    assert "SOURCE POST SAVED" in output
    async with session_factory() as session:
        post = await session.get(SourcePost, 1)
        link = await session.get(SourceLink, 1)
    assert post is not None
    assert post.source_chat_id == -1003909413317
    assert post.source_message_id == 1603
    assert post.status is SourcePostStatus.PENDING
    assert link is not None
    assert link.source_post_id == post.id
    assert link.original_url == "https://www.diskwala.com/app/6a58893906ba7ea03d3163c3"


async def test_non_matching_source_channel_prints_ignored(
    session_factory, settings, capsys
) -> None:
    await source_channel._handle_channel_message(
        _channel_message(chat_id=-100999, title="Other", message_id=44),
        _context(settings, session_factory),
        edited=False,
    )
    output = capsys.readouterr().out
    assert "SOURCE POST IGNORED" in output
    assert "Received channel ID: -100999" in output
    assert f"Configured source channel ID: {settings.source_channel_id}" in output


async def test_channel_post_error_does_not_reply_to_channel() -> None:
    message = SimpleNamespace(replies=[], reply_text=_record_reply)
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(type="channel"),
    )
    context = SimpleNamespace(error=RuntimeError("boom"))
    await on_error(update, context)
    assert message.replies == []


async def _record_reply(text: str, **_kwargs) -> None:
    # Bound dynamically through SimpleNamespace in the test above.
    raise AssertionError(f"Unexpected channel reply: {text}")


def _context(settings, session_factory):
    return SimpleNamespace(
        application=SimpleNamespace(
            bot_data={"settings": settings, "session_factory": session_factory}
        )
    )


def _channel_message(
    *,
    chat_id: int,
    title: str,
    message_id: int,
    text: str = "Hello",
):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, title=title, type="channel"),
        from_user=None,
        message_id=message_id,
        text=text,
        caption=None,
        entities=None,
        caption_entities=None,
        date=None,
    )
