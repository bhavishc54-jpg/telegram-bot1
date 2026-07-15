"""Application entry point."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes

from app.config import ConfigurationError, Settings
from app.database import create_engine_and_session, initialize_database
from app.handlers.admin import handlers as admin_handlers
from app.handlers.links import handlers as link_handlers
from app.handlers.subscriptions import handlers as subscription_handlers
from app.handlers.user import handlers as user_handlers
from app.middleware.rate_limit import CooldownRateLimiter
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled update error: %s", type(context.error).__name__, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Something went wrong. Please try again later.")


def build_application(settings: Settings) -> Application:
    engine, session_factory = create_engine_and_session(settings)

    async def post_init(application: Application) -> None:
        await initialize_database(engine, session_factory, settings)
        logger.info("Database initialized; bot is starting.")

    async def post_shutdown(application: Application) -> None:
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
    for handler in user_handlers():
        application.add_handler(handler)
    for handler in admin_handlers():
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
