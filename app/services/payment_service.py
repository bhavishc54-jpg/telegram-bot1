"""Provider-neutral, idempotent payment creation and fulfillment."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Payment,
    PaymentProvider,
    PaymentStatus,
    ProcessedPaymentEvent,
    Product,
    User,
    utcnow,
)
from app.services.pending_request_service import ProcessOutcome, resume_latest_pending_request
from app.services.subscription_service import grant_premium


@dataclass(frozen=True, slots=True)
class FulfillmentOutcome:
    payment_id: int
    fulfilled: bool
    duplicate: bool
    credits_added: int
    credit_balance: int
    resumed: ProcessOutcome | None


def generate_order_id() -> str:
    return f"ord_{secrets.token_urlsafe(18)}"


def generate_invoice_payload(internal_order_id: str) -> str:
    payload = f"stars:{internal_order_id}:{secrets.token_urlsafe(18)}"
    if len(payload.encode("utf-8")) > 128:
        raise ValueError("Invoice payload is too long.")
    return payload


async def create_pending_payment(session: AsyncSession, user_id: int, product: Product) -> Payment:
    if not product.is_active:
        raise ValueError("This product is not active.")
    order_id = generate_order_id()
    invoice_payload = None
    amount = 0
    if product.provider is PaymentProvider.TELEGRAM_STARS:
        if not product.stars_price or product.currency != "XTR":
            raise ValueError("Telegram Stars product is not configured correctly.")
        invoice_payload = generate_invoice_payload(order_id)
        amount = product.stars_price
    payment = Payment(
        user_id=user_id,
        provider=product.provider,
        product_id=product.id,
        internal_order_id=order_id,
        invoice_payload=invoice_payload,
        amount=amount,
        currency=product.currency,
        credits_purchased=product.credits,
        premium_duration_days=product.premium_duration_days,
        status=PaymentStatus.PENDING,
    )
    session.add(payment)
    await session.flush()
    return payment


async def get_stars_payment_for_validation(
    session: AsyncSession,
    invoice_payload: str,
    user_id: int,
    currency: str,
    amount: int,
) -> Payment | None:
    payment = await session.scalar(
        select(Payment).where(
            Payment.invoice_payload == invoice_payload,
            Payment.provider == PaymentProvider.TELEGRAM_STARS,
        )
    )
    if (
        payment is None
        or payment.user_id != user_id
        or payment.currency != currency
        or payment.amount != amount
        or payment.status is not PaymentStatus.PENDING
    ):
        return None
    product = await session.get(Product, payment.product_id)
    if product is None or not product.is_active or product.stars_price != amount:
        return None
    return payment


async def fulfill_payment(
    session: AsyncSession,
    payment_id: int,
    event_id: str,
    *,
    telegram_payment_charge_id: str | None = None,
    telegram_provider_payment_charge_id: str | None = None,
    paddle_event_id: str | None = None,
    paddle_subscription_id: str | None = None,
    paddle_customer_id: str | None = None,
) -> FulfillmentOutcome:
    existing_event = await session.scalar(
        select(ProcessedPaymentEvent).where(
            ProcessedPaymentEvent.provider
            == (PaymentProvider.PADDLE if paddle_event_id else PaymentProvider.TELEGRAM_STARS),
            ProcessedPaymentEvent.event_id == event_id[:255],
        )
    )
    if existing_event is not None:
        existing_payment = await session.get(Payment, existing_event.payment_id)
        user = await session.get(User, existing_payment.user_id) if existing_payment else None
        return FulfillmentOutcome(
            existing_event.payment_id,
            False,
            True,
            0,
            user.credits if user else 0,
            None,
        )
    values: dict[str, object] = {"status": PaymentStatus.PAID, "paid_at": utcnow()}
    if telegram_payment_charge_id:
        values["telegram_payment_charge_id"] = telegram_payment_charge_id
    if telegram_provider_payment_charge_id:
        values["telegram_provider_payment_charge_id"] = telegram_provider_payment_charge_id
    if paddle_event_id:
        values["paddle_event_id"] = paddle_event_id
    if paddle_subscription_id:
        values["paddle_subscription_id"] = paddle_subscription_id
    if paddle_customer_id:
        values["paddle_customer_id"] = paddle_customer_id

    claim = await session.execute(
        update(Payment)
        .where(Payment.id == payment_id, Payment.status == PaymentStatus.PENDING)
        .values(**values)
    )
    if claim.rowcount != 1:
        existing = await session.get(Payment, payment_id)
        user = await session.get(User, existing.user_id) if existing else None
        return FulfillmentOutcome(
            payment_id,
            False,
            True,
            0,
            user.credits if user else 0,
            None,
        )

    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise RuntimeError("Claimed payment disappeared.")
    user = await session.get(User, payment.user_id)
    if user is None:
        raise RuntimeError("Payment user does not exist.")

    session.add(
        ProcessedPaymentEvent(
            provider=payment.provider,
            event_id=event_id[:255],
            payment_id=payment.id,
        )
    )
    if payment.credits_purchased > 0:
        user.credits += payment.credits_purchased
    if payment.premium_duration_days > 0:
        await grant_premium(session, user, payment.premium_duration_days)
    resumed = await resume_latest_pending_request(session, user, payment)
    await session.flush()
    return FulfillmentOutcome(
        payment.id,
        True,
        False,
        payment.credits_purchased,
        user.credits,
        resumed,
    )


async def mark_payment_terminal(
    session: AsyncSession,
    payment: Payment,
    event_id: str,
    status: PaymentStatus,
    metadata: dict[str, object] | None = None,
) -> bool:
    if status not in {PaymentStatus.FAILED, PaymentStatus.CANCELED, PaymentStatus.REFUNDED}:
        raise ValueError("Unsupported terminal payment status.")
    timestamp_field = {
        PaymentStatus.FAILED: "failed_at",
        PaymentStatus.CANCELED: "canceled_at",
        PaymentStatus.REFUNDED: "refunded_at",
    }[status]
    result = await session.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.status == PaymentStatus.PENDING)
        .values(
            status=status,
            **{timestamp_field: utcnow()},
            metadata_json=json.dumps(metadata or {}, separators=(",", ":"), sort_keys=True),
        )
    )
    if result.rowcount != 1:
        return False
    session.add(
        ProcessedPaymentEvent(
            provider=payment.provider,
            event_id=event_id[:255],
            payment_id=payment.id,
        )
    )
    await session.flush()
    return True
