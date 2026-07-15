"""Safe logging configuration."""

import logging
from pathlib import Path


def configure_logging(level: str) -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("logs/bot.log", encoding="utf-8")],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
