"""Safe link validation with free, credit, Premium, and payment-required access."""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from app.config import Settings
from app.keyboards.payments import purchase_options_keyboard
from app.middleware.rate_limit import CooldownRateLimiter
from app.models import LinkRequest, Product, User
from app.services.ad_service import get_eligible_ad, send_sponsored_message
from app.services.link_validator import validate_diskwala_url
from app.services.pending_request_service import (
    consume_access,
    process_validated_request,
    save_pending_request,
)
from app.services.user_service import get_or_create_user


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
    validation = validate_diskwala_url(raw_url)
    async with session_factory() as session:
        user = await get_or_create_user(session, update.effective_user, settings.owner_user_id)
        if not validation.valid:
            session.add(
                LinkRequest(
                    user_id=user.telegram_id,
                    submitted_url=raw_url,
                    normalized_url=None,
                    is_valid=False,
                    result_code=validation.code,
                )
            )
            await session.commit()
            await checking_message.edit_text(f"❌ {validation.message}")
            return

        normalized_url = validation.normalized_url or raw_url
        decision = await consume_access(session, user)
        if not decision.allowed:
            pending = await save_pending_request(session, user.telegram_id, normalized_url)
            session.add(
                LinkRequest(
                    user_id=user.telegram_id,
                    submitted_url=raw_url,
                    normalized_url=normalized_url,
                    is_valid=True,
                    result_code="waiting_payment",
                )
            )
            products = list(
                await session.scalars(
                    select(Product).where(Product.is_active.is_(True)).order_by(Product.id)
                )
            )
            await session.commit()
            keyboard = purchase_options_keyboard(products, settings)
            text = (
                f"✅ Valid DiskWala link saved as pending request #{pending.id}.\n\n"
                f"Your free daily limit of {decision.limit} is used and you have no credits. "
                "Choose a payment option; the latest unexpired saved link resumes only after "
                "Telegram or Paddle confirms payment."
            )
            if keyboard is None:
                text += "\n\nPayments are not configured yet. Try again tomorrow."
            await checking_message.edit_text(text, reply_markup=keyboard)
            return

        outcome = await process_validated_request(session, user, normalized_url, decision)
        session.add(
            LinkRequest(
                user_id=user.telegram_id,
                submitted_url=raw_url,
                normalized_url=normalized_url,
                is_valid=True,
                result_code=f"completed_{decision.access_source}"
                if outcome.completed
                else "failed",
            )
        )
        await session.commit()

    if not outcome.completed:
        await checking_message.edit_text(outcome.message)
        return
    await checking_message.edit_text(f"✅ {validation.message}\n\n{outcome.message}")
    async with session_factory() as session:
        current_user = await session.get(User, update.effective_user.id)
        ad = await get_eligible_ad(session, current_user) if current_user else None
    if ad:
        await send_sponsored_message(update.effective_message, ad)


def handlers() -> list[object]:
    return [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)]
