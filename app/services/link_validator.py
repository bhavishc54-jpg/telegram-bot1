"""Strict, offline validation for public DiskWala URLs.

This module deliberately performs no HTTP request and contains no bypass or
download behavior. A permitted downloader can later implement ``Downloader``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
ALLOWED_HOSTS = frozenset({"diskwala.com", "www.diskwala.com"})
ALLOWED_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    code: str
    message: str
    normalized_url: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadResult:
    available: bool
    message: str


class Downloader(Protocol):
    """Extension point for a future official or legally permitted provider."""

    async def get_download(self, normalized_url: str) -> DownloadResult: ...


class ValidationOnlyDownloader:
    async def get_download(self, normalized_url: str) -> DownloadResult:
        return DownloadResult(
            available=False,
            message=(
                "Downloading is not connected yet. It will only be enabled when an official API "
                "or legally permitted public direct-download method is confirmed."
            ),
        )


def validate_diskwala_url(raw_url: str) -> ValidationResult:
    candidate = raw_url.strip()
    if not candidate or len(candidate) > MAX_URL_LENGTH:
        return ValidationResult(False, "invalid_length", "Send one complete HTTP or HTTPS URL.")
    if any(ord(character) < 32 for character in candidate):
        return ValidationResult(False, "control_characters", "The URL contains unsafe characters.")

    try:
        parsed = urlsplit(candidate)
        hostname = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
    except (UnicodeError, ValueError):
        return ValidationResult(False, "malformed_url", "That URL is malformed.")

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return ValidationResult(
            False, "unsupported_scheme", "Only HTTP and HTTPS links are supported."
        )
    if not parsed.netloc or not hostname:
        return ValidationResult(
            False, "incomplete_url", "Send a complete URL including http:// or https://."
        )
    if parsed.username is not None or parsed.password is not None:
        return ValidationResult(
            False, "embedded_credentials", "URLs containing credentials are not allowed."
        )
    if hostname not in ALLOWED_HOSTS:
        return ValidationResult(
            False, "unsupported_domain", "Only public diskwala.com links are supported."
        )
    if port is not None and port not in {80, 443}:
        return ValidationResult(False, "unsupported_port", "Non-standard ports are not supported.")
    if parsed.fragment:
        # Fragments never reach a server; removing them avoids storing misleading variants.
        parsed = parsed._replace(fragment="")

    normalized = urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )
    return ValidationResult(True, "valid", "This is a supported DiskWala URL.", normalized)
