"""Application entry point."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes

from app.config import ConfigurationError, Settings
from app.database import create_engine_and_session, initialize_database
from app.handlers.admin import handlers as admin_handlers
from app.handlers.ads import handlers as ad_handlers
from app.handlers.broadcast import handlers as broadcast_handlers
from app.handlers.links import handlers as link_handlers
from app.handlers.payment_admin import handlers as payment_admin_handlers
from app.handlers.subscriptions import handlers as subscription_handlers
from app.handlers.user import handlers as user_handlers
from app.middleware.access import handler as access_guard_handler
from app.middleware.rate_limit import CooldownRateLimiter
from app.migrations import run_migrations
from app.utils.logging import configure_logging
from app.web_server import start_webhook_server, stop_webhook_server

logger = logging.getLogger(__name__)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Log only the exception type. Third-party error messages can contain request details.
    logger.error("Unhandled update error: %s", type(context.error).__name__)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Something went wrong. Please try again later.")


def build_application(settings: Settings) -> Application:
    engine, session_factory = create_engine_and_session(settings)

    async def post_init(application: Application) -> None:
        await asyncio.to_thread(run_migrations, settings.database_url)
        await initialize_database(engine, session_factory, settings)
        if settings.enable_paddle:
            server, server_task = await start_webhook_server(
                settings, session_factory, application.bot
            )
            application.bot_data["webhook_server"] = server
            application.bot_data["webhook_server_task"] = server_task
        logger.info("Database initialized; bot is starting.")

    async def post_shutdown(application: Application) -> None:
        server = application.bot_data.get("webhook_server")
        server_task = application.bot_data.get("webhook_server_task")
        if server and server_task:
            await stop_webhook_server(server, server_task)
        await engine.dispose()
        logger.info("Database connection closed.")

    application = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data.update(
        {
            "settings": settings,
            "session_factory": session_factory,
            "rate_limiter": CooldownRateLimiter(settings.request_cooldown_seconds),
        }
    )
    application.add_handler(access_guard_handler(), group=-100)
    for handler in user_handlers():
        application.add_handler(handler)
    for handler in broadcast_handlers():
        application.add_handler(handler, group=-1)
    for handler in admin_handlers():
        application.add_handler(handler)
    for handler in payment_admin_handlers():
        application.add_handler(handler)
    for handler in ad_handlers():
        application.add_handler(handler)
    for handler in link_handlers():
        application.add_handler(handler)
    for handler in subscription_handlers():
        application.add_handler(handler)
    application.add_error_handler(on_error)
    return application


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    configure_logging(settings.log_level)
    build_application(settings).run_polling(
        allowed_updates=Update.ALL_TYPES, drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
