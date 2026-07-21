from telegram import MessageEntity

from app.services.post_processor import (
    build_final_message,
    build_final_messages,
    extract_links,
    ordered_unique_diskwala_links,
    process_source_text,
)

HEADER = (
    "📢 <b>BROADCAST</b>\n\n"
    "Instagram Me Reels Dalkar Paise Kamao ✅ Earn Weekly ₹10,000 💰\n"
    "DM: @RolexWorkZ_01"
)


def test_one_diskwala_link_with_text_extracts_source_but_final_removes_text() -> None:
    result = process_source_text(
        "Good Morning!\n\nhttps://diskwala.com/original\nhttps://t.me/remove",
        None,
        ("diskwala.com", "www.diskwala.com"),
        ("https://diskwala.com/affiliate",),
    )
    assert result.cleaned_text == "Good Morning!"
    assert result.original_diskwala_links == ("https://diskwala.com/original",)
    assert result.final_text == "📥 Download Link\n\nhttps://diskwala.com/affiliate"
    assert "Good Morning" not in result.final_text


def test_fixed_header_and_one_link_format() -> None:
    message = build_final_message(
        "Original title should disappear",
        ("https://www.diskwala.com/app/converted-link",),
        HEADER,
    )
    assert message == (
        f"{HEADER}\n\n📥 Download Link\n\nhttps://www.diskwala.com/app/converted-link"
    )
    assert "Original title" not in message
    assert "<b>BROADCAST</b>" in message


def test_one_diskwala_link_without_text() -> None:
    result = process_source_text(
        "https://diskwala.com/original",
        None,
        ("diskwala.com",),
        ("https://diskwala.com/affiliate",),
    )
    assert result.final_text == "📥 Download Link\n\nhttps://diskwala.com/affiliate"


def test_fixed_header_and_multiple_link_format() -> None:
    message = build_final_message(
        "Remove me",
        (
            "https://www.diskwala.com/app/converted-link-1",
            "https://www.diskwala.com/app/converted-link-2",
            "https://www.diskwala.com/app/converted-link-3",
        ),
        HEADER,
    )
    assert message == (
        f"{HEADER}\n\n"
        "📥 Download Links\n\n"
        "1. https://www.diskwala.com/app/converted-link-1\n\n"
        "2. https://www.diskwala.com/app/converted-link-2\n\n"
        "3. https://www.diskwala.com/app/converted-link-3"
    )
    assert "Remove me" not in message


def test_duplicate_uppercase_and_punctuation_urls() -> None:
    result = process_source_text(
        "Files: https://DISKWALA.com/ABC, https://diskwala.com/ABC.",
        None,
        ("diskwala.com",),
    )
    assert result.original_diskwala_links == ("https://diskwala.com/ABC",)
    assert result.cleaned_text == "Files:"


def test_url_entity_extracts_diskwala_link() -> None:
    text = "Visit https://diskwala.com/from-entity"
    links = extract_links(
        text,
        (MessageEntity(type=MessageEntity.URL, offset=6, length=38),),
        ("diskwala.com",),
    )
    assert ordered_unique_diskwala_links(links) == ("https://diskwala.com/from-entity",)


def test_text_link_entity_extracts_hidden_diskwala_url() -> None:
    links = extract_links(
        "Visit https://google.com and hidden links",
        (
            MessageEntity(type=MessageEntity.URL, offset=6, length=18),
            MessageEntity(
                type=MessageEntity.TEXT_LINK,
                offset=29,
                length=6,
                url="https://diskwala.com/from-entity",
            ),
        ),
        ("diskwala.com",),
    )
    assert [link.url for link in links if link.is_diskwala] == ["https://diskwala.com/from-entity"]


def test_no_entities_still_extracts_plain_text_url() -> None:
    result = process_source_text(
        "Final converter test\nhttps://diskwala.com/app/plain",
        None,
        ("diskwala.com", "www.diskwala.com"),
    )
    assert result.original_diskwala_links == ("https://diskwala.com/app/plain",)


def test_url_entity_uses_utf16_offsets_with_emoji_before_url() -> None:
    text = "🔥 Final https://diskwala.com/app/unicode"
    offset = _utf16_units("🔥 Final ")
    length = _utf16_units("https://diskwala.com/app/unicode")
    links = extract_links(
        text,
        (MessageEntity(type=MessageEntity.URL, offset=offset, length=length),),
        ("diskwala.com",),
    )
    assert ordered_unique_diskwala_links(links) == ("https://diskwala.com/app/unicode",)


def test_www_diskwala_link_is_supported() -> None:
    result = process_source_text(
        "Final converter test\nhttps://www.diskwala.com/app/abc",
        None,
        ("diskwala.com", "www.diskwala.com"),
    )
    assert result.original_diskwala_links == ("https://www.diskwala.com/app/abc",)


def test_text_only_and_media_caption_without_diskwala_has_no_final_broadcast() -> None:
    result = process_source_text(
        "Server maintenance today.\n\nWe will return at 9 PM.\nhttps://example.com",
        None,
        ("diskwala.com",),
    )
    assert result.original_diskwala_links == ()
    assert result.final_text == ""


def test_media_only_post_is_skipped() -> None:
    result = process_source_text("", None, ("diskwala.com",))
    assert result.skipped is True
    assert result.final_text == ""


def test_converter_promo_and_telegram_backup_links_are_not_in_final_message() -> None:
    message = build_final_message(
        "Promo 🔥 https://t.me/backup",
        ("https://www.diskwala.com/app/clean",),
        HEADER,
    )
    assert "Promo" not in message
    assert "t.me" not in message
    assert "https://www.diskwala.com/app/clean" in message


def test_dynamic_links_are_html_escaped() -> None:
    message = build_final_message("", ("https://diskwala.com/app/a?x=1&y=<bad>",), HEADER)
    assert "x=1&amp;y=&lt;bad&gt;" in message


def test_message_splitting_preserves_numbering_without_cutting_urls() -> None:
    links = tuple(f"https://www.diskwala.com/app/{index:02d}-{'x' * 20}" for index in range(1, 31))
    parts = build_final_messages("", links, HEADER, max_length=420)
    assert len(parts) > 1
    assert "📥 Download Links 1/" in parts[0]
    assert "1. https://www.diskwala.com/app/01-" in parts[0]
    assert any("30. https://www.diskwala.com/app/30-" in part for part in parts)
    assert all(len(part) <= 420 for part in parts)


def _utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2
