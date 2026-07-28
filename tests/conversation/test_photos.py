"""Photo memory configuration validation tests."""

from __future__ import annotations

import base64

import pytest

from reminiscence.conversation.photos import (
    MAX_PHOTO_BYTES,
    PhotoConfigurationError,
    parse_photo,
    parse_photos,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"photo"


def valid_photo() -> dict[str, object]:
    return {
        "id": "family-1",
        "image_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
        "image_media_type": "image/png",
        "location": "제주도 성산일출봉",
        "people": ["딸 영희", "손자 민준"],
        "event": "2022년 봄 가족여행",
        "description": "성산일출봉에 오르기 전에 함께 찍은 사진",
    }


def test_parse_photo_returns_data_url_and_context() -> None:
    photo = parse_photo(valid_photo())

    assert photo.photo_id == "family-1"
    assert photo.people == ("딸 영희", "손자 민준")
    assert photo.data_url.startswith("data:image/png;base64,")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", " ", "id must be a non-empty string"),
        ("location", None, "location must be a non-empty string"),
        ("people", [], "people must be a non-empty array"),
        ("event", "", "event must be a non-empty string"),
        ("description", 1, "description must be a non-empty string"),
    ],
)
def test_parse_photo_rejects_missing_context(
    field: str,
    value: object,
    message: str,
) -> None:
    configured = valid_photo()
    configured[field] = value

    with pytest.raises(PhotoConfigurationError, match=message):
        parse_photo(configured)


def test_parse_photo_rejects_invalid_base64() -> None:
    configured = valid_photo()
    configured["image_base64"] = "not base64!"

    with pytest.raises(PhotoConfigurationError, match="must be valid base64"):
        parse_photo(configured)


def test_parse_photo_rejects_media_type_mismatch() -> None:
    configured = valid_photo()
    configured["image_media_type"] = "image/jpeg"

    with pytest.raises(PhotoConfigurationError, match="does not match"):
        parse_photo(configured)


def test_parse_photo_rejects_unsupported_media_type() -> None:
    configured = valid_photo()
    configured["image_media_type"] = "image/svg+xml"

    with pytest.raises(PhotoConfigurationError, match="must be one of"):
        parse_photo(configured)


def test_parse_photo_rejects_decoded_image_over_limit() -> None:
    configured = valid_photo()
    configured["image_base64"] = base64.b64encode(
        b"\x89PNG\r\n\x1a\n" + b"x" * MAX_PHOTO_BYTES
    ).decode("ascii")

    with pytest.raises(PhotoConfigurationError, match="must not exceed"):
        parse_photo(configured)


def test_parse_photos_rejects_duplicate_ids() -> None:
    duplicate = valid_photo()

    with pytest.raises(PhotoConfigurationError, match="duplicate photo id"):
        parse_photos([valid_photo(), duplicate])


def test_parse_photos_rejects_non_object_entry() -> None:
    with pytest.raises(PhotoConfigurationError, match=r"photos\[0\] must be an object"):
        parse_photos(["family-1"])
