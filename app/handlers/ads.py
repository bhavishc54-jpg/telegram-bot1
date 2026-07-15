"""Owner commands for sponsored-message management."""

from __future__ import annotations

from datetime import UTC, datetime, time

from sqlalchemy import select
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.handlers.admin import _audit, _authorized
from app.models import SponsoredMessage
from app.services.ad_service import validate_ad_content


async def ads(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context, owner_only=True)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    _, session_factory = dependencies
    if context.args and context.args[0].lower() in {"activate", "deactivate"}:
        if len(context.args) != 2:
            await update.effective_message.reply_text("Usage: /ads activate|deactivate AD_ID")
            return
        try:
            ad_id = int(context.args[1])
        except ValueError:
            await update.effective_message.reply_text("AD_ID must be a whole number.")
            return
        async with session_factory() as session:
            ad = await session.get(SponsoredMessage, ad_id)
            if not ad:
                await update.effective_message.reply_text("Advertisement not found.")
                return
            ad.is_active = context.args[0].lower() == "activate"
            await _audit(
                session, update.effective_user.id, "ad_status", f"id={ad_id} active={ad.is_active}"
            )
            await session.commit()
        await update.effective_message.reply_text("Advertisement status updated.")
        return
    if context.args and context.args[0].lower() == "edit":
        if len(context.args) < 4:
            await update.effective_message.reply_text(
                "Usage: /ads edit AD_ID title|message|button_text|button_url|max_displays VALUE"
            )
            return
        try:
            ad_id = int(context.args[1])
        except ValueError:
            await update.effective_message.reply_text("AD_ID must be a whole number.")
            return
        field = context.args[2].lower()
        value = " ".join(context.args[3:]).strip()
        allowed_fields = {"title", "message", "button_text", "button_url", "max_displays"}
        if field not in allowed_fields:
            await update.effective_message.reply_text(
                "Editable fields: title, message, button_text, button_url, max_displays"
            )
            return
        async with session_factory() as session:
            ad = await session.get(SponsoredMessage, ad_id)
            if not ad:
                await update.effective_message.reply_text("Advertisement not found.")
                return
            try:
                if field == "title":
                    ad.title = value
                elif field == "message":
                    ad.message_text = value
                elif field == "button_text":
                    ad.button_text = None if value == "-" else value
                elif field == "button_url":
                    ad.button_url = None if value == "-" else value
                else:
                    ad.max_displays = int(value)
                    if not 0 <= ad.max_displays <= 10_000_000:
                        raise ValueError("Maximum displays must be between 0 and 10000000.")
                if bool(ad.button_text) != bool(ad.button_url):
                    raise ValueError(
                        "Button text and URL must either both be set or both be removed."
                    )
                validate_ad_content(ad.title, ad.message_text, ad.button_url)
                if ad.button_text and len(ad.button_text) > 64:
                    raise ValueError("Button text cannot exceed 64 characters.")
            except ValueError as exc:
                await session.rollback()
                await update.effective_message.reply_text(f"Cannot edit advertisement: {exc}")
                return
            await _audit(session, update.effective_user.id, "edit_ad", f"id={ad_id} field={field}")
            await session.commit()
        await update.effective_message.reply_text(f"Advertisement #{ad_id} updated.")
        return
    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(SponsoredMessage).order_by(SponsoredMessage.id.desc()).limit(30)
            )
        )
    text = "📢 Sponsored messages\n" + "\n".join(
        f"#{ad.id} | {'active' if ad.is_active else 'inactive'} | "
        f"{ad.display_count}/{ad.max_displays or '∞'} | {ad.title}"
        for ad in rows
    )
    text += (
        "\n\nAdd: /addad TITLE | MESSAGE | BUTTON TEXT | URL | START_DATE | END_DATE | MAX\n"
        "Dates use YYYY-MM-DD. Button fields may be '-'.\n"
        "Status: /ads activate|deactivate AD_ID\n"
        "Edit: /ads edit AD_ID FIELD VALUE\nDelete: /removead AD_ID"
    )
    await update.effective_message.reply_text(text[:4000])


async def add_ad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context, owner_only=True)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    raw = " ".join(context.args)
    fields = [field.strip() for field in raw.split("|")]
    if len(fields) != 7:
        await update.effective_message.reply_text(
            "Create an ad with:\n/addad TITLE | MESSAGE | BUTTON TEXT | URL | "
            "START_DATE | END_DATE | MAX\n"
            "Use '-' for both button fields when no button is needed. Always use /ads to review it."
        )
        return
    title, message, button_text, button_url, start_raw, end_raw, max_raw = fields
    button_text = None if button_text == "-" else button_text
    button_url = None if button_url == "-" else button_url
    try:
        validate_ad_content(title, message, button_url)
        if bool(button_text) != bool(button_url):
            raise ValueError("Button text and URL must either both be set or both use '-'.")
        if button_text and len(button_text) > 64:
            raise ValueError("Button text cannot exceed 64 characters.")
        starts_at = datetime.combine(datetime.strptime(start_raw, "%Y-%m-%d").date(), time.min, UTC)
        ends_at = datetime.combine(datetime.strptime(end_raw, "%Y-%m-%d").date(), time.max, UTC)
        max_displays = int(max_raw)
        if ends_at < starts_at or not 0 <= max_displays <= 10_000_000:
            raise ValueError("Date range or maximum displays is invalid.")
    except ValueError as exc:
        await update.effective_message.reply_text(f"Cannot create advertisement: {exc}")
        return
    _, session_factory = dependencies
    async with session_factory() as session:
        ad = SponsoredMessage(
            title=title,
            message_text=message,
            button_text=button_text,
            button_url=button_url,
            starts_at=starts_at,
            ends_at=ends_at,
            max_displays=max_displays,
            created_by=update.effective_user.id,
            is_active=True,
        )
        session.add(ad)
        await session.flush()
        await _audit(session, update.effective_user.id, "add_ad", f"id={ad.id}")
        await session.commit()
    await update.effective_message.reply_text(
        f"Advertisement #{ad.id} created and active. Use /ads to review it."
    )


async def remove_ad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dependencies = await _authorized(update, context, owner_only=True)
    if not dependencies or not update.effective_message or not update.effective_user:
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text("Usage: /removead AD_ID")
        return
    try:
        ad_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("AD_ID must be a whole number.")
        return
    _, session_factory = dependencies
    async with session_factory() as session:
        ad = await session.get(SponsoredMessage, ad_id)
        if not ad:
            await update.effective_message.reply_text("Advertisement not found.")
            return
        await session.delete(ad)
        await _audit(session, update.effective_user.id, "remove_ad", f"id={ad_id}")
        await session.commit()
    await update.effective_message.reply_text(f"Advertisement #{ad_id} deleted.")


def handlers() -> list[object]:
    return [
        CommandHandler("ads", ads),
        CommandHandler("addad", add_ad),
        CommandHandler("removead", remove_ad),
    ]
