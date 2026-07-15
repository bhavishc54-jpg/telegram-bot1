"""FastAPI application exposing the verified Paddle webhook route."""

from __future__ import annotations

import json
import logging
import secrets

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Bot

from app.config import ConfigurationError, Settings
from app.services.paddle_service import (
    PaddleWebhookError,
    process_paddle_event,
    verify_paddle_signature,
)

logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 1_000_000


def create_api(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> FastAPI:
    api = FastAPI(title="Telegram Bot Payment Webhooks", docs_url=None, redoc_url=None)

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/", response_class=HTMLResponse)
    async def paddle_checkout_page() -> HTMLResponse:
        if not settings.enable_paddle or not settings.paddle_client_token:
            return HTMLResponse("Paddle checkout is not configured.", status_code=503)
        nonce = secrets.token_urlsafe(18)
        token_json = json.dumps(settings.paddle_client_token).replace("<", "\\u003c")
        environment_json = json.dumps(settings.paddle_env)
        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Secure Paddle Checkout</title>
  <script src="https://cdn.paddle.com/paddle/v2/paddle.js"></script>
  <style nonce="{nonce}">
    body {{ font-family: system-ui, sans-serif; max-width: 680px;
            margin: 3rem auto; padding: 1rem; }}
    .notice {{ color: #374151; }}
  </style>
</head>
<body>
  <h1>Secure checkout</h1>
  <p class="notice">Paddle will open your checkout.
    Access is added only after webhook confirmation.</p>
  <p id="error" role="alert"></p>
  <script nonce="{nonce}">
    const environment = {environment_json};
    const transactionId = new URLSearchParams(window.location.search).get("_ptxn");
    if (!transactionId || !/^txn_[a-z0-9]+$/i.test(transactionId)) {{
      document.getElementById("error").textContent = "Missing or invalid transaction.";
    }} else {{
      if (environment === "sandbox") Paddle.Environment.set("sandbox");
      Paddle.Initialize({{ token: {token_json} }});
      Paddle.Checkout.open({{ transactionId }});
    }}
  </script>
</body>
</html>"""
        headers = {
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; "
                f"script-src 'nonce-{nonce}' https://cdn.paddle.com; "
                f"style-src 'nonce-{nonce}'; "
                "connect-src https://*.paddle.com; frame-src https://*.paddle.com; "
                "img-src data: https://*.paddle.com; base-uri 'none'; form-action https://*.paddle.com"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }
        return HTMLResponse(body, headers=headers)

    @api.post("/webhooks/paddle", status_code=status.HTTP_200_OK)
    async def paddle_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
        try:
            settings.require_paddle_webhook()
        except ConfigurationError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Webhook is not configured."
            ) from exc
        raw_body = await request.body()
        if not raw_body or len(raw_body) > MAX_WEBHOOK_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Invalid body size.")
        signature = request.headers.get("Paddle-Signature", "")
        try:
            verify_paddle_signature(
                raw_body,
                signature,
                settings.paddle_webhook_secret,
                settings.paddle_webhook_tolerance_seconds,
            )
        except PaddleWebhookError as exc:
            logger.warning("Rejected Paddle webhook: %s", type(exc).__name__)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature.") from exc
        try:
            event = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON.") from exc
        if not isinstance(event, dict):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid event.")
        try:
            async with session_factory() as session:
                result = await process_paddle_event(session, event)
        except PaddleWebhookError as exc:
            logger.warning("Rejected signed Paddle event: %s", type(exc).__name__)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Payment validation failed.") from exc
        if result.fulfillment and result.fulfillment.fulfilled and result.user_id:
            background_tasks.add_task(
                _notify_payment_success,
                bot,
                result.user_id,
                result.fulfillment.credit_balance,
                result.fulfillment.resumed.message if result.fulfillment.resumed else None,
            )
        return {"status": "processed" if result.handled else "ignored"}

    return api


async def _notify_payment_success(
    bot: Bot, user_id: int, credit_balance: int, resumed_message: str | None
) -> None:
    text = f"Payment successful. Credits added. Current balance: {credit_balance}."
    if resumed_message:
        text += f"\n\n{resumed_message}"
    try:
        await bot.send_message(user_id, text)
    except Exception as exc:
        logger.warning("Could not send payment notification: %s", type(exc).__name__)
