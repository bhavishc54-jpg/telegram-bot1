import logging

import pytest

from app.services.diskwala_client import (
    DiskWalaClient,
    DiskWalaConfigurationError,
    DiskWalaConversionError,
    _diskwala_links_from_converter_reply,
    convert_many_with_cache,
    convert_with_cache,
)


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.raw_text = text


class FakeConversation:
    def __init__(self, client: "FakeTelethonClient", reply: str | BaseException) -> None:
        self.client = client
        self.reply = reply
        self.consumed = False

    async def __aenter__(self) -> "FakeConversation":
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def send_message(self, text: str) -> None:
        self.client.sent.append(text)

    async def get_response(self) -> FakeResponse:
        if self.consumed:
            raise TimeoutError()
        self.consumed = True
        if isinstance(self.reply, BaseException):
            raise self.reply
        return FakeResponse(self.reply)


class FakeTelethonClient:
    def __init__(
        self,
        replies: list[str | BaseException],
        *,
        authorized: bool = True,
    ) -> None:
        self.replies = replies
        self.authorized = authorized
        self.sent: list[str] = []
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def get_entity(self, entity: str) -> str:
        return entity

    def conversation(self, _entity, *, timeout: int) -> FakeConversation:
        assert timeout > 0
        reply = self.replies.pop(0)
        return FakeConversation(self, reply)


async def test_diskwala_conversion_success(settings) -> None:
    client = FakeTelethonClient(["https://diskwala.com/affiliate"])
    converter = DiskWalaClient(settings, client)
    assert await converter.convert_link("https://diskwala.com/original") == (
        "https://diskwala.com/affiliate"
    )
    assert client.sent == ["https://diskwala.com/original"]


async def test_www_diskwala_input_converts(settings) -> None:
    client = FakeTelethonClient(["https://www.diskwala.com/converted"])
    converter = DiskWalaClient(settings, client)
    assert await converter.convert_link("https://www.diskwala.com/app/original") == (
        "https://www.diskwala.com/converted"
    )


async def test_converter_reply_keeps_only_diskwala_link(settings) -> None:
    reply = (
        "🔥 Converted!\n"
        "Join https://t.me/unwanted\n"
        "Your link: https://diskwala.com/my-affiliate\n"
        "Enjoy ✅"
    )
    client = FakeTelethonClient([reply])
    converter = DiskWalaClient(settings, client)
    assert await converter.convert_link("https://diskwala.com/original") == (
        "https://diskwala.com/my-affiliate"
    )


async def test_converter_timeout_retries_once(settings) -> None:
    client = FakeTelethonClient([TimeoutError(), "https://diskwala.com/retry-ok"])
    converter = DiskWalaClient(settings, client)
    assert await converter.convert_link("https://diskwala.com/original") == (
        "https://diskwala.com/retry-ok"
    )
    assert client.sent == ["https://diskwala.com/original", "https://diskwala.com/original"]


async def test_batch_conversion_sends_all_links_in_one_message(settings) -> None:
    reply = "\n".join(
        [
            "Promo https://t.me/backup",
            "https://diskwala.com/converted-1",
            "https://diskwala.com/converted-2",
        ]
    )
    client = FakeTelethonClient([reply])
    converter = DiskWalaClient(settings, client)

    converted = await converter.convert_links(
        ["https://diskwala.com/original-1", "https://diskwala.com/original-2"]
    )

    assert converted == ["https://diskwala.com/converted-1", "https://diskwala.com/converted-2"]
    assert client.sent == ["https://diskwala.com/original-1\nhttps://diskwala.com/original-2"]


async def test_batch_conversion_deduplicates_converter_links(settings) -> None:
    client = FakeTelethonClient(
        ["https://diskwala.com/converted\nhttps://t.me/backup\nhttps://diskwala.com/converted"]
    )
    converter = DiskWalaClient(settings, client)

    with pytest.raises(DiskWalaConversionError):
        await converter.convert_links(["https://diskwala.com/a", "https://diskwala.com/a"])


async def test_convert_many_cache_falls_back_and_skips_failed_link(session, settings) -> None:
    client = FakeTelethonClient(
        [
            "https://diskwala.com/only-one",
            "https://diskwala.com/a-ok",
            DiskWalaConversionError("single_failed"),
            "https://diskwala.com/c-ok",
        ]
    )
    converter = DiskWalaClient(settings, client)

    converted = await convert_many_with_cache(
        session,
        converter,
        ["https://diskwala.com/a", "https://diskwala.com/b", "https://diskwala.com/c"],
    )

    assert converted == ["https://diskwala.com/a-ok", "https://diskwala.com/c-ok"]


async def test_invalid_converter_reply_fails(settings) -> None:
    client = FakeTelethonClient(["Join https://t.me/channel\nhttps://example.com/no"])
    converter = DiskWalaClient(settings, client)
    with pytest.raises(DiskWalaConversionError):
        await converter.convert_link("https://diskwala.com/original")


async def test_missing_telethon_details_are_reported(settings) -> None:
    unconfigured = settings.__class__(
        bot_token="123:test",
        admin_user_id=1,
        source_channel_id=-100,
    )
    converter = DiskWalaClient(unconfigured, FakeTelethonClient(["https://diskwala.com/x"]))
    with pytest.raises(DiskWalaConfigurationError):
        await converter.convert_link("https://diskwala.com/original")


async def test_unauthorized_session_is_reported(settings) -> None:
    converter = DiskWalaClient(
        settings, FakeTelethonClient(["https://diskwala.com/x"], authorized=False)
    )
    with pytest.raises(DiskWalaConfigurationError):
        await converter.convert_link("https://diskwala.com/original")


async def test_conversion_cache_reused(session, settings) -> None:
    client = FakeTelethonClient(["https://diskwala.com/cached"])
    converter = DiskWalaClient(settings, client)
    assert await convert_with_cache(session, converter, "https://diskwala.com/original") == (
        "https://diskwala.com/cached"
    )
    await session.commit()
    assert await convert_with_cache(session, converter, "https://diskwala.com/original") == (
        "https://diskwala.com/cached"
    )
    assert client.sent == ["https://diskwala.com/original"]


async def test_api_secret_never_appears_in_logs(settings, caplog) -> None:
    client = FakeTelethonClient(["https://example.com/no"])
    converter = DiskWalaClient(settings, client)
    with caplog.at_level(logging.WARNING), pytest.raises(DiskWalaConversionError):
        await converter.convert_link("https://diskwala.com/original")
    assert settings.telegram_api_hash not in caplog.text
    assert settings.telegram_phone not in caplog.text


def test_reply_parser_deduplicates_diskwala_links() -> None:
    assert _diskwala_links_from_converter_reply(
        "Promo https://t.me/x\nhttps://diskwala.com/a\nhttps://DISKWALA.com/a.",
        ("diskwala.com",),
    ) == ("https://diskwala.com/a",)
