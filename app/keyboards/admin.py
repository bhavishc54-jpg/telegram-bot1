"""Owner/admin inline keyboards."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu_keyboard(owner: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📊 Stats", callback_data="admin:stats"),
            InlineKeyboardButton("👥 Users", callback_data="admin:users"),
        ]
    ]
    if owner:
        rows.extend(
            [
                [
                    InlineKeyboardButton("💎 Premium", callback_data="admin:premium"),
                    InlineKeyboardButton("🚫 Ban user", callback_data="admin:ban"),
                ],
                [
                    InlineKeyboardButton("📣 Broadcast", callback_data="admin:broadcast"),
                    InlineKeyboardButton("📢 Ads", callback_data="admin:ads"),
                ],
                [
                    InlineKeyboardButton("⚙️ Settings", callback_data="admin:settings"),
                    InlineKeyboardButton("🛠 Maintenance", callback_data="admin:maintenance"),
                ],
                [InlineKeyboardButton("📋 Logs", callback_data="admin:logs")],
            ]
        )
    rows.append([InlineKeyboardButton("✖ Close", callback_data="admin:cancel")])
    return InlineKeyboardMarkup(rows)


def back_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅ Back", callback_data="admin:back"),
                InlineKeyboardButton("✖ Cancel", callback_data="admin:cancel"),
            ]
        ]
    )
