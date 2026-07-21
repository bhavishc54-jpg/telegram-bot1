"""Application entry point."""

from __future__ import annotations

import asyncio
import logging

from telegram.constants import ChatType
from telegram.ext import Application, ApplicationBuilder, ContextTypes

from app.config import ConfigurationError, Settings
from app.database import create_engine_and_session, initialize_database
from app.handlers.admin import handlers as admin_handlers
from app.handlers.private_messages import handlers as private_message_handlers
from app.handlers.source_channel import handlers as source_channel_handlers
from app.handlers.subscribers import handlers as subscriber_handlers
from app.migrations import run_migrations
from app.services.diskwala_client import DiskWalaClient
from app.utils.logging import configure_logging
from app.utils.terminal import terminal_log
from app.workers.queue_worker import QueueWorker

logger = logging.getLogger(__name__)

POLLING_ALLOWED_UPDATES = ["message", "channel_post", "edited_channel_post"]


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(
        "Unhandled update error: %s",
        type(context.error).__name__,
        exc_info=(
            (type(context.error), context.error, context.error.__traceback__)
            if context.error
            else None
        ),
    )
    effective_message = getattr(update, "effective_message", None)
    effective_chat = getattr(update, "effective_chat", None)
    if effective_message:
        if effective_chat and effective_chat.type == ChatType.CHANNEL:
            return
        await effective_message.reply_text("Something went wrong. Please try again later.")


def build_application(settings: Settings) -> Application:
    engine, session_factory = create_engine_and_session(settings)
    diskwala_client = DiskWalaClient(settings)

    async def post_init(application: Application) -> None:
        await asyncio.to_thread(run_migrations, settings.database_url)
        await initialize_database(engine, session_factory, settings)
        if settings.app_mode == "polling":
            await application.bot.delete_webhook(drop_pending_updates=False)
            logger.info("Deleted any existing webhook before polling.")
        if settings.diskwala_conversion_configured:
            await diskwala_client.start()
            logger.info("Telethon converter client connected successfully.")
        else:
            logger.warning(
                "Telethon converter is not fully configured; DiskWala conversion will fail."
            )
        worker = QueueWorker(application.bot, session_factory, settings, diskwala_client)
        worker_task = asyncio.create_task(worker.run(), name="queue-worker")
        application.bot_data["queue_worker"] = worker
        application.bot_data["queue_worker_task"] = worker_task
        if settings.app_mode == "polling":
            terminal_log(
                "BOT STARTED",
                "POLLING ACTIVE",
                "WAITING FOR TELEGRAM UPDATES",
            )
        logger.info(
            "Bot startup complete. mode=%s source_channel_configured=%s",
            settings.app_mode,
            settings.source_channel_id is not None,
        )

    async def post_shutdown(application: Application) -> None:
        worker: QueueWorker | None = application.bot_data.get("queue_worker")
        worker_task: asyncio.Task | None = application.bot_data.get("queue_worker_task")
        if worker is not None:
            worker.stop()
        if worker_task is not None:
            await asyncio.wait([worker_task], timeout=5)
        await diskwala_client.close()
        await engine.dispose()
        logger.info("Bot shutdown complete.")

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
            "diskwala_client": diskwala_client,
        }
    )
    for handler in subscriber_handlers():
        application.add_handler(handler)
    for handler in admin_handlers():
        application.add_handler(handler)
    for handler in source_channel_handlers():
        application.add_handler(handler)
    for handler in private_message_handlers():
        application.add_handler(handler)
    application.add_error_handler(on_error)
    return application


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    configure_logging(settings.log_level)
    app = build_application(settings)
    if settings.app_mode == "webhook":
        app.run_webhook(
            listen="127.0.0.1",
            port=8443,
            webhook_url=settings.webhook_url,
            secret_token=settings.webhook_secret,
            allowed_updates=POLLING_ALLOWED_UPDATES,
            drop_pending_updates=False,
        )
    else:
        app.run_polling(allowed_updates=POLLING_ALLOWED_UPDATES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
