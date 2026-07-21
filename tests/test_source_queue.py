from datetime import timedelta

from sqlalchemy import select

from app.models import SourceLink, SourcePost, SourcePostStatus, utcnow
from app.repositories.source_posts import create_or_update_source_post, next_due_posts


async def test_source_channel_is_accepted_and_other_channel_ignored_by_caller(
    session, settings
) -> None:
    post = await create_or_update_source_post(
        session,
        settings,
        source_chat_id=settings.source_channel_id,
        source_message_id=1,
        source_message_date=utcnow(),
        text="https://diskwala.com/file",
        entities=None,
    )
    await session.commit()
    assert post.status is SourcePostStatus.PENDING
    assert post.source_chat_id == settings.source_channel_id


async def test_new_source_post_is_immediately_eligible(session, settings) -> None:
    post = await create_or_update_source_post(
        session,
        settings,
        source_chat_id=settings.source_channel_id,
        source_message_id=101,
        source_message_date=utcnow(),
        text="Immediate https://diskwala.com/file",
        entities=None,
    )
    await session.commit()

    due_posts = await next_due_posts(session, limit=10)

    assert post.id in {due_post.id for due_post in due_posts}
    assert post.due_at == post.received_at


async def test_duplicate_update_does_not_create_second_job(session, settings) -> None:
    kwargs = dict(
        source_chat_id=settings.source_channel_id,
        source_message_id=2,
        source_message_date=utcnow(),
        text="https://diskwala.com/file",
        entities=None,
    )
    first = await create_or_update_source_post(session, settings, **kwargs)
    second = await create_or_update_source_post(session, settings, **kwargs)
    await session.commit()
    count = await session.scalar(select(SourcePost).where(SourcePost.source_message_id == 2))
    assert first.id == second.id
    assert count is not None


async def test_edited_pending_post_updates_same_job(session, settings) -> None:
    post = await create_or_update_source_post(
        session,
        settings,
        source_chat_id=settings.source_channel_id,
        source_message_id=3,
        source_message_date=utcnow(),
        text="Old https://diskwala.com/old",
        entities=None,
    )
    original_due = post.due_at
    edited = await create_or_update_source_post(
        session,
        settings,
        source_chat_id=settings.source_channel_id,
        source_message_id=3,
        source_message_date=utcnow(),
        text="New https://diskwala.com/new",
        entities=None,
        edited=True,
    )
    await session.commit()
    links = list(
        await session.scalars(select(SourceLink).where(SourceLink.source_post_id == post.id))
    )
    assert edited.id == post.id
    assert edited.due_at == original_due
    assert edited.cleaned_text == "New"
    assert [link.original_url for link in links] == ["https://diskwala.com/new"]


async def test_edit_after_broadcast_does_not_rebroadcast(session, settings) -> None:
    post = await create_or_update_source_post(
        session,
        settings,
        source_chat_id=settings.source_channel_id,
        source_message_id=4,
        source_message_date=utcnow(),
        text="Done https://diskwala.com/old",
        entities=None,
    )
    post.status = SourcePostStatus.COMPLETED
    await session.commit()
    edited = await create_or_update_source_post(
        session,
        settings,
        source_chat_id=settings.source_channel_id,
        source_message_id=4,
        source_message_date=utcnow(),
        text="Changed https://diskwala.com/new",
        entities=None,
        edited=True,
    )
    assert edited.cleaned_text == "Done"
    assert edited.status is SourcePostStatus.COMPLETED


async def test_media_only_post_marked_skipped(session, settings) -> None:
    post = await create_or_update_source_post(
        session,
        settings,
        source_chat_id=settings.source_channel_id,
        source_message_id=5,
        source_message_date=utcnow(),
        text="",
        entities=None,
    )
    assert post.status is SourcePostStatus.SKIPPED


async def test_queue_survives_restart_and_orders_by_source_message(
    session_factory, settings
) -> None:
    source_date = utcnow()
    async with session_factory() as session:
        for message_id in (20, 10):
            post = await create_or_update_source_post(
                session,
                settings,
                source_chat_id=settings.source_channel_id,
                source_message_id=message_id,
                source_message_date=source_date,
                text=f"https://diskwala.com/{message_id}",
                entities=None,
            )
            post.due_at = utcnow() - timedelta(seconds=1)
        await session.commit()
    async with session_factory() as session:
        due = await next_due_posts(session, limit=10)
    assert [post.source_message_id for post in due] == [10, 20]
