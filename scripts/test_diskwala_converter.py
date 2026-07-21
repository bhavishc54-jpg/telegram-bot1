"""Send one DiskWala link to the configured converter bot and print its reply."""

from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

DEFAULT_TEST_LINK = "https://diskwala.com/test"
DEFAULT_TIMEOUT_SECONDS = 60


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the DiskWala converter bot via Telethon.")
    parser.add_argument("--link", default=DEFAULT_TEST_LINK, help="DiskWala link to send.")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Seconds to wait for the converter reply.",
    )
    args = parser.parse_args()
    asyncio.run(_test_converter(args.link.strip(), args.timeout))


async def _test_converter(link: str, timeout_seconds: int) -> None:
    if not link:
        raise SystemExit("A test link is required.")
    if timeout_seconds <= 0:
        raise SystemExit("Timeout must be greater than zero.")

    load_dotenv(".env", override=False)
    api_id = _required_int("TELEGRAM_API_ID")
    api_hash = _required("TELEGRAM_API_HASH")
    bot_username = _required("DISKWALA_CONVERTER_BOT").lstrip("@")
    session_path = _session_path()

    client = TelegramClient(str(session_path), api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise SystemExit(
                "Telethon session is not logged in. Run scripts/telethon_login.py first."
            )

        entity = await client.get_entity(bot_username)
        async with client.conversation(entity, timeout=timeout_seconds) as conversation:
            await conversation.send_message(link)
            response = await conversation.get_response()
            print(response.raw_text or "", flush=True)
    except TimeoutError as exc:
        raise SystemExit("Timed out waiting for converter reply.") from exc
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
    return Path("data") / "telethon_sessions" / safe_name


if __name__ == "__main__":
    main()
