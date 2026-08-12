"""JSON-only application runtime settings with environment bootstrap paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from reminiscence.storage import open_versioned_store

DEFAULT_PUBLIC_ORIGIN = "https://reminiscence.leehyowon14.dev"
DEFAULT_CODEX_LB_BASE_URL = "http://127.0.0.1:2455/v1"


class RuntimeConfigurationError(ValueError):
    """Raised when configuration.json runtime settings are malformed."""


@dataclass(frozen=True, slots=True)
class CodexLbSettings:
    base_url: str = DEFAULT_CODEX_LB_BASE_URL
    connect_timeout_seconds: float = 10.0
    transcription_read_timeout_seconds: float = 150.0
    response_read_timeout_seconds: float = 60.0
    response_model: str = "gpt-5.6-sol"


@dataclass(frozen=True, slots=True)
class SupertonicSettings:
    model_dir: Path | None = None
    auto_download: bool = True
    voice: str = "F1"
    language: str = "ko"
    total_steps: int = 8
    speed: float = 0.9
    max_text_chars: int = 500
    intra_op_num_threads: int | None = None
    inter_op_num_threads: int | None = None


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    timezone: str = "Asia/Seoul"
    public_origin: str = DEFAULT_PUBLIC_ORIGIN
    cors_origins: tuple[str, ...] = ()
    routine_tick_seconds: float = 5.0
    evaluation_seconds: float = 60.0
    codex_lb: CodexLbSettings = CodexLbSettings()
    supertonic: SupertonicSettings = SupertonicSettings()


def data_directory() -> Path:
    """Return the container bootstrap path for all versioned domain JSON."""

    return Path(os.environ.get("REMINISCENCE_DATA_DIR", "data"))


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeConfigurationError(f"{field} must be an object")
    return value


def _exact(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise RuntimeConfigurationError(
            f"unknown {field} fields: " + ", ".join(sorted(unknown))
        )


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RuntimeConfigurationError(f"{field} must be a trimmed non-empty string")
    return value


def _positive_number(value: Any, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not isfinite(value)
        or value <= 0
    ):
        raise RuntimeConfigurationError(f"{field} must be finite and positive")
    return float(value)


def _optional_positive_integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeConfigurationError(f"{field} must be a positive integer or null")
    return value


def _origin(value: Any, field: str) -> str:
    origin = _text(value, field)
    parsed = urlsplit(origin)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeConfigurationError(f"{field} must be an HTTP origin") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeConfigurationError(f"{field} must be an HTTP origin")
    return f"{parsed.scheme}://{parsed.netloc}"


def _codex_lb(value: Any) -> CodexLbSettings:
    root = _object(value, "runtime.codex_lb")
    _exact(
        root,
        {
            "base_url",
            "connect_timeout_seconds",
            "transcription_read_timeout_seconds",
            "response_read_timeout_seconds",
            "response_model",
        },
        "runtime.codex_lb",
    )
    defaults = CodexLbSettings()
    base_url = _text(
        root.get("base_url", defaults.base_url),
        "runtime.codex_lb.base_url",
    )
    parsed_url = urlsplit(base_url)
    try:
        port = parsed_url.port
    except ValueError as exc:
        raise RuntimeConfigurationError(
            "runtime.codex_lb.base_url must be an HTTP URL ending in /v1"
        ) from exc
    if (
        parsed_url.scheme not in {"http", "https"}
        or parsed_url.hostname is None
        or parsed_url.username is not None
        or parsed_url.password is not None
        or port == 0
        or parsed_url.query
        or parsed_url.fragment
        or not parsed_url.path.rstrip("/").endswith("/v1")
    ):
        raise RuntimeConfigurationError(
            "runtime.codex_lb.base_url must be an HTTP URL ending in /v1"
        )
    return CodexLbSettings(
        base_url=base_url,
        connect_timeout_seconds=_positive_number(
            root.get("connect_timeout_seconds", defaults.connect_timeout_seconds),
            "runtime.codex_lb.connect_timeout_seconds",
        ),
        transcription_read_timeout_seconds=_positive_number(
            root.get(
                "transcription_read_timeout_seconds",
                defaults.transcription_read_timeout_seconds,
            ),
            "runtime.codex_lb.transcription_read_timeout_seconds",
        ),
        response_read_timeout_seconds=_positive_number(
            root.get("response_read_timeout_seconds", defaults.response_read_timeout_seconds),
            "runtime.codex_lb.response_read_timeout_seconds",
        ),
        response_model=_text(
            root.get("response_model", defaults.response_model),
            "runtime.codex_lb.response_model",
        ),
    )


def _supertonic(value: Any) -> SupertonicSettings:
    root = _object(value, "runtime.supertonic")
    _exact(
        root,
        {
            "model_dir",
            "auto_download",
            "voice",
            "language",
            "total_steps",
            "speed",
            "max_text_chars",
            "intra_op_num_threads",
            "inter_op_num_threads",
        },
        "runtime.supertonic",
    )
    defaults = SupertonicSettings()
    model_dir_value = root.get("model_dir")
    if model_dir_value is not None:
        model_dir_value = _text(model_dir_value, "runtime.supertonic.model_dir")
    auto_download = root.get("auto_download", defaults.auto_download)
    if not isinstance(auto_download, bool):
        raise RuntimeConfigurationError("runtime.supertonic.auto_download must be a boolean")
    total_steps = root.get("total_steps", defaults.total_steps)
    max_text_chars = root.get("max_text_chars", defaults.max_text_chars)
    if not isinstance(total_steps, int) or isinstance(total_steps, bool):
        raise RuntimeConfigurationError("runtime.supertonic.total_steps must be an integer")
    if not isinstance(max_text_chars, int) or isinstance(max_text_chars, bool):
        raise RuntimeConfigurationError("runtime.supertonic.max_text_chars must be an integer")
    if not 5 <= total_steps <= 12:
        raise RuntimeConfigurationError(
            "runtime.supertonic.total_steps must be between 5 and 12"
        )
    if not 1 <= max_text_chars <= 500:
        raise RuntimeConfigurationError(
            "runtime.supertonic.max_text_chars must be between 1 and 500"
        )
    language = _text(
        root.get("language", defaults.language),
        "runtime.supertonic.language",
    )
    if language != "ko":
        raise RuntimeConfigurationError("runtime.supertonic.language must be ko")
    speed = _positive_number(
        root.get("speed", defaults.speed),
        "runtime.supertonic.speed",
    )
    if not 0.7 <= speed <= 2.0:
        raise RuntimeConfigurationError(
            "runtime.supertonic.speed must be between 0.7 and 2.0"
        )
    return SupertonicSettings(
        model_dir=Path(model_dir_value) if model_dir_value is not None else None,
        auto_download=auto_download,
        voice=_text(root.get("voice", defaults.voice), "runtime.supertonic.voice"),
        language=language,
        total_steps=total_steps,
        speed=speed,
        max_text_chars=max_text_chars,
        intra_op_num_threads=_optional_positive_integer(
            root.get("intra_op_num_threads"),
            "runtime.supertonic.intra_op_num_threads",
        ),
        inter_op_num_threads=_optional_positive_integer(
            root.get("inter_op_num_threads"),
            "runtime.supertonic.inter_op_num_threads",
        ),
    )


def parse_runtime_settings(
    configuration: dict[str, Any],
    *,
    require_explicit: bool = False,
) -> RuntimeSettings:
    """Parse runtime settings, retaining defaults for legacy v1 documents."""

    runtime_value = configuration.get("runtime")
    if runtime_value is None:
        if require_explicit:
            raise RuntimeConfigurationError("configuration.runtime is required")
        return RuntimeSettings()
    root = _object(runtime_value, "runtime")
    _exact(
        root,
        {
            "timezone",
            "public_origin",
            "cors_origins",
            "routine_tick_seconds",
            "evaluation_seconds",
            "codex_lb",
            "supertonic",
        },
        "runtime",
    )
    defaults = RuntimeSettings()
    timezone = _text(root.get("timezone", defaults.timezone), "runtime.timezone")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeConfigurationError("runtime.timezone is unknown") from exc
    cors_value = root.get("cors_origins", [])
    if not isinstance(cors_value, list):
        raise RuntimeConfigurationError("runtime.cors_origins must be an array")
    cors_origins = tuple(
        _origin(origin, f"runtime.cors_origins[{index}]")
        for index, origin in enumerate(cors_value)
    )
    if len(cors_origins) != len(set(cors_origins)):
        raise RuntimeConfigurationError("runtime.cors_origins must be unique")
    return RuntimeSettings(
        timezone=timezone,
        public_origin=_origin(
            root.get("public_origin", defaults.public_origin),
            "runtime.public_origin",
        ),
        cors_origins=cors_origins,
        routine_tick_seconds=_positive_number(
            root.get("routine_tick_seconds", defaults.routine_tick_seconds),
            "runtime.routine_tick_seconds",
        ),
        evaluation_seconds=_positive_number(
            root.get("evaluation_seconds", defaults.evaluation_seconds),
            "runtime.evaluation_seconds",
        ),
        codex_lb=_codex_lb(root.get("codex_lb", {})),
        supertonic=_supertonic(root.get("supertonic", {})),
    )


def load_runtime_settings(*, require_explicit: bool = False) -> RuntimeSettings:
    """Read runtime settings from the versioned application configuration JSON."""

    root = open_versioned_store(
        data_directory() / "configuration.json",
        missing_default={"routines": [], "photos": [], "conversation": {}},
        read_only=True,
    ).read()
    return parse_runtime_settings(root, require_explicit=require_explicit)


def server_timezone() -> ZoneInfo:
    """Return the configured application timezone."""

    return ZoneInfo(load_runtime_settings().timezone)
