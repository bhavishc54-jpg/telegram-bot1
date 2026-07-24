"""Text, URL extraction, cleanup, and Telegram-safe message splitting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from telegram._utils.entities import parse_message_entity

MAX_TELEGRAM_TEXT_LENGTH = 4096
URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,!?;:)]}>'\""


class TextEntity(Protocol):
    type: str
    url: str | None
    offset: int
    length: int


@dataclass(frozen=True, slots=True)
class ExtractedLink:
    url: str
    is_diskwala: bool
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True, slots=True)
class ProcessedPost:
    cleaned_text: str
    original_diskwala_links: tuple[str, ...]
    final_text: str
    skipped: bool = False


def normalize_url(raw_url: str) -> str | None:
    candidate = raw_url.strip().strip(TRAILING_PUNCTUATION)
    if not candidate or any(ord(character) < 32 for character in candidate):
        return None
    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
    except (UnicodeError, ValueError):
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not host or parsed.username:
        return None
    netloc = host
    if port is not None:
        netloc = f"{host}:{port}"
    if parsed.fragment:
        parsed = parsed._replace(fragment="")
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def is_allowed_diskwala_url(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    normalized = normalize_url(url)
    if not normalized:
        return False
    parsed = urlsplit(normalized)
    return (parsed.hostname or "").lower().rstrip(".") in allowed_hosts


def extract_links(
    text: str,
    entities: list[TextEntity] | tuple[TextEntity, ...] | None,
    allowed_hosts: tuple[str, ...],
) -> list[ExtractedLink]:
    links: list[ExtractedLink] = []
    for match in URL_RE.finditer(text):
        normalized = normalize_url(match.group(0))
        if normalized:
            links.append(
                ExtractedLink(
                    normalized,
                    is_allowed_diskwala_url(normalized, allowed_hosts),
                    match.start(),
                    match.end(),
                )
            )

    for entity in entities or ():
        if entity.type == "url":
            normalized = normalize_url(_entity_text(text, entity))
        elif entity.type == "text_link" and entity.url:
            normalized = normalize_url(entity.url)
        else:
            normalized = None
        if normalized:
            links.append(
                ExtractedLink(normalized, is_allowed_diskwala_url(normalized, allowed_hosts))
            )
    return links


def _entity_text(text: str, entity: TextEntity) -> str:
    """Extract Telegram entity text using UTF-16 offsets."""

    try:
        return parse_message_entity(text, entity)  # type: ignore[arg-type]
    except Exception:
        encoded = text.encode("utf-16-le")
        start = max(entity.offset, 0) * 2
        end = max(entity.offset + entity.length, 0) * 2
        return encoded[start:end].decode("utf-16-le", errors="ignore")


def ordered_unique_diskwala_links(links: list[ExtractedLink]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for link in links:
        if link.is_diskwala and link.url not in seen:
            seen.add(link.url)
            ordered.append(link.url)
    return tuple(ordered)


def clean_visible_text(text: str) -> str:
    without_urls = URL_RE.sub("", text)
    cleaned_lines: list[str] = []
    blank_count = 0
    for raw_line in without_urls.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            blank_count += 1
            if blank_count <= 1 and cleaned_lines:
                cleaned_lines.append("")
            continue
        blank_count = 0
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def build_final_message(
    cleaned_text: str,
    converted_links: list[str] | tuple[str, ...],
    broadcast_header: str = "",
) -> str:
    messages = build_final_messages(cleaned_text, converted_links, broadcast_header)
    return messages[0] if messages else ""


def build_final_messages(
    cleaned_text: str,
    converted_links: list[str] | tuple[str, ...],
    broadcast_header: str = "",
    max_length: int = MAX_TELEGRAM_TEXT_LENGTH,
) -> list[str]:
    del cleaned_text

    footer = (
        "viral videos milte rahenge \u2705 Stay Joined For Lifetime Free Updates \u274C "
        "Leave / Mute Mat Karna \U0001F440 More Exclusive Content Coming Daily\n\n"
        "Join backup channel link please \U0001F64F\U0001F3FB \U0001F447\U0001F3FB\U0001F447\U0001F3FB\U0001F447\U0001F3FB\n"
        "https://t.me/+9XcM-efDtMRiMDU1"
    )

    links = list(converted_links)

    if not links:
        return []

    if len(links) == 1:
        section = "\n".join(
            [
                "\U0001F4E5 Download Link",
                "",
                _escape_html_text(links[0]),
                "",
                footer,
            ]
        )
        return [_join_header_and_section(broadcast_header, section)]

    all_links_section = "\n".join(
        [
            "\U0001F4E5 Download Links",
            "",
            "   ".join(
                f"{index}. {_escape_html_text(link)}"
                for index, link in enumerate(links, start=1)
            ),
            footer,
        ]
    )

    all_links_message = _join_header_and_section(broadcast_header, all_links_section)

    if len(all_links_message) <= max_length:
        return [all_links_message]

    chunks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []

    for index, link in enumerate(links, start=1):
        candidate = [*current, (index, link)]
        candidate_message = _numbered_message(
            broadcast_header,
            "\U0001F4E5 Download Links",
            candidate,
        )

        if current and len(candidate_message) > max_length:
            chunks.append(current)
            current = [(index, link)]
        else:
            current = candidate

    if current:
        chunks.append(current)

    total_parts = len(chunks)
    messages: list[str] = []

    for part_number, chunk in enumerate(chunks, start=1):
        heading = f"\U0001F4E5 Download Links {part_number}/{total_parts}"
        message = _numbered_message(broadcast_header, heading, chunk)

        if part_number == total_parts:
            message = f"{message}\n\n{footer}".strip()

        messages.append(message)

    return messages


def _numbered_message(broadcast_header: str, heading: str, links: list[tuple[int, str]]) -> str:
    lines = [heading, ""]
    for position, link in links:
        if position != links[0][0]:
            lines.append("")
        lines.append(f"{position}. {_escape_html_text(link)}")
    return _join_header_and_section(broadcast_header, "\n".join(lines))


def _join_header_and_section(broadcast_header: str, section: str) -> str:
    if broadcast_header.strip():
        return f"{broadcast_header.strip()}\n\n{section}".strip()
    return section.strip()


def _escape_html_text(value: str) -> str:
    return escape(value, quote=False)


def process_source_text(
    text: str,
    entities: list[TextEntity] | tuple[TextEntity, ...] | None,
    allowed_hosts: tuple[str, ...],
    converted_links: list[str] | tuple[str, ...] = (),
) -> ProcessedPost:
    links = extract_links(text, entities, allowed_hosts)
    diskwala_links = ordered_unique_diskwala_links(links)
    cleaned = clean_visible_text(text)
    final_text = build_final_message(cleaned, converted_links)
    return ProcessedPost(
        cleaned_text=cleaned,
        original_diskwala_links=diskwala_links,
        final_text=final_text,
        skipped=not cleaned and not diskwala_links,
    )


def split_telegram_text(text: str, max_length: int = MAX_TELEGRAM_TEXT_LENGTH) -> list[str]:
    text = text.strip()
    if len(text) <= max_length:
        return [text] if text else []

    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_length:
            parts.append(remaining)
            break
        split_at = remaining.rfind("\n\n", 0, max_length + 1)
        if split_at < max_length // 2:
            split_at = remaining.rfind("\n", 0, max_length + 1)
        if split_at < max_length // 2:
            split_at = remaining.rfind(" ", 0, max_length + 1)
        if split_at < 1:
            split_at = max_length
        part = remaining[:split_at].strip()
        if part:
            parts.append(part)
        remaining = remaining[split_at:].strip()
    return parts
