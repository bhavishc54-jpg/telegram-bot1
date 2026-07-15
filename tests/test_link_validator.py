import pytest

from app.services.link_validator import validate_diskwala_url


@pytest.mark.parametrize(
    "url",
    [
        "https://diskwala.com/file/abc123",
        "http://diskwala.com/public?id=12",
        "https://www.diskwala.com/folder/example",
    ],
)
def test_valid_diskwala_urls(url: str) -> None:
    result = validate_diskwala_url(url)
    assert result.valid is True
    assert result.normalized_url


@pytest.mark.parametrize(
    "url",
    ["", "diskwala.com/file/1", "ftp://diskwala.com/file", "https://", "not a URL"],
)
def test_invalid_urls(url: str) -> None:
    assert validate_diskwala_url(url).valid is False


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/file",
        "https://diskwala.com.evil.example/file",
        "https://evil.example/?next=https://diskwala.com/file",
        "https://user:password@diskwala.com/file",
        "https://diskwala.com:444/file",
    ],
)
def test_unsupported_or_dangerous_urls(url: str) -> None:
    assert validate_diskwala_url(url).valid is False
