"""Lifecycle helpers for the embedded FastAPI/Uvicorn webhook server."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager

import uvicorn
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Bot

from app.api import create_api
from app.config import Settings


class NoSignalServer(uvicorn.Server):
    """Let python-telegram-bot retain ownership of process signals."""

    @contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        yield


async def start_webhook_server(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> tuple[NoSignalServer, asyncio.Task[None]]:
    config = uvicorn.Config(
        create_api(settings, session_factory, bot),
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    server = NoSignalServer(config)
    task = asyncio.create_task(server.serve(), name="paddle-webhook-server")
    for _ in range(50):
        if server.started or task.done():
            break
        await asyncio.sleep(0.1)
    if task.done():
        exception = task.exception()
        if exception:
            raise RuntimeError("Webhook server failed to start.") from exception
    return server, task


async def stop_webhook_server(server: NoSignalServer, task: asyncio.Task[None]) -> None:
    server.should_exit = True
    try:
        await asyncio.wait_for(task, timeout=10)
    except TimeoutError:
        task.cancel()
