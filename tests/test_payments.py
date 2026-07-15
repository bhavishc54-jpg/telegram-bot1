from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta

import httpx
import pytest

from app.api import create_api
from app.config import Settings
from app.database import DEFAULT_PRODUCTS
from app.keyboards.payments import purchase_options_keyboard
from app.models import (
    Payment,
    PaymentProvider,
    PaymentStatus,
    PendingRequestStatus,
    Product,
    SubscriptionPlan,
    User,
)
from app.services.paddle_service import (
    PaddleClient,
    PaddleWebhookError,
    attach_paddle_checkout,
    process_paddle_event,
)
from app.services.payment_service import (
    create_pending_payment,
    fulfill_payment,
    generate_invoice_payload,
)
from app.services.pending_request_service import (
    consume_access,
    process_validated_request,
    save_pending_request,
)
from app.services.subscription_service import subscription_is_active

VALID_URL = "https://diskwala.com/file/paid-test"
SECRET = "pdl_ntfset_test_secret"


def settings(**overrides) -> Settings:
    values = {
        "bot_token": "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789",
        "owner_user_id": 999,
        "database_url": "sqlite:///:memory:",
        "enable_telegram_stars": True,
        "enable_paddle": True,
        "paddle_env": "sandbox",
        "paddle_api_key": "test-api-key",
        "paddle_client_token": "test_client_token",
        "paddle_webhook_secret": SECRET,
    }
    values.update(overrides)
    return Settings(**values)


async def add_user(session, user_id: int = 100, *, credits: int = 0) -> User:
    user = User(telegram_id=user_id, first_name="Buyer", credits=credits)
    session.add(user)
    await session.flush()
    return user


async def add_stars_product(session, code: str = "stars_test", credits: int = 10) -> Product:
    product = Product(
        product_code=code,
        name="Stars test pack",
        description="Test credits",
        provider=PaymentProvider.TELEGRAM_STARS,
        credits=credits,
        stars_price=10,
        currency="XTR",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def add_paddle_product(
    session, code: str = "paddle_test", *, credits: int = 100, premium_days: int = 0
) -> Product:
    product = Product(
        product_code=code,
        name="Paddle test pack",
        description="Test Paddle purchase",
        provider=PaymentProvider.PADDLE,
        credits=credits,
        premium_duration_days=premium_days,
        paddle_product_id="pro_test_product",
        paddle_price_id="pri_test_price",
        currency="USD",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


def paddle_event(payment: Payment, product: Product, event_id: str = "evt_test_1") -> dict:
    return {
        "event_id": event_id,
        "event_type": "transaction.completed",
        "data": {
            "id": payment.paddle_transaction_id,
            "status": "completed",
            "currency_code": payment.currency,
            "customer_id": "ctm_test_customer",
            "subscription_id": None,
            "custom_data": {
                "internal_order_id": payment.internal_order_id,
                "telegram_user_id": str(payment.user_id),
                "product_code": product.product_code,
            },
            "items": [
                {
                    "quantity": 1,
                    "price": {
                        "id": product.paddle_price_id,
                        "product_id": product.paddle_product_id,
                        "unit_price": {"amount": str(payment.amount), "currency_code": "USD"},
                    },
                }
            ],
        },
    }


def signed_headers(raw_body: bytes, *, valid: bool = True) -> dict[str, str]:
    timestamp = int(time.time())
    digest = hmac.new(
        SECRET.encode(), str(timestamp).encode() + b":" + raw_body, hashlib.sha256
    ).hexdigest()
    if not valid:
        digest = "0" * 64
    return {"Paddle-Signature": f"ts={timestamp};h1={digest}"}


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, user_id: int, text: str) -> None:
        self.messages.append((user_id, text))


def test_default_product_definitions() -> None:
    assert len(DEFAULT_PRODUCTS) == 8
    assert {product["product_code"] for product in DEFAULT_PRODUCTS} == {
        "stars_10",
        "stars_50",
        "stars_100",
        "paddle_starter",
        "paddle_100",
        "paddle_500",
        "paddle_premium_monthly",
        "paddle_premium_yearly",
    }


def test_stars_invoice_payload_generation() -> None:
    first = generate_invoice_payload("ord_safe")
    second = generate_invoice_payload("ord_safe")
    assert first.startswith("stars:ord_safe:")
    assert first != second
    assert len(first.encode()) <= 128


@pytest.mark.asyncio
async def test_stars_successful_payment_adds_credits(session) -> None:
    user = await add_user(session)
    product = await add_stars_product(session)
    payment = await create_pending_payment(session, user.telegram_id, product)
    outcome = await fulfill_payment(
        session,
        payment.id,
        "stars_charge_1",
        telegram_payment_charge_id="stars_charge_1",
    )
    await session.commit()
    assert outcome.fulfilled is True
    assert user.credits == 10
    assert payment.status is PaymentStatus.PAID


@pytest.mark.asyncio
async def test_duplicate_stars_payment_does_not_add_twice(session) -> None:
    user = await add_user(session)
    product = await add_stars_product(session)
    payment = await create_pending_payment(session, user.telegram_id, product)
    await fulfill_payment(session, payment.id, "stars_charge_2")
    duplicate = await fulfill_payment(session, payment.id, "stars_charge_2")
    await session.commit()
    assert duplicate.duplicate is True
    assert user.credits == 10


@pytest.mark.asyncio
async def test_paddle_checkout_creation(session) -> None:
    user = await add_user(session)
    product = await add_paddle_product(session)
    payment = await create_pending_payment(session, user.telegram_id, product)

    def responder(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        assert sent["custom_data"]["telegram_user_id"] == str(user.telegram_id)
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "txn_test_checkout",
                    "checkout": {"url": "https://checkout.paddle.com/test"},
                    "custom_data": sent["custom_data"],
                    "items": [
                        {
                            "quantity": 1,
                            "price": {
                                "id": product.paddle_price_id,
                                "product_id": product.paddle_product_id,
                                "unit_price": {"amount": "1250", "currency_code": "USD"},
                            },
                        }
                    ],
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http_client:
        checkout = await attach_paddle_checkout(
            session, payment, product, PaddleClient(settings(), http_client)
        )
    assert checkout.transaction_id == "txn_test_checkout"
    assert payment.amount == 1250
    assert payment.checkout_url == "https://checkout.paddle.com/test"


@pytest.mark.asyncio
async def test_valid_paddle_webhook_and_duplicate(session_factory) -> None:
    async with session_factory() as session:
        user = await add_user(session)
        product = await add_paddle_product(session)
        payment = await create_pending_payment(session, user.telegram_id, product)
        payment.paddle_transaction_id = "txn_test_valid"
        payment.amount = 1250
        await session.commit()
        event = paddle_event(payment, product)
    raw_body = json.dumps(event, separators=(",", ":")).encode()
    bot = FakeBot()
    api = create_api(settings(), session_factory, bot)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test"
    ) as client:
        first = await client.post(
            "/webhooks/paddle", content=raw_body, headers=signed_headers(raw_body)
        )
        second = await client.post(
            "/webhooks/paddle", content=raw_body, headers=signed_headers(raw_body)
        )
    assert first.status_code == 200
    assert second.status_code == 200
    async with session_factory() as session:
        saved_user = await session.get(User, user.telegram_id)
        assert saved_user and saved_user.credits == 100
    assert len(bot.messages) == 1


@pytest.mark.asyncio
async def test_invalid_paddle_webhook_signature(session_factory) -> None:
    raw_body = b'{"event_id":"evt_bad","event_type":"transaction.completed","data":{}}'
    api = create_api(settings(), session_factory, FakeBot())  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/paddle", content=raw_body, headers=signed_headers(raw_body, valid=False)
        )
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_field", ["product", "amount"])
async def test_wrong_paddle_product_or_amount(session, wrong_field: str) -> None:
    user = await add_user(session)
    product = await add_paddle_product(session)
    payment = await create_pending_payment(session, user.telegram_id, product)
    payment.paddle_transaction_id = "txn_test_wrong"
    payment.amount = 1250
    await session.flush()
    event = paddle_event(payment, product)
    if wrong_field == "product":
        event["data"]["items"][0]["price"]["id"] = "pri_wrong"
    else:
        event["data"]["items"][0]["price"]["unit_price"]["amount"] = "999"
    with pytest.raises(PaddleWebhookError):
        await process_paddle_event(session, event)
    assert user.credits == 0


@pytest.mark.asyncio
async def test_premium_activation_after_payment(session) -> None:
    user = await add_user(session)
    product = await add_paddle_product(session, "paddle_premium_test", credits=0, premium_days=30)
    payment = await create_pending_payment(session, user.telegram_id, product)
    payment.amount = 1000
    outcome = await fulfill_payment(session, payment.id, "evt_premium")
    assert outcome.fulfilled is True
    assert user.plan is SubscriptionPlan.PREMIUM
    assert subscription_is_active(user)


@pytest.mark.asyncio
async def test_pending_request_resumes_after_payment(session) -> None:
    user = await add_user(session)
    pending = await save_pending_request(session, user.telegram_id, VALID_URL)
    product = await add_stars_product(session)
    payment = await create_pending_payment(session, user.telegram_id, product)
    outcome = await fulfill_payment(session, payment.id, "stars_resume")
    assert outcome.resumed and outcome.resumed.completed
    assert pending.status is PendingRequestStatus.COMPLETED
    assert pending.payment_id == payment.id
    assert user.credits == 9


@pytest.mark.asyncio
async def test_expired_pending_request_does_not_resume(session) -> None:
    user = await add_user(session)
    pending = await save_pending_request(
        session, user.telegram_id, VALID_URL, expires_in=timedelta(seconds=-1)
    )
    product = await add_stars_product(session)
    payment = await create_pending_payment(session, user.telegram_id, product)
    outcome = await fulfill_payment(session, payment.id, "stars_expired")
    assert outcome.resumed is None
    assert pending.status is PendingRequestStatus.EXPIRED
    assert user.credits == 10


@pytest.mark.asyncio
async def test_user_without_credits_gets_payment_buttons(session) -> None:
    user = await add_user(session)
    user.daily_usage = 2
    product = await add_stars_product(session)
    decision = await consume_access(session, user)
    keyboard = purchase_options_keyboard([product], settings())
    assert decision.allowed is False
    assert keyboard is not None


@pytest.mark.asyncio
async def test_user_with_credits_can_process_link(session) -> None:
    user = await add_user(session, credits=1)
    user.daily_usage = 2
    decision = await consume_access(session, user)
    outcome = await process_validated_request(session, user, VALID_URL, decision)
    assert decision.access_source == "credit"
    assert outcome.completed is True
    assert user.credits == 0


@pytest.mark.asyncio
async def test_credit_is_refunded_when_processing_fails(session) -> None:
    user = await add_user(session, credits=1)
    user.daily_usage = 2
    decision = await consume_access(session, user)
    outcome = await process_validated_request(
        session, user, "https://example.com/not-supported", decision
    )
    assert outcome.completed is False
    assert user.credits == 1


@pytest.mark.asyncio
async def test_failed_paddle_payment_is_recorded(session) -> None:
    user = await add_user(session)
    product = await add_paddle_product(session)
    payment = await create_pending_payment(session, user.telegram_id, product)
    payment.paddle_transaction_id = "txn_test_failed"
    event = {
        "event_id": "evt_test_failed",
        "event_type": "transaction.payment_failed",
        "data": {"id": payment.paddle_transaction_id},
    }
    result = await process_paddle_event(session, event)
    assert result.handled is True
    assert payment.status is PaymentStatus.FAILED
    assert user.credits == 0
