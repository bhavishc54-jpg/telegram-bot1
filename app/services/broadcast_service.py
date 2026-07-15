"""Confirmed broadcast delivery with pacing and progress callbacks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from telegram import Bot, InlineKeyboardMarkup
from telegram.error import Forbidden, RetryAfter, TelegramError


@dataclass(frozen=True, slots=True)
class BroadcastPayload:
    source_chat_id: int
    source_message_id: int
    content_type: str
    reply_markup: InlineKeyboardMarkup | None = None


@dataclass(frozen=True, slots=True)
class BroadcastResult:
    successful: int
    failed: int


async def deliver_broadcast(
    bot: Bot,
    user_ids: Sequence[int],
    payload: BroadcastPayload,
    delay_seconds: float,
    progress: Callable[[int, int, int], Awaitable[None]] | None = None,
) -> BroadcastResult:
    successful = 0
    failed = 0
    total = len(user_ids)
    for index, user_id in enumerate(user_ids, start=1):
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=payload.source_chat_id,
                message_id=payload.source_message_id,
                reply_markup=payload.reply_markup,
            )
            successful += 1
        except RetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 0.5)
            try:
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=payload.source_chat_id,
                    message_id=payload.source_message_id,
                    reply_markup=payload.reply_markup,
                )
                successful += 1
            except TelegramError:
                failed += 1
        except (Forbidden, TelegramError):
            failed += 1
        if progress and (index % 25 == 0 or index == total):
            await progress(index, successful, failed)
        if delay_seconds:
            await asyncio.sleep(delay_seconds)
    return BroadcastResult(successful=successful, failed=failed)
