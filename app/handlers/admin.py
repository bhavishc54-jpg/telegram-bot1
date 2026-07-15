"""Protected owner and limited-admin commands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from app.config import Settings
from app.keyboards.admin import admin_menu_keyboard, back_cancel_keyboard
from app.models import AuditLog, BotSetting, LinkRequest, SubscriptionPlan, User, UserRole, utcnow
from app.services.auth_service import is_admin, is_owner
from app.services.subscription_service import grant_premium, remove_premium

EDITABLE_SETTINGS = {
    "welcome_message",
    "help_message",
    "support_username",
    "free_daily_limit",
    "premium_daily_limit",
    "sponsored_messages_enabled",
    "maintenance_message",
    "premium_plan_name",
    "premium_price_text",
}


def _dependencies(
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[Settings, async_sessionmaker[AsyncSession]]:
    return context.application.bot_data["settings"], context.application.bot_data["session_factory"]


async def _authorized(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, owner_only: bool = False
) -> tuple[Settings, async_sessionmaker[AsyncSession]] | None:
    settings, session_factory = _dependencies(context)
    user_id = update.effective_user.id if update.effective_user else None
    allowed = is_owner(user_id, settings.owner_user_id)
    if not owner_only and not allowed:
        async with session_factory() as session:
            allowed = await is_admin(session, user_id, settings.owner_user_id)
    if not allowed:
        if update.callback_query:
            await update.callback_query.answer("You are not authorized.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("You are not authorized to use this command.")
        return None
    return settings, session_factory


async def _audit(session: AsyncSession, actor_id: int, action: str, details: str = "") -> None:
    session.add(AuditLog(actor_id=actor_id, action=action, details=details[:2000]))


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    settings, _ = dependencies
    await update.effective_message.reply_text(
        "Admin panel",
        reply_markup=admin_menu_keyboard(
            is_owner(update.effective_user.id, settings.owner_user_id)
        ),
    )


async def _stats_text(session: AsyncSession) -> str:
    today = datetime.now(UTC).date()
    active_since = utcnow() - timedelta(days=7)
    total = await session.scalar(select(func.count()).select_from(User)) or 0
    active = (
        await session.scalar(
            select(func.count()).select_from(User).where(User.last_active_at >= active_since)
        )
        or 0
    )
    new_today = (
        await session.scalar(
            select(func.count()).select_from(User).where(func.date(User.joined_at) == str(today))
        )
        or 0
    )
    requests = await session.scalar(select(func.count()).select_from(LinkRequest)) or 0
    premium = (
        await session.scalar(
            select(func.count()).select_from(User).where(User.plan == SubscriptionPlan.PREMIUM)
        )
        or 0
    )
    banned = (
        await session.scalar(select(func.count()).select_from(User).where(User.is_banned.is_(True)))
        or 0
    )
    return (
        "📊 Bot statistics\n"
        f"Total users: {total}\nActive (7 days): {active}\nNew today: {new_today}\n"
        f"Link requests: {requests}\nFree users: {total - premium}\n"
        f"Premium users: {premium}\nBanned users: {banned}"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context)
    if not dependencies or not update.effective_message:
        return
    _, session_factory = dependencies
    async with session_factory() as session:
        text = await _stats_text(session)
    await update.effective_message.reply_text(text)


async def users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context)
    if not dependencies or not update.effective_message:
        return
    _, session_factory = dependencies
    async with session_factory() as session:
        rows = list(await session.scalars(select(User).order_by(User.joined_at.desc()).limit(20)))
    lines = ["👥 Newest users (maximum 20)"]
    lines.extend(
        f"{user.telegram_id} | @{user.username or '-'} | {user.plan.value} | {user.role.value}"
        for user in rows
    )
    await update.effective_message.reply_text("\n".join(lines))


async def add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context, owner_only=True)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Usage: /addpremium USER_ID DAYS")
        return
    try:
        target_id, days = int(context.args[0]), int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text("USER_ID and DAYS must be whole numbers.")
        return
    _, session_factory = dependencies
    async with session_factory() as session:
        target = await session.get(User, target_id)
        if not target:
            await update.effective_message.reply_text(
                "User not found. They must start the bot first."
            )
            return
        try:
            await grant_premium(session, target, days)
        except ValueError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await _audit(
            session, update.effective_user.id, "add_premium", f"user={target_id} days={days}"
        )
        await session.commit()
    await update.effective_message.reply_text(f"Premium granted to {target_id} for {days} days.")


async def remove_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _target_user_mutation(update, context, "remove_premium")


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _target_user_mutation(update, context, "ban")


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _target_user_mutation(update, context, "unban")


async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _target_user_mutation(update, context, "add_admin")


async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _target_user_mutation(update, context, "remove_admin")


async def _target_user_mutation(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str
) -> None:
    dependencies = await _authorized(update, context, owner_only=True)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text(f"Usage: /{action.replace('_', '')} USER_ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("USER_ID must be a whole number.")
        return
    settings, session_factory = dependencies
    if target_id == settings.owner_user_id and action in {"ban", "remove_admin"}:
        await update.effective_message.reply_text(
            "The owner account cannot be changed by this action."
        )
        return
    async with session_factory() as session:
        target = await session.get(User, target_id)
        if not target:
            await update.effective_message.reply_text(
                "User not found. They must start the bot first."
            )
            return
        if action == "remove_premium":
            await remove_premium(session, target)
        elif action == "ban":
            target.is_banned = True
        elif action == "unban":
            target.is_banned = False
        elif action == "add_admin":
            target.role = UserRole.ADMIN
        elif action == "remove_admin":
            target.role = UserRole.USER
        await _audit(session, update.effective_user.id, action, f"user={target_id}")
        await session.commit()
    await update.effective_message.reply_text(f"Action {action} completed for {target_id}.")


async def set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context, owner_only=True)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    if len(context.args) != 2 or context.args[0].lower() not in {"free", "premium"}:
        await update.effective_message.reply_text("Usage: /setlimit free|premium NUMBER")
        return
    try:
        value = int(context.args[1])
        if not 1 <= value <= 10000:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("Limit must be between 1 and 10000.")
        return
    key = f"{context.args[0].lower()}_daily_limit"
    _, session_factory = dependencies
    async with session_factory() as session:
        setting = await session.get(BotSetting, key)
        if setting:
            setting.value = str(value)
        else:
            session.add(BotSetting(key=key, value=str(value)))
        await _audit(session, update.effective_user.id, "set_limit", f"{key}={value}")
        await session.commit()
    await update.effective_message.reply_text(f"{key} is now {value}.")


async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context, owner_only=True)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    if len(context.args) != 1 or context.args[0].lower() not in {"on", "off"}:
        await update.effective_message.reply_text("Usage: /maintenance on|off")
        return
    value = "true" if context.args[0].lower() == "on" else "false"
    _, session_factory = dependencies
    async with session_factory() as session:
        setting = await session.get(BotSetting, "maintenance_enabled")
        if setting:
            setting.value = value
        await _audit(session, update.effective_user.id, "maintenance", value)
        await session.commit()
    await update.effective_message.reply_text(f"Maintenance mode is {context.args[0].lower()}.")


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context, owner_only=True)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    _, session_factory = dependencies
    async with session_factory() as session:
        if not context.args:
            rows = list(
                await session.scalars(
                    select(BotSetting)
                    .where(BotSetting.key.in_(EDITABLE_SETTINGS))
                    .order_by(BotSetting.key)
                )
            )
            text = "⚙️ Editable settings\n" + "\n".join(f"{row.key} = {row.value}" for row in rows)
            await update.effective_message.reply_text(text[:4000])
            return
        if len(context.args) < 2 or context.args[0] not in EDITABLE_SETTINGS:
            await update.effective_message.reply_text(
                "Usage: /settings KEY VALUE\nUse /settings to list allowed keys."
            )
            return
        key, value = context.args[0], " ".join(context.args[1:]).strip()
        if not value or len(value) > 3500:
            await update.effective_message.reply_text("Value must contain 1 to 3500 characters.")
            return
        if key in {"free_daily_limit", "premium_daily_limit"}:
            try:
                if not 1 <= int(value) <= 10000:
                    raise ValueError
            except ValueError:
                await update.effective_message.reply_text(
                    "Daily limits must be between 1 and 10000."
                )
                return
        if key == "sponsored_messages_enabled" and value.lower() not in {"true", "false"}:
            await update.effective_message.reply_text("Use true or false for this setting.")
            return
        setting = await session.get(BotSetting, key)
        if setting:
            setting.value = value
        else:
            session.add(BotSetting(key=key, value=value))
        await _audit(session, update.effective_user.id, "update_setting", key)
        await session.commit()
    await update.effective_message.reply_text(f"Setting {key} updated.")


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    owner_actions = {"premium", "ban", "broadcast", "ads", "settings", "maintenance", "logs"}
    action = (query.data or "").removeprefix("admin:")
    dependencies = await _authorized(update, context, owner_only=action in owner_actions)
    if not dependencies:
        return
    await query.answer()
    settings, session_factory = dependencies
    if action == "cancel":
        await query.edit_message_text("Admin action cancelled.")
    elif action == "back":
        await query.edit_message_text(
            "Admin panel",
            reply_markup=admin_menu_keyboard(
                is_owner(update.effective_user.id, settings.owner_user_id)
            ),
        )
    elif action == "stats":
        async with session_factory() as session:
            text = await _stats_text(session)
        await query.edit_message_text(text, reply_markup=back_cancel_keyboard())
    elif action == "users":
        await query.edit_message_text(
            "Use /users to view the latest users.", reply_markup=back_cancel_keyboard()
        )
    elif action == "premium":
        await query.edit_message_text(
            "Give premium: /addpremium USER_ID DAYS\nRemove: /removepremium USER_ID",
            reply_markup=back_cancel_keyboard(),
        )
    elif action == "ban":
        await query.edit_message_text(
            "Ban: /ban USER_ID\nUnban: /unban USER_ID", reply_markup=back_cancel_keyboard()
        )
    elif action == "maintenance":
        await query.edit_message_text(
            "Use /maintenance on or /maintenance off.", reply_markup=back_cancel_keyboard()
        )
    elif action == "settings":
        await query.edit_message_text(
            "Use /settings to list values, then /settings KEY VALUE to edit one.",
            reply_markup=back_cancel_keyboard(),
        )
    elif action in {"broadcast", "ads"}:
        await query.edit_message_text(
            f"Use /{action} to open this workflow.", reply_markup=back_cancel_keyboard()
        )
    elif action == "payments":
        await query.edit_message_text(
            "Use /payments for payment statistics or /userpayments USER_ID for history.",
            reply_markup=back_cancel_keyboard(),
        )
    elif action == "products":
        await query.edit_message_text(
            "Use /products to view products. Owner configuration commands are shown there.",
            reply_markup=back_cancel_keyboard(),
        )
    elif action == "logs":
        async with session_factory() as session:
            logs = list(
                await session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(15))
            )
        text = "📋 Recent audit log\n" + "\n".join(
            f"{item.created_at:%m-%d %H:%M} | {item.actor_id} | {item.action}" for item in logs
        )
        await query.edit_message_text(
            text or "No audit entries yet.", reply_markup=back_cancel_keyboard()
        )


def handlers() -> list[object]:
    return [
        CommandHandler("admin", admin),
        CommandHandler("stats", stats),
        CommandHandler("users", users),
        CommandHandler("addpremium", add_premium),
        CommandHandler("removepremium", remove_premium_command),
        CommandHandler("ban", ban),
        CommandHandler("unban", unban),
        CommandHandler("setlimit", set_limit),
        CommandHandler("addadmin", add_admin),
        CommandHandler("removeadmin", remove_admin),
        CommandHandler("maintenance", maintenance),
        CommandHandler("settings", settings_command),
        CallbackQueryHandler(admin_callback, pattern=r"^admin:"),
    ]
