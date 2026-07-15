"""Sponsored-message validation, eligibility, and selection."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.models import BotSetting, SponsoredMessage, SubscriptionPlan, User, utcnow
from app.services.subscription_service import subscription_is_active

PROHIBITED_TERMS = frozenset(
    {
        "adult",
        "casino",
        "gambling",
        "betting",
        "malware",
        "phishing",
        "guaranteed profit",
        "illegal drugs",
    }
)


def validate_ad_content(title: str, message: str, button_url: str | None) -> None:
    combined = f"{title} {message}".lower()
    if any(term in combined for term in PROHIBITED_TERMS):
        raise ValueError("This advertisement contains prohibited or potentially harmful content.")
    if not title.strip() or len(title.strip()) > 120:
        raise ValueError("Ad title must contain 1 to 120 characters.")
    if not message.strip() or len(message.strip()) > 3000:
        raise ValueError("Ad message must contain 1 to 3000 characters.")
    if button_url:
        try:
            parsed = urlsplit(button_url.strip())
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Button URL is malformed.") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Button URL must be a complete HTTP or HTTPS URL.")
        if parsed.username or parsed.password or (port and port not in {80, 443}):
            raise ValueError("Button URL contains unsupported credentials or port.")


def user_is_ad_eligible(user: User, global_enabled: bool = True) -> bool:
    return (
        global_enabled
        and user.is_banned is not True
        and user.ads_enabled is not False
        and user.plan in {None, SubscriptionPlan.FREE}
        and not subscription_is_active(user)
    )


def ad_is_current(ad: SponsoredMessage, now: datetime | None = None) -> bool:
    current = now or utcnow()
    start = ad.starts_at if ad.starts_at.tzinfo else ad.starts_at.replace(tzinfo=UTC)
    end = ad.ends_at if ad.ends_at.tzinfo else ad.ends_at.replace(tzinfo=UTC)
    max_displays = ad.max_displays or 0
    display_count = ad.display_count or 0
    return (
        ad.is_active is not False
        and start <= current <= end
        and (max_displays == 0 or display_count < max_displays)
    )


async def get_eligible_ad(session: AsyncSession, user: User) -> SponsoredMessage | None:
    setting = await session.get(BotSetting, "sponsored_messages_enabled")
    enabled = setting is None or setting.value.lower() == "true"
    if not user_is_ad_eligible(user, enabled):
        return None
    now = utcnow()
    ad = await session.scalar(
        select(SponsoredMessage)
        .where(
            SponsoredMessage.is_active.is_(True),
            SponsoredMessage.starts_at <= now,
            SponsoredMessage.ends_at >= now,
            or_(
                SponsoredMessage.max_displays == 0,
                SponsoredMessage.display_count < SponsoredMessage.max_displays,
            ),
        )
        .order_by(SponsoredMessage.display_count.asc(), SponsoredMessage.id.asc())
        .limit(1)
    )
    if ad:
        ad.display_count += 1
        await session.commit()
    return ad


async def send_sponsored_message(message: Message, ad: SponsoredMessage) -> None:
    keyboard = None
    if ad.button_text and ad.button_url:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(ad.button_text, url=ad.button_url)]])
    await message.reply_text(
        f"Sponsored: {ad.title}\n\n{ad.message_text}",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
