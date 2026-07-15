"""Subscription-related user callbacks.

Payments remain intentionally unavailable until a provider is configured.
"""

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


async def payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Payments are not connected yet. The bot never stores card information "
            "or payment credentials."
        )


def handlers() -> list[object]:
    return [CommandHandler("paymentstatus", payment_status)]
