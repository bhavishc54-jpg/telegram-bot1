"""Basic user commands and main-menu callbacks."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from app.config import Settings
from app.keyboards.user import main_menu_keyboard
from app.models import SubscriptionPlan
from app.services.subscription_service import refresh_expired_subscription
from app.services.user_service import get_or_create_user, get_setting


def _dependencies(
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[Settings, async_sessionmaker[AsyncSession]]:
    return context.application.bot_data["settings"], context.application.bot_data["session_factory"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    settings, session_factory = _dependencies(context)
    async with session_factory() as session:
        await get_or_create_user(session, update.effective_user, settings.owner_user_id)
        welcome = await get_setting(session, "welcome_message")
    await update.effective_message.reply_text(welcome, reply_markup=main_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    _, session_factory = _dependencies(context)
    async with session_factory() as session:
        text = await get_setting(session, "help_message")
    await update.effective_message.reply_text(text, reply_markup=main_menu_keyboard())


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("✅ Bot is online and ready.")


async def account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    settings, session_factory = _dependencies(context)
    async with session_factory() as session:
        user = await get_or_create_user(session, update.effective_user, settings.owner_user_id)
        if await refresh_expired_subscription(session, user):
            await session.commit()
        limit_key = (
            "premium_daily_limit" if user.plan is SubscriptionPlan.PREMIUM else "free_daily_limit"
        )
        limit = await get_setting(session, limit_key)
    expiry = "Not active"
    if user.subscription_expires_at:
        expiry = user.subscription_expires_at.strftime("%Y-%m-%d %H:%M UTC")
    badge = " 💎" if user.plan is SubscriptionPlan.PREMIUM else ""
    text = (
        f"<b>Your account{badge}</b>\n"
        f"Name: {update.effective_user.mention_html()}\n"
        f"User ID: <code>{user.telegram_id}</code>\n"
        f"Plan: {user.plan.value.title()}\n"
        f"Daily usage: {user.daily_usage}/{limit}\n"
        f"Subscription expiry: {expiry}"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    _, session_factory = _dependencies(context)
    async with session_factory() as session:
        free_limit = await get_setting(session, "free_daily_limit", "5")
        premium_limit = await get_setting(session, "premium_daily_limit", "100")
        premium_name = await get_setting(session, "premium_plan_name", "Premium")
        price = await get_setting(session, "premium_price_text", "Coming soon")
    text = (
        f"<b>Free</b>\n• {free_limit} validations per day\n• Sponsored messages may appear\n"
        "• Normal priority\n\n"
        f"<b>{premium_name} 💎</b>\n• {premium_limit} validations per day\n"
        f"• No sponsored messages\n• Priority processing\n• Price: {price}\n\n"
        "Payments are not connected yet. No card information is collected."
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    settings, session_factory = _dependencies(context)
    async with session_factory() as session:
        username = await get_setting(session, "support_username", settings.support_username)
    message = (
        f"For support, contact @{username}."
        if username
        else "Support contact is not configured yet."
    )
    await update.effective_message.reply_text(message)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    routes = {
        "user:account": account,
        "user:plans": plans,
        "user:help": help_command,
        "user:support": support,
    }
    handler = routes.get(query.data or "")
    if handler:
        await handler(update, context)


def handlers() -> list[object]:
    return [
        CommandHandler("start", start),
        CommandHandler("help", help_command),
        CommandHandler("status", status),
        CommandHandler("account", account),
        CommandHandler("plans", plans),
        CommandHandler("support", support),
        CallbackQueryHandler(menu_callback, pattern=r"^user:"),
    ]
