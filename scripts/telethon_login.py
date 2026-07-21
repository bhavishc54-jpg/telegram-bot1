"""One-time Telethon login for the Telegram user account."""

from __future__ import annotations

import asyncio
import getpass
import re
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError


def main() -> None:
    asyncio.run(_login())


async def _login() -> None:
    load_dotenv(".env", override=False)
    api_id = _required_int("TELEGRAM_API_ID")
    api_hash = _required("TELEGRAM_API_HASH")
    phone = _required("TELEGRAM_PHONE")
    session_path = _session_path()

    client = TelegramClient(str(session_path), api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            code = getpass.getpass("Telegram login code: ").strip()
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                password = getpass.getpass("Telegram two-step-verification password: ")
                await client.sign_in(password=password)
        print("TELETHON LOGIN SUCCESSFUL", flush=True)
    finally:
        await client.disconnect()


def _required(name: str) -> str:
    import os

    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required in .env.")
    return value


def _required_int(name: str) -> int:
    value = _required(name)
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be numeric.") from exc


def _session_path() -> Path:
    raw_name = _required("TELETHON_SESSION_NAME")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_name).strip("._")
    if not safe_name:
        raise SystemExit("TELETHON_SESSION_NAME must contain a usable file name.")
    directory = Path("data") / "telethon_sessions"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / safe_name


if __name__ == "__main__":
    main()
