"""Safe link-validation handler."""

from __future__ import annotations

import math

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from app.config import Settings
from app.middleware.rate_limit import CooldownRateLimiter
from app.models import LinkRequest
from app.services.link_validator import ValidationOnlyDownloader, validate_diskwala_url
from app.services.user_service import (
    check_and_consume_daily_request,
    get_or_create_user,
    get_setting,
)


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if (
        not update.effective_user
        or not update.effective_message
        or not update.effective_message.text
    ):
        return
    settings: Settings = context.application.bot_data["settings"]
    session_factory: async_sessionmaker[AsyncSession] = context.application.bot_data[
        "session_factory"
    ]
    limiter: CooldownRateLimiter = context.application.bot_data["rate_limiter"]

    wait_for = await limiter.check(update.effective_user.id)
    if wait_for > 0:
        await update.effective_message.reply_text(
            f"Please wait {math.ceil(wait_for)} second(s) before sending another link."
        )
        return

    checking_message = await update.effective_message.reply_text("🔎 Checking your link...")
    raw_url = update.effective_message.text.strip()
    result = validate_diskwala_url(raw_url)

    async with session_factory() as session:
        user = await get_or_create_user(session, update.effective_user, settings.owner_user_id)
        maintenance_enabled = await get_setting(session, "maintenance_enabled", "false") == "true"
        maintenance_message = await get_setting(session, "maintenance_message")
        if user.is_banned:
            await checking_message.edit_text(
                "Your account is banned. Contact support if this is a mistake."
            )
            return
        if maintenance_enabled and user.telegram_id != settings.owner_user_id:
            await checking_message.edit_text(maintenance_message)
            return

        allowed, limit = await check_and_consume_daily_request(session, user)
        request = LinkRequest(
            user_id=user.telegram_id,
            submitted_url=raw_url,
            normalized_url=result.normalized_url,
            is_valid=result.valid,
            result_code=result.code if allowed else "daily_limit",
        )
        session.add(request)
        await session.commit()

    if not allowed:
        await checking_message.edit_text(
            f"You have reached your daily limit of {limit} requests. "
            "Try again tomorrow or view /plans."
        )
        return
    if not result.valid:
        await checking_message.edit_text(f"❌ {result.message}")
        return

    download = await ValidationOnlyDownloader().get_download(result.normalized_url or raw_url)
    await checking_message.edit_text(
        f"✅ {result.message}\n\n{download.message}", disable_web_page_preview=True
    )


def handlers() -> list[object]:
    return [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)]
