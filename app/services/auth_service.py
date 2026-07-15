"""Telegram-ID based owner and admin authorization."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole


def is_owner(user_id: int | None, owner_user_id: int) -> bool:
    return user_id is not None and user_id == owner_user_id


async def is_admin(session: AsyncSession, user_id: int | None, owner_user_id: int) -> bool:
    if is_owner(user_id, owner_user_id):
        return True
    if user_id is None:
        return False
    user = await session.get(User, user_id)
    return bool(user and not user.is_banned and user.role is UserRole.ADMIN)
