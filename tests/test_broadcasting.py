from datetime import timedelta

from sqlalchemy import select
from telegram.error import Forbidden, RetryAfter

from app.models import (
    BroadcastDelivery,
    BroadcastStatus,
    DeliveryStatus,
    SourcePost,
    SourcePostStatus,
    Subscriber,
    utcnow,
)
from app.repositories.source_posts import create_or_update_source_post
from app.services.broadcast_service import (
    deliver_job,
    ensure_deliveries,
    get_or_create_broadcast_job,
)
from app.workers.queue_worker import QueueWorker


class FakeBot:
    def __init__(self, fail_for: set[int] | None = None, retry_once: bool = False) -> None:
        self.messages: list[tuple[int, str, dict]] = []
        self.fail_for = fail_for or set()
        self.retry_once = retry_once
        self._retried = False

    async def send_message(self, chat_id: int, text: str, **kwargs):
        if chat_id in self.fail_for:
            raise Forbidden("blocked")
        if self.retry_once and not self._retried:
            self._retried = True
            raise RetryAfter(0)
        self.messages.append((chat_id, text, kwargs))


async def _subscriber(session, user_id: int) -> None:
    session.add(
        Subscriber(
            user_id=user_id,
            chat_id=user_id,
            first_name=f"User {user_id}",
            is_active=True,
        )
    )


async def test_broadcast_text_only_and_no_media_is_sent(session_factory, settings) -> None:
    async with session_factory() as session:
        await _subscriber(session, 1)
        post = await create_or_update_source_post(
            session,
            settings,
            source_chat_id=settings.source_channel_id,
            source_message_id=1,
            source_message_date=utcnow(),
            text="Hello",
            entities=None,
        )
        job = await get_or_create_broadcast_job(session, post)
        await ensure_deliveries(session, job)
        await session.commit()
        job_id = job.id

    bot = FakeBot()
    result = await deliver_job(bot, session_factory, job_id, "Hello", rate_per_second=100)
    assert result.sent == 1
    assert bot.messages[0][0:2] == (1, "Hello")
    assert bot.messages[0][2]["parse_mode"] == "HTML"
    assert bot.messages[0][2]["disable_web_page_preview"] is True


async def test_blocked_user_marked_inactive(session_factory, settings) -> None:
    async with session_factory() as session:
        await _subscriber(session, 2)
        post = await create_or_update_source_post(
            session,
            settings,
            source_chat_id=settings.source_channel_id,
            source_message_id=2,
            source_message_date=utcnow(),
            text="Hello",
            entities=None,
        )
        job = await get_or_create_broadcast_job(session, post)
        await ensure_deliveries(session, job)
        await session.commit()
        job_id = job.id

    result = await deliver_job(
        FakeBot(fail_for={2}), session_factory, job_id, "Hello", rate_per_second=100
    )
    async with session_factory() as session:
        subscriber = await session.get(Subscriber, 2)
    assert result.blocked == 1
    assert subscriber is not None and subscriber.is_active is False


async def test_rate_limit_response_is_retried(session_factory, settings) -> None:
    async with session_factory() as session:
        await _subscriber(session, 3)
        post = await create_or_update_source_post(
            session,
            settings,
            source_chat_id=settings.source_channel_id,
            source_message_id=3,
            source_message_date=utcnow(),
            text="Hello",
            entities=None,
        )
        job = await get_or_create_broadcast_job(session, post)
        await ensure_deliveries(session, job)
        await session.commit()
        job_id = job.id
    bot = FakeBot(retry_once=True)
    result = await deliver_job(bot, session_factory, job_id, "Hello", rate_per_second=100)
    assert result.sent == 1
    assert bot.messages[0][0:2] == (3, "Hello")


async def test_one_failed_link_causes_complete_post_to_fail(session_factory, settings) -> None:
    class FailingClient:
        async def convert_links(self, _urls: list[str]) -> list[str]:
            from app.services.diskwala_client import DiskWalaConversionError

            raise DiskWalaConversionError("api_down")

        async def convert_link(self, _url: str) -> str:
            from app.services.diskwala_client import DiskWalaConversionError

            raise DiskWalaConversionError("api_down")

    async with session_factory() as session:
        post = await create_or_update_source_post(
            session,
            settings,
            source_chat_id=settings.source_channel_id,
            source_message_id=4,
            source_message_date=utcnow(),
            text="A https://diskwala.com/a\nB https://diskwala.com/b",
            entities=None,
        )
        post.due_at = utcnow() - timedelta(seconds=1)
        await session.commit()
    bot = FakeBot()
    worker = QueueWorker(bot, session_factory, settings, FailingClient())
    assert await worker.process_once() == 1
    async with session_factory() as session:
        post = await session.get(SourcePost, post.id)
        deliveries = list(await session.scalars(select(BroadcastDelivery)))
    assert post.status is SourcePostStatus.FAILED
    assert deliveries == []
    assert bot.messages == [
        (
            settings.admin_user_id,
            "Source post 1 failed during DiskWala conversion.\nError: api_down",
            {},
        )
    ]


async def test_source_post_broadcasts_only_converted_diskwala_link(
    session_factory, settings
) -> None:
    class ConverterClient:
        async def convert_links(self, original_urls: list[str]) -> list[str]:
            assert original_urls == ["https://diskwala.com/original"]
            return ["https://diskwala.com/converted"]

    async with session_factory() as session:
        await _subscriber(session, 6)
        post = await create_or_update_source_post(
            session,
            settings,
            source_chat_id=settings.source_channel_id,
            source_message_id=6,
            source_message_date=utcnow(),
            text=("Today ready\nhttps://diskwala.com/original\nhttps://t.me/remove-this"),
            entities=None,
        )
        post.due_at = utcnow() - timedelta(seconds=1)
        await session.commit()
    bot = FakeBot()
    worker = QueueWorker(bot, session_factory, settings, ConverterClient())
    assert await worker.process_once() == 1
    assert bot.messages[0][0] == 6
    assert bot.messages[0][1] == (
        f"{settings.broadcast_header}\n\n📥 Download Link\n\nhttps://diskwala.com/converted"
    )
    assert "Today ready" not in bot.messages[0][1]
    assert "original" not in bot.messages[0][1]
    assert "t.me" not in bot.messages[0][1]


async def test_broadcast_job_status_records_success(session_factory, settings) -> None:
    async with session_factory() as session:
        await _subscriber(session, 5)
        post = await create_or_update_source_post(
            session,
            settings,
            source_chat_id=settings.source_channel_id,
            source_message_id=5,
            source_message_date=utcnow(),
            text="Hello",
            entities=None,
        )
        job = await get_or_create_broadcast_job(session, post)
        await ensure_deliveries(session, job)
        await session.commit()
        job_id = job.id
    await deliver_job(FakeBot(), session_factory, job_id, "Hello", rate_per_second=100)
    async with session_factory() as session:
        job = await session.get(type(job), job_id)
        delivery = list(await session.scalars(select(BroadcastDelivery)))[0]
    assert job.status is BroadcastStatus.COMPLETED
    assert delivery.status is DeliveryStatus.SENT
