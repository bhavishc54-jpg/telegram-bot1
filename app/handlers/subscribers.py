"""Private subscriber commands."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.config import Settings
from app.repositories.subscribers import mark_inactive, upsert_subscriber


def _dependencies(
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[Settings, async_sessionmaker[AsyncSession]]:
    return context.application.bot_data["settings"], context.application.bot_data["session_factory"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat or not update.effective_message:
        return
    _, session_factory = _dependencies(context)
    async with session_factory() as session:
        await upsert_subscriber(session, update.effective_user, update.effective_chat.id)
        await session.commit()
    await update.effective_message.reply_text(
        "Welcome. You will receive automatic updates here when new posts are ready."
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    _, session_factory = _dependencies(context)
    async with session_factory() as session:
        await mark_inactive(session, update.effective_user.id)
        await session.commit()
    await update.effective_message.reply_text("Automatic updates are stopped.")


async def help_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "This bot sends automatic text updates. Use /stop any time to unsubscribe."
        )


async def myid(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and update.effective_message:
        await update.effective_message.reply_text(
            f"Your Telegram ID is {update.effective_user.id}."
        )


def handlers() -> list[object]:
    return [
        CommandHandler("start", start),
        CommandHandler("stop", stop),
        CommandHandler("help", help_command),
        CommandHandler("myid", myid),
    ]
