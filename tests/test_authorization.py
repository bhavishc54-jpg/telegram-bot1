import pytest

from app.models import User, UserRole
from app.services.auth_service import is_admin, is_owner


def test_owner_authorization() -> None:
    assert is_owner(123, 123) is True
    assert is_owner(456, 123) is False
    assert is_owner(None, 123) is False


@pytest.mark.asyncio
async def test_admin_authorization(session) -> None:
    session.add_all(
        [
            User(telegram_id=10, first_name="Admin", role=UserRole.ADMIN),
            User(telegram_id=11, first_name="User", role=UserRole.USER),
            User(telegram_id=12, first_name="Banned", role=UserRole.ADMIN, is_banned=True),
        ]
    )
    await session.commit()

    assert await is_admin(session, 1, 1) is True
    assert await is_admin(session, 10, 1) is True
    assert await is_admin(session, 11, 1) is False
    assert await is_admin(session, 12, 1) is False
