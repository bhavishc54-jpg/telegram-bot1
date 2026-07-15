"""Paddle sandbox/live checkout creation and verified webhook processing."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    Payment,
    PaymentProvider,
    PaymentStatus,
    ProcessedPaymentEvent,
    Product,
)
from app.services.payment_service import (
    FulfillmentOutcome,
    fulfill_payment,
    mark_payment_terminal,
)


class PaddleError(RuntimeError):
    """Safe Paddle error that never includes credentials or response bodies."""


class PaddleWebhookError(ValueError):
    """Raised when a signed webhook does not match the expected payment."""


@dataclass(frozen=True, slots=True)
class PaddleCheckout:
    transaction_id: str
    checkout_url: str
    amount: int
    currency: str


@dataclass(frozen=True, slots=True)
class PaddleEventResult:
    handled: bool
    payment_id: int | None = None
    user_id: int | None = None
    fulfillment: FulfillmentOutcome | None = None
    event_type: str = ""


class PaddleClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        settings.require_paddle_checkout()
        self.settings = settings
        self._client = client

    async def create_transaction(self, payment: Payment, product: Product) -> PaddleCheckout:
        if not product.paddle_product_id or not product.paddle_price_id:
            raise PaddleError("Paddle product and price IDs are not configured.")
        payload = {
            "items": [{"price_id": product.paddle_price_id, "quantity": 1}],
            "collection_mode": "automatic",
            "custom_data": {
                "internal_order_id": payment.internal_order_id,
                "telegram_user_id": str(payment.user_id),
                "product_code": product.product_code,
            },
            "checkout": {"url": self.settings.frontend_url},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.paddle_api_key}",
            "Content-Type": "application/json",
            "Paddle-Version": "1",
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.post(
                f"{self.settings.paddle_api_base_url}/transactions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PaddleError("Paddle checkout creation failed.") from exc
        finally:
            if owns_client:
                await client.aclose()
        return _parse_checkout(body, payment, product, self.settings.paddle_env)


def _parse_checkout(
    body: dict[str, Any], payment: Payment, product: Product, paddle_env: str
) -> PaddleCheckout:
    data = body.get("data")
    if not isinstance(data, dict):
        raise PaddleError("Paddle returned an invalid checkout response.")
    transaction_id = data.get("id")
    checkout = data.get("checkout")
    checkout_url = checkout.get("url") if isinstance(checkout, dict) else None
    items = data.get("items")
    custom_data = data.get("custom_data")
    if not isinstance(transaction_id, str) or not transaction_id.startswith("txn_"):
        raise PaddleError("Paddle returned an invalid transaction ID.")
    if not isinstance(checkout_url, str) or not _safe_checkout_url(checkout_url, paddle_env):
        raise PaddleError("Paddle returned an unsafe checkout URL.")
    if (
        not isinstance(custom_data, dict)
        or custom_data.get("internal_order_id") != payment.internal_order_id
        or str(custom_data.get("telegram_user_id")) != str(payment.user_id)
        or custom_data.get("product_code") != product.product_code
    ):
        raise PaddleError("Paddle checkout order reference did not match.")
    item = _matching_item(items, product)
    price = item["price"]
    unit_price = price.get("unit_price")
    if not isinstance(unit_price, dict):
        raise PaddleError("Paddle did not return an expected price amount.")
    try:
        amount = int(unit_price["amount"])
        currency = str(unit_price["currency_code"]).upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise PaddleError("Paddle returned an invalid price amount.") from exc
    if amount <= 0 or currency != product.currency:
        raise PaddleError("Paddle checkout price or currency did not match the product.")
    return PaddleCheckout(transaction_id, checkout_url, amount, currency)


def _matching_item(items: object, product: Product) -> dict[str, Any]:
    return _matching_item_ids(items, product.paddle_price_id, product.paddle_product_id)


def _matching_item_ids(
    items: object, expected_price_id: object, expected_product_id: object
) -> dict[str, Any]:
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise PaddleError("Paddle checkout must contain exactly one configured product.")
    item = items[0]
    price = item.get("price")
    if (
        item.get("quantity") != 1
        or not isinstance(price, dict)
        or price.get("id") != expected_price_id
        or price.get("product_id") != expected_product_id
    ):
        raise PaddleError("Paddle checkout product did not match.")
    return item


def _safe_checkout_url(url: str, paddle_env: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    return paddle_env == "sandbox" or parsed.scheme == "https"


async def attach_paddle_checkout(
    session: AsyncSession,
    payment: Payment,
    product: Product,
    client: PaddleClient,
) -> PaddleCheckout:
    checkout = await client.create_transaction(payment, product)
    payment.paddle_transaction_id = checkout.transaction_id
    payment.checkout_url = checkout.checkout_url
    payment.amount = checkout.amount
    payment.currency = checkout.currency
    payment.metadata_json = json.dumps(
        {
            "expected_paddle_product_id": product.paddle_product_id,
            "expected_paddle_price_id": product.paddle_price_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    await session.flush()
    return checkout


def verify_paddle_signature(
    raw_body: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = 5,
    *,
    now: int | None = None,
) -> None:
    if not raw_body or not signature_header or not secret:
        raise PaddleWebhookError("Missing webhook signature data.")
    parts: dict[str, list[str]] = {}
    for segment in signature_header.split(";"):
        key, separator, value = segment.partition("=")
        if separator and key and value:
            parts.setdefault(key, []).append(value)
    try:
        timestamp = int(parts["ts"][0])
        signatures = parts["h1"]
    except (KeyError, IndexError, ValueError) as exc:
        raise PaddleWebhookError("Malformed Paddle signature header.") from exc
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        raise PaddleWebhookError("Paddle signature timestamp is outside the allowed window.")
    signed_payload = str(timestamp).encode() + b":" + raw_body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise PaddleWebhookError("Invalid Paddle webhook signature.")


async def process_paddle_event(session: AsyncSession, event: dict[str, Any]) -> PaddleEventResult:
    event_id = event.get("event_id")
    event_type = event.get("event_type")
    data = event.get("data")
    if (
        not isinstance(event_id, str)
        or not event_id.startswith("evt_")
        or not isinstance(event_type, str)
        or not isinstance(data, dict)
    ):
        raise PaddleWebhookError("Invalid Paddle event envelope.")

    if event_type == "transaction.completed":
        payment, product = await _validated_transaction_payment(session, data)
        outcome = await fulfill_payment(
            session,
            payment.id,
            event_id,
            paddle_event_id=event_id,
            paddle_subscription_id=_optional_id(data.get("subscription_id"), "sub_"),
            paddle_customer_id=_optional_id(data.get("customer_id"), "ctm_"),
        )
        await session.commit()
        return PaddleEventResult(True, payment.id, payment.user_id, outcome, event_type)

    if event_type in {"transaction.payment_failed", "transaction.canceled"}:
        payment = await _find_payment(session, data)
        if payment is None:
            raise PaddleWebhookError("No matching internal Paddle payment.")
        status = (
            PaymentStatus.FAILED
            if event_type == "transaction.payment_failed"
            else PaymentStatus.CANCELED
        )
        await mark_payment_terminal(session, payment, event_id, status, {"event_type": event_type})
        await session.commit()
        return PaddleEventResult(True, payment.id, payment.user_id, None, event_type)

    subscription_events = {
        "subscription.created",
        "subscription.activated",
        "subscription.updated",
        "subscription.canceled",
        "subscription.past_due",
    }
    if event_type in subscription_events:
        payment = await _find_subscription_payment(session, data)
        if payment is None:
            return PaddleEventResult(False, event_type=event_type)
        duplicate = await session.scalar(
            select(ProcessedPaymentEvent).where(
                ProcessedPaymentEvent.provider == PaymentProvider.PADDLE,
                ProcessedPaymentEvent.event_id == event_id,
            )
        )
        if duplicate is None:
            payment.paddle_subscription_id = _optional_id(data.get("id"), "sub_")
            payment.paddle_customer_id = _optional_id(data.get("customer_id"), "ctm_")
            payment.metadata_json = json.dumps(
                {"subscription_status": data.get("status"), "event_type": event_type},
                separators=(",", ":"),
                sort_keys=True,
            )
            session.add(
                ProcessedPaymentEvent(
                    provider=PaymentProvider.PADDLE,
                    event_id=event_id,
                    payment_id=payment.id,
                )
            )
            await session.commit()
        return PaddleEventResult(True, payment.id, payment.user_id, None, event_type)

    return PaddleEventResult(False, event_type=event_type)


async def _validated_transaction_payment(
    session: AsyncSession, data: dict[str, Any]
) -> tuple[Payment, Product]:
    payment = await _find_payment(session, data)
    if payment is None or payment.provider is not PaymentProvider.PADDLE:
        raise PaddleWebhookError("No matching internal Paddle payment.")
    if data.get("id") != payment.paddle_transaction_id or data.get("status") != "completed":
        raise PaddleWebhookError("Paddle transaction ID or status did not match.")
    product = await session.get(Product, payment.product_id)
    if product is None:
        raise PaddleWebhookError("Payment product no longer exists.")
    custom_data = data.get("custom_data")
    if (
        not isinstance(custom_data, dict)
        or custom_data.get("internal_order_id") != payment.internal_order_id
        or str(custom_data.get("telegram_user_id")) != str(payment.user_id)
        or custom_data.get("product_code") != product.product_code
    ):
        raise PaddleWebhookError("Paddle custom data did not match the internal order.")
    try:
        metadata = json.loads(payment.metadata_json or "{}")
    except json.JSONDecodeError as exc:
        raise PaddleWebhookError("Internal Paddle payment metadata was invalid.") from exc
    expected_price_id = metadata.get("expected_paddle_price_id") or product.paddle_price_id
    expected_product_id = metadata.get("expected_paddle_product_id") or product.paddle_product_id
    try:
        item = _matching_item_ids(data.get("items"), expected_price_id, expected_product_id)
    except PaddleError as exc:
        raise PaddleWebhookError(str(exc)) from exc
    unit_price = item["price"].get("unit_price")
    if not isinstance(unit_price, dict):
        raise PaddleWebhookError("Paddle webhook price was missing.")
    try:
        amount = int(unit_price["amount"])
        currency = str(unit_price["currency_code"]).upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise PaddleWebhookError("Paddle webhook price was invalid.") from exc
    if amount != payment.amount or currency != payment.currency:
        raise PaddleWebhookError("Paddle amount or currency did not match the internal payment.")
    if str(data.get("currency_code", "")).upper() != payment.currency:
        raise PaddleWebhookError("Paddle transaction currency did not match.")
    return payment, product


async def _find_payment(session: AsyncSession, data: dict[str, Any]) -> Payment | None:
    transaction_id = data.get("id")
    if isinstance(transaction_id, str):
        payment = await session.scalar(
            select(Payment).where(Payment.paddle_transaction_id == transaction_id)
        )
        if payment:
            return payment
    custom_data = data.get("custom_data")
    order_id = custom_data.get("internal_order_id") if isinstance(custom_data, dict) else None
    if isinstance(order_id, str):
        return await session.scalar(select(Payment).where(Payment.internal_order_id == order_id))
    return None


async def _find_subscription_payment(session: AsyncSession, data: dict[str, Any]) -> Payment | None:
    transaction_id = data.get("transaction_id")
    if isinstance(transaction_id, str):
        payment = await session.scalar(
            select(Payment).where(Payment.paddle_transaction_id == transaction_id)
        )
        if payment:
            return payment
    subscription_id = data.get("id")
    if isinstance(subscription_id, str):
        payment = await session.scalar(
            select(Payment).where(Payment.paddle_subscription_id == subscription_id)
        )
        if payment:
            return payment
    return await _find_payment(session, data)


def _optional_id(value: object, prefix: str) -> str | None:
    return value if isinstance(value, str) and value.startswith(prefix) else None
