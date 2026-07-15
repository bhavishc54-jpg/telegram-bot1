"""User registration and settings helpers."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import User as TelegramUser

from app.models import BotSetting, User, UserRole, utcnow


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
