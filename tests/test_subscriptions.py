from datetime import timedelta

import pytest

from app.models import SubscriptionPlan, User, utcnow
from app.services.subscription_service import (
    grant_premium,
    refresh_expired_subscription,
    subscription_is_active,
)
from app.services.user_service import check_and_consume_daily_request


@pytest.mark.asyncio
async def test_free_plan_limit(session) -> None:
    user = User(telegram_id=1, first_name="Free")
    session.add(user)
    await session.commit()

    assert await check_and_consume_daily_request(session, user) == (True, 2)
    assert await check_and_consume_daily_request(session, user) == (True, 2)
    assert await check_and_consume_daily_request(session, user) == (False, 2)


@pytest.mark.asyncio
async def test_premium_plan_limit(session) -> None:
    user = User(telegram_id=2, first_name="Premium")
    session.add(user)
    await session.flush()
    await grant_premium(session, user, 30)

    results = [await check_and_consume_daily_request(session, user) for _ in range(5)]
    assert results[:4] == [(True, 4)] * 4
    assert results[4] == (False, 4)


@pytest.mark.asyncio
async def test_subscription_expiry_downgrades_user(session) -> None:
    user = User(
        telegram_id=3,
        first_name="Expired",
        plan=SubscriptionPlan.PREMIUM,
        subscription_started_at=utcnow() - timedelta(days=5),
        subscription_expires_at=utcnow() - timedelta(seconds=1),
        ads_enabled=False,
    )
    session.add(user)
    await session.flush()

    assert subscription_is_active(user) is False
    assert await refresh_expired_subscription(session, user) is True
    assert user.plan is SubscriptionPlan.FREE
    assert user.ads_enabled is True
