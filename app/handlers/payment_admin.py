"""Owner/admin product, payment, credit, and user-payment controls."""

from __future__ import annotations

from sqlalchemy import func, select
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.handlers.admin import _audit, _authorized
from app.models import Payment, PaymentStatus, Product, User


async def payments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context)
    if not dependencies or not update.effective_message:
        return
    _, session_factory = dependencies
    async with session_factory() as session:
        counts = {
            status.value: await session.scalar(
                select(func.count()).select_from(Payment).where(Payment.status == status)
            )
            or 0
            for status in PaymentStatus
        }
    await update.effective_message.reply_text(
        "Payment statistics\n" + "\n".join(f"{key}: {value}" for key, value in counts.items())
    )


async def products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    owner_only = bool(context.args)
    dependencies = await _authorized(update, context, owner_only=owner_only)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    _, session_factory = dependencies
    if context.args:
        action = context.args[0].lower()
        if action in {"enable", "disable"} and len(context.args) == 2:
            async with session_factory() as session:
                product = await session.scalar(
                    select(Product).where(Product.product_code == context.args[1])
                )
                if product is None:
                    await update.effective_message.reply_text("Product not found.")
                    return
                if (
                    action == "enable"
                    and product.provider.value == "paddle"
                    and (not product.paddle_product_id or not product.paddle_price_id)
                ):
                    await update.effective_message.reply_text(
                        "Configure Paddle product and price IDs before enabling this product."
                    )
                    return
                product.is_active = action == "enable"
                await _audit(
                    session,
                    update.effective_user.id,
                    "product_status",
                    f"{product.product_code}={product.is_active}",
                )
                await session.commit()
            await update.effective_message.reply_text("Product status updated.")
            return
        if action == "configure" and len(context.args) == 4:
            product_code, paddle_product_id, paddle_price_id = context.args[1:]
            if not paddle_product_id.startswith("pro_") or not paddle_price_id.startswith("pri_"):
                await update.effective_message.reply_text(
                    "Paddle IDs must start with pro_ and pri_."
                )
                return
            async with session_factory() as session:
                product = await session.scalar(
                    select(Product).where(Product.product_code == product_code)
                )
                if product is None or product.provider.value != "paddle":
                    await update.effective_message.reply_text("Paddle product not found.")
                    return
                product.paddle_product_id = paddle_product_id[:64]
                product.paddle_price_id = paddle_price_id[:64]
                await _audit(session, update.effective_user.id, "configure_product", product_code)
                await session.commit()
            await update.effective_message.reply_text(
                "Paddle IDs saved. Use /products enable PRODUCT_CODE when ready."
            )
            return
        await update.effective_message.reply_text(
            "Usage:\n/products\n/products enable|disable CODE\n"
            "/products configure CODE pro_ID pri_ID"
        )
        return
    async with session_factory() as session:
        rows = list(await session.scalars(select(Product).order_by(Product.id)))
    await update.effective_message.reply_text(
        "Products\n"
        + "\n".join(
            f"{row.product_code} | {row.provider.value} | "
            f"{'active' if row.is_active else 'inactive'} | credits={row.credits} | "
            f"premium_days={row.premium_duration_days}"
            for row in rows
        )
    )


async def give_credits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _change_credits(update, context, remove=False)


async def remove_credits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _change_credits(update, context, remove=True)


async def _change_credits(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, remove: bool
) -> None:
    dependencies = await _authorized(update, context, owner_only=True)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    if len(context.args) != 2:
        command = "removecredits" if remove else "givecredits"
        await update.effective_message.reply_text(f"Usage: /{command} USER_ID AMOUNT")
        return
    try:
        user_id, amount = int(context.args[0]), int(context.args[1])
        if not 1 <= amount <= 1_000_000:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("USER_ID and a positive AMOUNT are required.")
        return
    _, session_factory = dependencies
    async with session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            await update.effective_message.reply_text("User not found.")
            return
        if remove and user.credits < amount:
            await update.effective_message.reply_text("The user does not have that many credits.")
            return
        user.credits += -amount if remove else amount
        await _audit(
            session,
            update.effective_user.id,
            "remove_credits" if remove else "give_credits",
            f"user={user_id} amount={amount}",
        )
        await session.commit()
    await update.effective_message.reply_text(f"New credit balance: {user.credits}")


async def find_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context)
    if not dependencies or not update.effective_message or len(context.args) != 1:
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("User ID must be numeric.")
        return
    _, session_factory = dependencies
    async with session_factory() as session:
        user = await session.get(User, user_id)
    if user is None:
        await update.effective_message.reply_text("User not found.")
        return
    await update.effective_message.reply_text(
        f"ID: {user.telegram_id}\nUsername: @{user.username or '-'}\n"
        f"Credits: {user.credits}\nPlan: {user.plan.value}\nRole: {user.role.value}"
    )


async def user_payments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context)
    if not dependencies or not update.effective_message or len(context.args) != 1:
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("User ID must be numeric.")
        return
    _, session_factory = dependencies
    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(Payment)
                .where(Payment.user_id == user_id)
                .order_by(Payment.created_at.desc())
                .limit(20)
            )
        )
    await update.effective_message.reply_text(
        "Payment history\n"
        + (
            "\n".join(
                f"{p.internal_order_id} | {p.provider.value} | {p.status.value}" for p in rows
            )
            or "None"
        )
    )


def handlers() -> list[object]:
    return [
        CommandHandler("payments", payments),
        CommandHandler("products", products),
        CommandHandler("givecredits", give_credits),
        CommandHandler("removecredits", remove_credits),
        CommandHandler("finduser", find_user),
        CommandHandler("userpayments", user_payments),
    ]
