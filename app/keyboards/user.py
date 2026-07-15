"""User-facing keyboard layouts."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👤 Account", callback_data="user:account"),
                InlineKeyboardButton("💎 Plans", callback_data="user:plans"),
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="user:help"),
                InlineKeyboardButton("🛟 Support", callback_data="user:support"),
            ],
        ]
    )
