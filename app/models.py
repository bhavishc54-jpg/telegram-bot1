"""SQLAlchemy database models."""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"
    OWNER = "owner"


class SubscriptionPlan(StrEnum):
    FREE = "free"
    PREMIUM = "premium"


class PaymentProvider(StrEnum):
    TELEGRAM_STARS = "telegram_stars"
    PADDLE = "paddle"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class PendingRequestStatus(StrEnum):
    WAITING_PAYMENT = "waiting_payment"
    READY = "ready"
    PROCESSING = "processing"
    COMPLETED = "completed"
    EXPIRED = "expired"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), default="")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER)
    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan), default=SubscriptionPlan.FREE
    )
    subscription_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    subscription_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    daily_usage: Mapped[int] = mapped_column(Integer, default=0)
    usage_date: Mapped[date] = mapped_column(Date, default=date.today)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    ads_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    referral_code: Mapped[str] = mapped_column(
        String(32), unique=True, default=lambda: secrets.token_urlsafe(9)
    )
    referrer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=True
    )


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LinkRequest(Base):
    __tablename__ = "link_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    submitted_url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    result_code: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class SponsoredMessage(Base):
    __tablename__ = "sponsored_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    message_text: Mapped[str] = mapped_column(Text)
    button_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    button_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    max_displays: Mapped[int] = mapped_column(Integer, default=0)
    display_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[int] = mapped_column(BigInteger)


class BroadcastLog(Base):
    __tablename__ = "broadcast_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    content_type: Mapped[str] = mapped_column(String(32))
    successful_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[PaymentProvider] = mapped_column(Enum(PaymentProvider), index=True)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    premium_duration_days: Mapped[int] = mapped_column(Integer, default=0)
    stars_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paddle_product_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paddle_price_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    provider: Mapped[PaymentProvider] = mapped_column(Enum(PaymentProvider), index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), index=True)
    internal_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invoice_payload: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3))
    credits_purchased: Mapped[int] = mapped_column(Integer, default=0)
    premium_duration_days: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.PENDING, index=True
    )
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    telegram_provider_payment_charge_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    paddle_transaction_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    paddle_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paddle_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paddle_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


class ProcessedPaymentEvent(Base):
    __tablename__ = "processed_payment_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_processed_provider_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[PaymentProvider] = mapped_column(Enum(PaymentProvider), index=True)
    event_id: Mapped[str] = mapped_column(String(255))
    payment_id: Mapped[int] = mapped_column(Integer, ForeignKey("payments.id"), index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PendingRequest(Base):
    __tablename__ = "pending_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    status: Mapped[PendingRequestStatus] = mapped_column(
        Enum(PendingRequestStatus), default=PendingRequestStatus.WAITING_PAYMENT, index=True
    )
    payment_required: Mapped[bool] = mapped_column(Boolean, default=True)
    payment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("payments.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
