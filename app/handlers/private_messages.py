"""Forward private non-command user messages to the admin only."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from app.config import Settings

logger = logging.getLogger(__name__)


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


async def forward_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    settings = _settings(context)
    if user.id == settings.admin_user_id:
        return
    username = f"@{user.username}" if user.username else "-"
    header = (
        "Private message from user\n"
        f"Name: {user.first_name or '-'}\n"
        f"Username: {username}\n"
        f"User ID: {user.id}"
    )
    try:
        await context.bot.send_message(chat_id=settings.admin_user_id, text=header)
        await context.bot.copy_message(
            chat_id=settings.admin_user_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
    except Exception as exc:
        logger.warning("Could not forward private user message: %s", type(exc).__name__)


def handlers() -> list[object]:
    return [
        MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, forward_private_message),
    ]
