from datetime import timedelta

import pytest

from app.models import SponsoredMessage, SubscriptionPlan, User, utcnow
from app.services.ad_service import ad_is_current, user_is_ad_eligible, validate_ad_content


def test_advertisement_eligibility() -> None:
    free = User(telegram_id=1, first_name="Free")
    premium = User(
        telegram_id=2,
        first_name="Premium",
        plan=SubscriptionPlan.PREMIUM,
        subscription_expires_at=utcnow() + timedelta(days=1),
        ads_enabled=False,
    )
    assert user_is_ad_eligible(free) is True
    assert user_is_ad_eligible(premium) is False
    assert user_is_ad_eligible(free, global_enabled=False) is False


def test_ad_dates_and_display_cap() -> None:
    now = utcnow()
    ad = SponsoredMessage(
        title="Safe product",
        message_text="A clear and honest message.",
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=1),
        max_displays=2,
        display_count=1,
        created_by=1,
    )
    assert ad_is_current(ad, now) is True
    ad.display_count = 2
    assert ad_is_current(ad, now) is False


def test_harmful_ad_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_ad_content("Casino bonus", "Guaranteed win", "https://example.com")
