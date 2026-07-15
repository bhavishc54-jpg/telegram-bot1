"""Bot-wide banned-user and maintenance-mode guard."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes, TypeHandler

from app.config import Settings
from app.models import User
from app.services.user_service import get_setting


async def access_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    settings: Settings = context.application.bot_data["settings"]
    if update.effective_user.id == settings.owner_user_id:
        return
    session_factory: async_sessionmaker[AsyncSession] = context.application.bot_data[
        "session_factory"
    ]
    async with session_factory() as session:
        user = await session.get(User, update.effective_user.id)
        if user and user.is_banned:
            if update.callback_query:
                await update.callback_query.answer("Your account is banned.", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(
                    "Your account is banned. Contact support if this is a mistake."
                )
            raise ApplicationHandlerStop
        maintenance_enabled = await get_setting(session, "maintenance_enabled", "false")
        if maintenance_enabled.lower() == "true":
            message = await get_setting(
                session, "maintenance_message", "The bot is under maintenance."
            )
            if update.callback_query:
                await update.callback_query.answer(message[:200], show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(message)
            raise ApplicationHandlerStop


def handler() -> TypeHandler:
    return TypeHandler(Update, access_guard)
