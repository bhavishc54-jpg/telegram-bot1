"""Telegram Stars and Paddle purchase flows."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from app.config import ConfigurationError, Settings
from app.keyboards.payments import purchase_options_keyboard
from app.models import Payment, PaymentProvider, PaymentStatus, Product, utcnow
from app.services.paddle_service import PaddleClient, PaddleError, attach_paddle_checkout
from app.services.payment_service import (
    create_pending_payment,
    fulfill_payment,
    get_stars_payment_for_validation,
)
from app.services.subscription_service import subscription_is_active
from app.services.user_service import get_or_create_user


def _dependencies(
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[Settings, async_sessionmaker[AsyncSession]]:
    return context.application.bot_data["settings"], context.application.bot_data["session_factory"]


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    settings, session_factory = _dependencies(context)
    async with session_factory() as session:
        await get_or_create_user(session, update.effective_user, settings.owner_user_id)
        products = list(
            await session.scalars(
                select(Product).where(Product.is_active.is_(True)).order_by(Product.id)
            )
        )
    keyboard = purchase_options_keyboard(products, settings)
    if keyboard is None:
        await update.effective_message.reply_text(
            "Purchase options are not configured yet. You can still use the free daily allowance."
        )
        return
    await update.effective_message.reply_text(
        "Choose a credit pack or Premium plan. Access is added only after the payment provider "
        "confirms payment.",
        reply_markup=keyboard,
    )


async def credits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    settings, session_factory = _dependencies(context)
    async with session_factory() as session:
        user = await get_or_create_user(session, update.effective_user, settings.owner_user_id)
    premium = "Active" if subscription_is_active(user) else "Not active"
    await update.effective_message.reply_text(
        f"Credits: {user.credits}\nPremium: {premium}\nUse /buy to see purchase options."
    )


async def payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    _, session_factory = _dependencies(context)
    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(Payment)
                .where(Payment.user_id == update.effective_user.id)
                .order_by(Payment.created_at.desc())
                .limit(10)
            )
        )
    if not rows:
        await update.effective_message.reply_text("You have no payment history.")
        return
    await update.effective_message.reply_text(
        "Your recent payments:\n"
        + "\n".join(
            f"{row.internal_order_id} | {row.provider.value} | {row.status.value}" for row in rows
        )
    )


async def purchase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    parts = (query.data or "").split(":", 2)
    if len(parts) != 3:
        await query.edit_message_text("Invalid purchase option.")
        return
    provider_name, product_code = parts[1], parts[2]
    settings, session_factory = _dependencies(context)
    async with session_factory() as session:
        product = await session.scalar(
            select(Product).where(Product.product_code == product_code, Product.is_active.is_(True))
        )
        if product is None:
            await query.edit_message_text("This product is no longer available.")
            return
        expected_provider = (
            PaymentProvider.TELEGRAM_STARS if provider_name == "stars" else PaymentProvider.PADDLE
        )
        if product.provider is not expected_provider:
            await query.edit_message_text("Product provider mismatch.")
            return
        payment = await create_pending_payment(session, update.effective_user.id, product)
        await session.commit()
        payment_id = payment.id

    if product.provider is PaymentProvider.TELEGRAM_STARS:
        if not settings.enable_telegram_stars:
            await query.edit_message_text("Telegram Stars payments are disabled.")
            return
        await context.bot.send_invoice(
            chat_id=update.effective_user.id,
            title=product.name,
            description=product.description,
            payload=payment.invoice_payload or "",
            currency="XTR",
            prices=[LabeledPrice(product.name, product.stars_price or 0)],
            provider_token=None,
        )
        await query.edit_message_text("Telegram Stars invoice created. Complete it in Telegram.")
        return

    try:
        client = PaddleClient(settings)
        async with session_factory() as session:
            current_payment = await session.get(Payment, payment_id)
            current_product = await session.get(Product, product.id)
            if current_payment is None or current_product is None:
                raise PaddleError("Internal Paddle order is missing.")
            checkout = await attach_paddle_checkout(
                session, current_payment, current_product, client
            )
            await session.commit()
    except (PaddleError, ConfigurationError):
        async with session_factory() as session:
            current_payment = await session.get(Payment, payment_id)
            if current_payment and current_payment.status is PaymentStatus.PENDING:
                current_payment.status = PaymentStatus.FAILED
                current_payment.failed_at = utcnow()
                current_payment.metadata_json = json.dumps({"reason": "checkout_creation_failed"})
                await session.commit()
        await query.edit_message_text(
            "Paddle checkout could not be created. Please try again later."
        )
        return
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Pay with Paddle", url=checkout.checkout_url)]]
    )
    await query.edit_message_text(
        "Complete checkout with Paddle. Credits unlock only after the verified Paddle webhook.",
        reply_markup=keyboard,
    )


async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if query is None:
        return
    _, session_factory = _dependencies(context)
    async with session_factory() as session:
        payment = await get_stars_payment_for_validation(
            session,
            query.invoice_payload,
            query.from_user.id,
            query.currency,
            query.total_amount,
        )
    if payment is None:
        await query.answer(
            ok=False, error_message="This invoice is invalid or no longer available."
        )
        return
    await query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    telegram_user = update.effective_user
    if message is None or telegram_user is None or message.successful_payment is None:
        return
    successful = message.successful_payment
    _, session_factory = _dependencies(context)
    async with session_factory() as session:
        payment = await session.scalar(
            select(Payment).where(
                Payment.invoice_payload == successful.invoice_payload,
                Payment.provider == PaymentProvider.TELEGRAM_STARS,
            )
        )
        if (
            payment is None
            or payment.user_id != telegram_user.id
            or payment.amount != successful.total_amount
            or payment.currency != successful.currency
        ):
            await message.reply_text(
                "Payment confirmation did not match the invoice. Contact support."
            )
            return
        outcome = await fulfill_payment(
            session,
            payment.id,
            successful.telegram_payment_charge_id,
            telegram_payment_charge_id=successful.telegram_payment_charge_id,
            telegram_provider_payment_charge_id=successful.provider_payment_charge_id,
        )
        await session.commit()
    if outcome.duplicate:
        await message.reply_text(
            "This payment was already processed. No duplicate credits were added."
        )
        return
    text = f"Payment successful. Credits added. Current balance: {outcome.credit_balance}."
    if outcome.resumed:
        text += f"\n\n{outcome.resumed.message}"
    await message.reply_text(text)


def handlers() -> list[object]:
    return [
        CommandHandler("buy", buy),
        CommandHandler("credits", credits),
        CommandHandler("paymentstatus", payment_status),
        CallbackQueryHandler(purchase_callback, pattern=r"^buy:(stars|paddle):"),
        PreCheckoutQueryHandler(pre_checkout),
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment),
    ]
