"""Paid/free access decisions and validation-only pending request processing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Payment,
    PendingRequest,
    PendingRequestStatus,
    User,
    utcnow,
)
from app.services.link_validator import validate_diskwala_url
from app.services.subscription_service import refresh_expired_subscription, subscription_is_active
from app.services.user_service import check_and_consume_daily_request


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    access_source: str
    limit: int
    credit_deducted: bool = False


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    request_id: int
    completed: bool
    message: str


async def consume_access(session: AsyncSession, user: User) -> AccessDecision:
    await refresh_expired_subscription(session, user)
    if subscription_is_active(user):
        return AccessDecision(True, "premium", 0)

    free_allowed, limit = await check_and_consume_daily_request(session, user)
    if free_allowed:
        return AccessDecision(True, "free_daily", limit)
    if user.credits > 0:
        user.credits -= 1
        await session.flush()
        return AccessDecision(True, "credit", limit, credit_deducted=True)
    return AccessDecision(False, "payment_required", limit)


async def save_pending_request(
    session: AsyncSession,
    user_id: int,
    source_url: str,
    *,
    expires_in: timedelta = timedelta(hours=24),
) -> PendingRequest:
    request = PendingRequest(
        user_id=user_id,
        source_url=source_url,
        status=PendingRequestStatus.WAITING_PAYMENT,
        payment_required=True,
        expires_at=utcnow() + expires_in,
    )
    session.add(request)
    await session.flush()
    return request


async def process_validated_request(
    session: AsyncSession,
    user: User,
    source_url: str,
    decision: AccessDecision,
) -> ProcessOutcome:
    request = PendingRequest(
        user_id=user.telegram_id,
        source_url=source_url,
        status=PendingRequestStatus.PROCESSING,
        payment_required=False,
        expires_at=utcnow() + timedelta(hours=24),
        processing_started_at=utcnow(),
    )
    session.add(request)
    await session.flush()
    try:
        result = validate_diskwala_url(source_url)
        if not result.valid:
            raise ValueError(result.message)
        request.status = PendingRequestStatus.COMPLETED
        request.completed_at = utcnow()
        await session.flush()
        return ProcessOutcome(
            request.id,
            True,
            "Link validated. Downloading is not connected yet because no official or permitted "
            "download method has been confirmed.",
        )
    except Exception as exc:
        request.status = PendingRequestStatus.FAILED
        request.error_message = type(exc).__name__
        if decision.credit_deducted:
            user.credits += 1
        await session.flush()
        return ProcessOutcome(
            request.id, False, "Processing failed. Any deducted credit was returned."
        )


async def resume_latest_pending_request(
    session: AsyncSession, user: User, payment: Payment
) -> ProcessOutcome | None:
    now = utcnow()
    await session.execute(
        update(PendingRequest)
        .where(
            PendingRequest.user_id == user.telegram_id,
            PendingRequest.status == PendingRequestStatus.WAITING_PAYMENT,
            PendingRequest.expires_at <= now,
        )
        .values(status=PendingRequestStatus.EXPIRED)
    )
    request = await session.scalar(
        select(PendingRequest)
        .where(
            PendingRequest.user_id == user.telegram_id,
            PendingRequest.status == PendingRequestStatus.WAITING_PAYMENT,
            PendingRequest.expires_at > now,
        )
        .order_by(PendingRequest.created_at.desc(), PendingRequest.id.desc())
        .limit(1)
    )
    if request is None:
        return None

    await refresh_expired_subscription(session, user)
    credit_deducted = False
    if not subscription_is_active(user):
        if user.credits <= 0:
            return None
        user.credits -= 1
        credit_deducted = True

    request.payment_id = payment.id
    request.payment_required = False
    request.status = PendingRequestStatus.PROCESSING
    request.processing_started_at = now
    try:
        result = validate_diskwala_url(request.source_url)
        if not result.valid:
            raise ValueError(result.message)
        request.status = PendingRequestStatus.COMPLETED
        request.completed_at = utcnow()
        await session.flush()
        return ProcessOutcome(
            request.id,
            True,
            "Your saved link was resumed and validated. Downloading is still not connected.",
        )
    except Exception as exc:
        request.status = PendingRequestStatus.FAILED
        request.error_message = type(exc).__name__
        if credit_deducted:
            user.credits += 1
        await session.flush()
        return ProcessOutcome(
            request.id, False, "Saved-link processing failed; the credit was returned."
        )
