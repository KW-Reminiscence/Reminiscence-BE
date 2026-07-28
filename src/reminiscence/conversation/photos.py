"""Validated photo memories loaded from the local configuration JSON."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_METADATA_CHARS = 500
MAX_PEOPLE = 20
SUPPORTED_IMAGE_MEDIA_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)


class PhotoConfigurationError(ValueError):
    """Raised when a configured photo memory is malformed."""


@dataclass(frozen=True, slots=True)
class PhotoMemory:
    """One family-provided photo and its trusted reminiscence context."""

    photo_id: str
    image_base64: str
    image_media_type: str
    location: str
    people: tuple[str, ...]
    event: str
    description: str

    @property
    def data_url(self) -> str:
        """Return a browser- and Responses-API-compatible image data URL."""

        return f"data:{self.image_media_type};base64,{self.image_base64}"


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PhotoConfigurationError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > MAX_METADATA_CHARS:
        raise PhotoConfigurationError(
            f"{field_name} must not exceed {MAX_METADATA_CHARS} characters"
        )
    return normalized


def _people(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
    ):
        raise PhotoConfigurationError("people must be a non-empty array")
    if len(value) > MAX_PEOPLE:
        raise PhotoConfigurationError(f"people must not contain more than {MAX_PEOPLE} names")
    return tuple(
        _required_text(person, f"people[{index}]") for index, person in enumerate(value)
    )


def _validate_image(image_base64: str, image_media_type: str) -> None:
    maximum_encoded_length = ((MAX_PHOTO_BYTES + 2) // 3) * 4
    if len(image_base64) > maximum_encoded_length:
        raise PhotoConfigurationError(
            f"decoded image must not exceed {MAX_PHOTO_BYTES} bytes"
        )
    try:
        image = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PhotoConfigurationError("image_base64 must be valid base64") from exc
    if not image:
        raise PhotoConfigurationError("image_base64 must not decode to an empty image")
    if len(image) > MAX_PHOTO_BYTES:
        raise PhotoConfigurationError(
            f"decoded image must not exceed {MAX_PHOTO_BYTES} bytes"
        )

    signatures = {
        "image/jpeg": image.startswith(b"\xff\xd8\xff"),
        "image/png": image.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": (
            len(image) >= 12
            and image.startswith(b"RIFF")
            and image[8:12] == b"WEBP"
        ),
    }
    if not signatures[image_media_type]:
        raise PhotoConfigurationError(
            "image_base64 content does not match image_media_type"
        )


def parse_photo(value: Mapping[str, Any]) -> PhotoMemory:
    """Parse and validate one configured photo memory."""

    photo_id = _required_text(value.get("id"), "id")
    image_base64 = _required_text(value.get("image_base64"), "image_base64")
    image_media_type = _required_text(
        value.get("image_media_type"),
        "image_media_type",
    ).lower()
    if image_media_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_MEDIA_TYPES))
        raise PhotoConfigurationError(
            f"image_media_type must be one of: {supported}"
        )
    _validate_image(image_base64, image_media_type)
    return PhotoMemory(
        photo_id=photo_id,
        image_base64=image_base64,
        image_media_type=image_media_type,
        location=_required_text(value.get("location"), "location"),
        people=_people(value.get("people")),
        event=_required_text(value.get("event"), "event"),
        description=_required_text(value.get("description"), "description"),
    )


def parse_photos(value: object) -> tuple[PhotoMemory, ...]:
    """Parse a photo array and reject malformed or duplicate entries."""

    if not isinstance(value, list):
        raise PhotoConfigurationError("photos must be an array")
    photos: list[PhotoMemory] = []
    seen_ids: set[str] = set()
    for index, raw_photo in enumerate(value):
        if not isinstance(raw_photo, dict):
            raise PhotoConfigurationError(f"photos[{index}] must be an object")
        try:
            photo = parse_photo(raw_photo)
        except PhotoConfigurationError as exc:
            raise PhotoConfigurationError(f"invalid photos[{index}]: {exc}") from exc
        if photo.photo_id in seen_ids:
            raise PhotoConfigurationError(f"duplicate photo id: {photo.photo_id}")
        seen_ids.add(photo.photo_id)
        photos.append(photo)
    return tuple(photos)
