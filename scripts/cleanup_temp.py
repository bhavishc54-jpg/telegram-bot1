"""Remove old files only from the project's dedicated data/tmp folder."""

from __future__ import annotations

import time
from pathlib import Path

TEMP_DIRECTORY = Path("data/tmp").resolve()
MAX_AGE_SECONDS = 24 * 60 * 60


def cleanup(directory: Path = TEMP_DIRECTORY, max_age_seconds: int = MAX_AGE_SECONDS) -> int:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max_age_seconds
    removed = 0
    for path in directory.iterdir():
        resolved = path.resolve()
        if resolved.parent != directory or not resolved.is_file() or resolved.name == ".gitkeep":
            continue
        if resolved.stat().st_mtime < cutoff:
            resolved.unlink()
            removed += 1
    return removed


if __name__ == "__main__":
    print(f"Removed {cleanup()} old temporary file(s).")
