"""Subscription lifecycle and future payment-provider contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SubscriptionPlan, User, utcnow


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class PaymentRequest:
    user_id: int
    plan_code: str
    amount_display: str


@dataclass(frozen=True, slots=True)
class PaymentResult:
    provider_reference: str
    status: PaymentStatus


class PaymentProvider(ABC):
    """Interface for Telegram Stars or another approved provider.

    Implementations must store provider references only, never card data or
    payment credentials.
    """

    @abstractmethod
    async def create_payment(self, request: PaymentRequest) -> PaymentResult:
        raise NotImplementedError

    @abstractmethod
    async def verify_payment(self, provider_reference: str) -> PaymentResult:
        raise NotImplementedError


def subscription_is_active(user: User, now: datetime | None = None) -> bool:
    if user.plan is not SubscriptionPlan.PREMIUM or user.subscription_expires_at is None:
        return False
    current = now or utcnow()
    expiry = user.subscription_expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry > current


async def refresh_expired_subscription(session: AsyncSession, user: User) -> bool:
    """Downgrade an expired premium user. Return True when changed."""
    if user.plan is SubscriptionPlan.PREMIUM and not subscription_is_active(user):
        user.plan = SubscriptionPlan.FREE
        user.subscription_started_at = None
        user.subscription_expires_at = None
        user.ads_enabled = True
        await session.flush()
        return True
    return False


async def grant_premium(session: AsyncSession, user: User, days: int) -> User:
    if not 1 <= days <= 3650:
        raise ValueError("Premium duration must be between 1 and 3650 days.")
    now = utcnow()
    base = user.subscription_expires_at if subscription_is_active(user, now) else now
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    user.plan = SubscriptionPlan.PREMIUM
    user.subscription_started_at = user.subscription_started_at or now
    user.subscription_expires_at = base + timedelta(days=days)
    user.ads_enabled = False
    await session.flush()
    return user


async def remove_premium(session: AsyncSession, user: User) -> User:
    user.plan = SubscriptionPlan.FREE
    user.subscription_started_at = None
    user.subscription_expires_at = None
    user.ads_enabled = True
    await session.flush()
    return user
