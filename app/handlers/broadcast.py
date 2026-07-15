"""Owner-confirmed, multi-format broadcast conversation."""

from __future__ import annotations

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.handlers.admin import _audit, _authorized
from app.models import BroadcastLog, User, utcnow
from app.services.ad_service import validate_ad_content
from app.services.broadcast_service import BroadcastPayload, deliver_broadcast

WAIT_CONTENT, WAIT_BUTTON, WAIT_CONFIRM = range(3)


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✖ Cancel", callback_data="broadcast:cancel")]]
    )


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context, owner_only=True) or not update.effective_message:
        return ConversationHandler.END
    context.user_data.pop("broadcast", None)
    await update.effective_message.reply_text(
        "Send the text, photo, video, or document to broadcast. "
        "Nothing will be sent without preview and confirmation.",
        reply_markup=_cancel_keyboard(),
    )
    return WAIT_CONTENT


async def capture_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context, owner_only=True) or not update.effective_message:
        return ConversationHandler.END
    message = update.effective_message
    if message.text:
        content_type = "text"
    elif message.photo:
        content_type = "photo"
    elif message.video:
        content_type = "video"
    elif message.document:
        content_type = "document"
    else:
        await message.reply_text("Unsupported content. Send text, a photo, a video, or a document.")
        return WAIT_CONTENT
    context.user_data["broadcast"] = {
        "source_chat_id": message.chat_id,
        "source_message_id": message.message_id,
        "content_type": content_type,
    }
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("No button", callback_data="broadcast:skip_button")],
            [InlineKeyboardButton("✖ Cancel", callback_data="broadcast:cancel")],
        ]
    )
    await message.reply_text(
        "Optional: send BUTTON TEXT | https://example.com, or choose No button.",
        reply_markup=keyboard,
    )
    return WAIT_BUTTON


async def capture_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context, owner_only=True) or not update.effective_message:
        return ConversationHandler.END
    fields = [part.strip() for part in (update.effective_message.text or "").split("|", 1)]
    if len(fields) != 2:
        await update.effective_message.reply_text("Use BUTTON TEXT | https://example.com")
        return WAIT_BUTTON
    button_text, button_url = fields
    try:
        validate_ad_content("Broadcast button", "Safe broadcast", button_url)
        if not button_text or len(button_text) > 64:
            raise ValueError("Button text must contain 1 to 64 characters.")
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return WAIT_BUTTON
    context.user_data["broadcast"]["button_text"] = button_text
    context.user_data["broadcast"]["button_url"] = button_url
    return await _show_preview(update, context)


async def skip_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context, owner_only=True) or not update.callback_query:
        return ConversationHandler.END
    await update.callback_query.answer()
    return await _show_preview(update, context)


async def _show_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = context.user_data.get("broadcast")
    if not data or not update.effective_chat:
        return ConversationHandler.END
    reply_markup = None
    if data.get("button_text") and data.get("button_url"):
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(data["button_text"], url=data["button_url"])]]
        )
    await context.bot.send_message(update.effective_chat.id, "Preview (only visible to you):")
    await context.bot.copy_message(
        chat_id=update.effective_chat.id,
        from_chat_id=data["source_chat_id"],
        message_id=data["source_message_id"],
        reply_markup=reply_markup,
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm send", callback_data="broadcast:confirm"),
                InlineKeyboardButton("✖ Cancel", callback_data="broadcast:cancel"),
            ]
        ]
    )
    await context.bot.send_message(
        update.effective_chat.id,
        "Send this broadcast to all eligible users?",
        reply_markup=keyboard,
    )
    return WAIT_CONFIRM


async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    dependencies = await _authorized(update, context, owner_only=True)
    query = update.callback_query
    data = context.user_data.get("broadcast")
    if not dependencies or not query or not data or not update.effective_user:
        return ConversationHandler.END
    await query.answer()
    progress_message = await query.edit_message_text("Broadcast confirmed. Preparing recipients...")
    _, session_factory = dependencies
    async with session_factory() as session:
        user_ids = list(
            await session.scalars(
                select(User.telegram_id).where(User.is_banned.is_(False)).order_by(User.telegram_id)
            )
        )
        log = BroadcastLog(
            owner_id=update.effective_user.id, content_type=data["content_type"], status="sending"
        )
        session.add(log)
        await session.flush()
        log_id = log.id
        await session.commit()

    reply_markup = None
    if data.get("button_text") and data.get("button_url"):
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(data["button_text"], url=data["button_url"])]]
        )
    payload = BroadcastPayload(
        source_chat_id=data["source_chat_id"],
        source_message_id=data["source_message_id"],
        content_type=data["content_type"],
        reply_markup=reply_markup,
    )

    async def report(processed: int, successful: int, failed: int) -> None:
        await progress_message.edit_text(
            f"Sending: {processed}/{len(user_ids)}\nSuccessful: {successful}\nFailed: {failed}"
        )

    settings, _ = dependencies
    result = await deliver_broadcast(
        context.bot, user_ids, payload, settings.broadcast_delay_seconds, report
    )
    async with session_factory() as session:
        log = await session.get(BroadcastLog, log_id)
        if log:
            log.successful_count = result.successful
            log.failed_count = result.failed
            log.status = "complete"
            log.completed_at = utcnow()
        await _audit(
            session,
            update.effective_user.id,
            "broadcast",
            f"id={log_id} successful={result.successful} failed={result.failed}",
        )
        await session.commit()
    await progress_message.edit_text(
        f"Broadcast complete.\nSuccessful: {result.successful}\nFailed: {result.failed}"
    )
    context.user_data.pop("broadcast", None)
    return ConversationHandler.END


async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("broadcast", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Broadcast cancelled. Nothing was sent.")
    elif update.effective_message:
        await update.effective_message.reply_text("Broadcast cancelled. Nothing was sent.")
    return ConversationHandler.END


def handlers() -> list[object]:
    return [
        ConversationHandler(
            entry_points=[CommandHandler("broadcast", broadcast_start)],
            states={
                WAIT_CONTENT: [
                    MessageHandler(
                        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL,
                        capture_content,
                    )
                ],
                WAIT_BUTTON: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, capture_button),
                    CallbackQueryHandler(skip_button, pattern=r"^broadcast:skip_button$"),
                ],
                WAIT_CONFIRM: [
                    CallbackQueryHandler(confirm_broadcast, pattern=r"^broadcast:confirm$")
                ],
            },
            fallbacks=[
                CommandHandler("cancel", cancel_broadcast),
                CallbackQueryHandler(cancel_broadcast, pattern=r"^broadcast:cancel$"),
            ],
            allow_reentry=True,
        )
    ]
