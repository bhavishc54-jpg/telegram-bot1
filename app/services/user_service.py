"""User registration and settings helpers."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import User as TelegramUser

from app.models import BotSetting, SubscriptionPlan, User, UserRole, utcnow
from app.services.subscription_service import refresh_expired_subscription


async def get_or_create_user(
    session: AsyncSession, telegram_user: TelegramUser, owner_user_id: int
) -> User:
    user = await session.get(User, telegram_user.id)
    expected_role = UserRole.OWNER if telegram_user.id == owner_user_id else UserRole.USER
    if user is None:
        user = User(
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name or "",
            role=expected_role,
        )
        session.add(user)
    else:
        user.username = telegram_user.username
        user.first_name = telegram_user.first_name or ""
        user.last_active_at = utcnow()
        if telegram_user.id == owner_user_id:
            user.role = UserRole.OWNER
    if user.usage_date != date.today():
        user.daily_usage = 0
        user.usage_date = date.today()
    await session.commit()
    await session.refresh(user)
    return user


async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    setting = await session.get(BotSetting, key)
    return setting.value if setting else default


async def check_and_consume_daily_request(session: AsyncSession, user: User) -> tuple[bool, int]:
    """Consume one daily request when the user's configured plan allows it."""
    await refresh_expired_subscription(session, user)
    if user.usage_date != date.today():
        user.daily_usage = 0
        user.usage_date = date.today()
    limit_key = (
        "premium_daily_limit" if user.plan is SubscriptionPlan.PREMIUM else "free_daily_limit"
    )
    raw_limit = await get_setting(
        session, limit_key, "100" if user.plan is SubscriptionPlan.PREMIUM else "5"
    )
    try:
        limit = max(1, int(raw_limit))
    except ValueError:
        limit = 100 if user.plan is SubscriptionPlan.PREMIUM else 5
    if user.daily_usage >= limit:
        return False, limit
    user.daily_usage += 1
    user.total_requests += 1
    await session.flush()
    return True, limit
