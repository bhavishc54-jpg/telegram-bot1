from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from app.config import Settings
from app.models import PrivateRelay, ScheduledDeletion, utcnow

logger = logging.getLogger(__name__)


def _dependencies(
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[Settings, async_sessionmaker[AsyncSession]]:
    return context.application.bot_data["settings"], context.application.bot_data["session_factory"]


def _user_id_from_replied_text(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"User ID:\s*(\d+)", text)
    return int(match.group(1)) if match else None


async def _schedule(
    session: AsyncSession,
    chat_id: int,
    message_id: int,
    delete_at,
    kind: str,
) -> None:
    row = await session.scalar(
        select(ScheduledDeletion).where(
            ScheduledDeletion.chat_id == chat_id,
            ScheduledDeletion.message_id == message_id,
        )
    )
    if row is None:
        session.add(
            ScheduledDeletion(
                chat_id=chat_id,
                message_id=message_id,
                delete_at=delete_at,
                kind=kind,
            )
        )
    else:
        row.delete_at = delete_at
        row.kind = kind
        row.deleted_at = None


async def reply_to_private_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    settings, session_factory = _dependencies(context)
    if user.id != settings.admin_user_id or message.reply_to_message is None:
        return

    replied = message.reply_to_message
    relay: PrivateRelay | None = None

    async with session_factory() as session:
        relay = await session.scalar(
            select(PrivateRelay)
            .where(
                or_(
                    PrivateRelay.admin_header_message_id == replied.message_id,
                    PrivateRelay.admin_copy_message_id == replied.message_id,
                )
            )
            .order_by(PrivateRelay.id.desc())
        )

    target_user_id = relay.user_chat_id if relay else _user_id_from_replied_text(replied.text)
    if target_user_id is None and replied.reply_to_message is not None:
        target_user_id = _user_id_from_replied_text(replied.reply_to_message.text)

    if target_user_id is None:
        await message.reply_text(
            "Could not find the user. Please reply directly to the user's information or copied message."
        )
        return

    try:
        admin_header = "ADMIN Msg \U0001F447"

        if message.text:
            sent_reply = await context.bot.send_message(
                chat_id=target_user_id,
                text=f"{admin_header}\n\n{message.text}",
            )
        else:
            original_caption = message.caption or ""
            formatted_caption = (
                f"{admin_header}\n\n{original_caption}"
                if original_caption
                else admin_header
            )
            sent_reply = await context.bot.copy_message(
                chat_id=target_user_id,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
                caption=formatted_caption,
            )
        notice = await context.bot.send_message(
            chat_id=target_user_id,
            text="\u26a0\ufe0f This reply will be deleted automatically after 24 hours.",
        )

        now = utcnow()
        async with session_factory() as session:
            await _schedule(
                session,
                target_user_id,
                sent_reply.message_id,
                now + timedelta(hours=24),
                "admin_reply_to_user",
            )
            await _schedule(
                session,
                target_user_id,
                notice.message_id,
                now + timedelta(hours=24),
                "reply_expiry_notice",
            )

            if relay is not None:
                stored = await session.get(PrivateRelay, relay.id)
                if stored is not None:
                    stored.replied_at = now
                    await _schedule(
                        session,
                        settings.admin_user_id,
                        stored.admin_header_message_id,
                        now + timedelta(hours=1),
                        "admin_private_header",
                    )
                    await _schedule(
                        session,
                        settings.admin_user_id,
                        stored.admin_copy_message_id,
                        now + timedelta(hours=1),
                        "admin_private_copy",
                    )
            await session.commit()

        await message.reply_text(
            f"\u2705 Reply sent successfully to user ID: {target_user_id}\n"
            "Admin copies will be deleted after 1 hour."
        )
    except Exception as exc:
        logger.warning("Could not send admin reply to user %s: %s", target_user_id, type(exc).__name__)
        await message.reply_text(
            "\u274c Reply could not be sent. The user may have blocked the bot or deleted the chat."
        )


async def forward_private_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    settings, session_factory = _dependencies(context)
    if user.id == settings.admin_user_id:
        return

    username = f"@{user.username}" if user.username else "Not available"
    full_name = user.full_name or user.first_name or "Not available"
    header = (
        "\U0001F4E9 New private message\n\n"
        f"Name: {full_name}\n"
        f"Username: {username}\n"
        f"User ID: {user.id}\n\n"
        "Reply directly to this information message or the copied message below."
    )

    try:
        admin_header = await context.bot.send_message(
            chat_id=settings.admin_user_id,
            text=header,
        )
        copied_message = await context.bot.copy_message(
            chat_id=settings.admin_user_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
            reply_to_message_id=admin_header.message_id,
        )
        contact_reply = await message.reply_text(
            "\U0001F44B Thank you for your message.\n\n"
            "For direct contact, please message the admin:\n"
            "\U0001F449 @EasyM_text\n\n"
            "\u26a0\ufe0f Your message and this notice will be deleted automatically after 24 hours."
        )

        delete_at = utcnow() + timedelta(hours=24)
        async with session_factory() as session:
            session.add(
                PrivateRelay(
                    user_chat_id=message.chat_id,
                    user_message_id=message.message_id,
                    admin_header_message_id=admin_header.message_id,
                    admin_copy_message_id=copied_message.message_id,
                )
            )
            for chat_id, message_id, kind in (
                (message.chat_id, message.message_id, "user_private_message"),
                (message.chat_id, contact_reply.message_id, "contact_auto_reply"),
                (settings.admin_user_id, admin_header.message_id, "admin_private_header"),
                (settings.admin_user_id, copied_message.message_id, "admin_private_copy"),
            ):
                await _schedule(session, chat_id, message_id, delete_at, kind)
            await session.commit()
    except Exception as exc:
        logger.warning("Could not forward private user message: %s", type(exc).__name__)


def handlers() -> list[object]:
    private_non_command = filters.ChatType.PRIVATE & ~filters.COMMAND
    return [
        MessageHandler(private_non_command & filters.REPLY, reply_to_private_user),
        MessageHandler(private_non_command, forward_private_message),
    ]
