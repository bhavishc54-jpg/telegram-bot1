"""Purchase-option keyboards shared by /buy and payment-required link replies."""

from collections.abc import Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Settings
from app.models import PaymentProvider, Product


def purchase_options_keyboard(
    products: Sequence[Product], settings: Settings
) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        if not product.is_active:
            continue
        if product.provider is PaymentProvider.TELEGRAM_STARS:
            if not settings.enable_telegram_stars or not product.stars_price:
                continue
            label = f"⭐ {product.name} — {product.stars_price} Stars"
            callback = f"buy:stars:{product.product_code}"
        else:
            if (
                not settings.enable_paddle
                or not product.paddle_product_id
                or not product.paddle_price_id
            ):
                continue
            label = f"💳 {product.name}"
            callback = f"buy:paddle:{product.product_code}"
        if len(callback.encode()) <= 64:
            rows.append([InlineKeyboardButton(label, callback_data=callback)])
    return InlineKeyboardMarkup(rows) if rows else None
