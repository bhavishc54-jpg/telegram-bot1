import pytest

from app.middleware.rate_limit import CooldownRateLimiter


@pytest.mark.asyncio
async def test_cooldown_rate_limit() -> None:
    now = [100.0]
    limiter = CooldownRateLimiter(3.0, clock=lambda: now[0])

    assert await limiter.check(10) == 0
    assert await limiter.check(10) == pytest.approx(3.0)
    assert await limiter.check(11) == 0

    now[0] += 3.0
    assert await limiter.check(10) == 0
