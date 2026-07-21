"""Small helper for safe, human-readable terminal status lines."""

from __future__ import annotations


def terminal_log(*lines: object) -> None:
    """Print operational breadcrumbs without involving secret-bearing log formatters."""

    print("\n".join(str(line) for line in lines), flush=True)
