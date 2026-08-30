"""Typed Survey Scribe errors and safe redaction helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "api_key",
        "key",
        "token",
        "access_token",
        "client_secret",
        "password",
        "secret",
        "signature",
        "sig",
        "credential",
    }
)

_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|authorization|bearer[_-]?token|access[_-]?token|"
    r"refresh[_-]?token|client[_-]?secret|password|secret|signature|credential|"
    r"question[_-]?text)",
    re.IGNORECASE,
)
_AUTHORIZATION_VALUE = re.compile(r"(?im)(\b(?:proxy-)?authorization\s*[:=]\s*)[^\r\n]+")
_URL_USER_INFORMATION = re.compile(r"(?i)(\bhttps?://)[^/@\s]+@")
_ESCAPED_QUOTED_ASSIGNED_SECRET = re.compile(
    r"(?i)(\\[\"'](?:api[_-]?key|bearer[_-]?token|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|secret|signature|credential)\\[\"']\s*[=:]\s*"
    r"\\[\"'])(.*?)(\\[\"'])"
)
_QUOTED_ASSIGNED_SECRET = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|bearer[_-]?token|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|secret|signature|credential)[\"']?\s*[=:]\s*)"
    r"([\"'])(.*?)\2"
)
_ASSIGNED_SECRET = re.compile(
    r"(?i)(\b(?:api[_-]?key|bearer[_-]?token|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|secret|signature|credential)\b\s*[=:]\s*)"
    r"[^\s,;&#}]+"
)
_QUERY_KEY_PATTERN = "|".join(
    re.escape(key).replace("_", r"[_-]?")
    for key in sorted(_SENSITIVE_QUERY_KEYS, key=len, reverse=True)
)
_QUERY_SECRET = re.compile(rf"(?i)([?&](?:{_QUERY_KEY_PATTERN})=)[^&#\s]+")


class SurveyScribeError(Exception):
    """Base class for stable public Survey Scribe errors."""

    code = "SURVEY_SCRIBE_ERROR"


class ConfigurationError(SurveyScribeError, ValueError):
    """Configuration cannot be loaded or validated."""

    code = "CONFIGURATION_INVALID"


class AmbiguousCredentialError(ConfigurationError):
    """More than one mutually exclusive credential form was supplied."""

    code = "CREDENTIALS_AMBIGUOUS"


class ArtifactError(SurveyScribeError):
    """Base class for artifact transaction errors."""

    code = "ARTIFACT_ERROR"


class ArtifactCollisionError(ArtifactError, FileExistsError):
    """An artifact exists or another writer owns the survey lock."""

    code = "ARTIFACT_COLLISION"


class ArtifactWriteError(ArtifactError, OSError):
    """A required artifact transaction stage failed."""

    code = "ARTIFACT_WRITE_FAILED"

    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(f"Artifact {stage} stage failed: {redact_text(message)}")


def redact_text(value: str, *, sensitive_values: Sequence[str] = ()) -> str:
    """Remove credentials and caller-identified private text from a string."""
    redacted = value
    for sensitive in sorted((item for item in sensitive_values if item), key=len, reverse=True):
        redacted = redacted.replace(sensitive, REDACTED)
    redacted = _AUTHORIZATION_VALUE.sub(rf"\1{REDACTED}", redacted)
    redacted = _URL_USER_INFORMATION.sub(rf"\1{REDACTED}@", redacted)
    redacted = _ESCAPED_QUOTED_ASSIGNED_SECRET.sub(rf"\1{REDACTED}\3", redacted)
    redacted = _QUOTED_ASSIGNED_SECRET.sub(rf"\1\2{REDACTED}\2", redacted)
    redacted = _ASSIGNED_SECRET.sub(rf"\1{REDACTED}", redacted)
    return _QUERY_SECRET.sub(rf"\1{REDACTED}", redacted)


def is_sensitive_key(value: str) -> bool:
    """Return whether a field name denotes recognized sensitive content."""
    return _SECRET_KEY.search(value) is not None


def is_sensitive_query_key(value: str) -> bool:
    """Return whether an exact URL query key carries credentials."""
    normalized = value.strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_QUERY_KEYS


def redact_exception(error: BaseException, *, sensitive_values: Sequence[str] = ()) -> str:
    """Render an exception chain without retaining nested sensitive values."""
    rendered: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = redact_text(str(current), sensitive_values=sensitive_values)
        rendered.append(f"{type(current).__name__}: {message}")
        current = current.__cause__ or current.__context__
    return " <- ".join(rendered)


def redact_data(value: Any, *, sensitive_values: Sequence[str] = ()) -> Any:
    """Recursively redact mappings, sequences, strings, and exceptions."""
    if isinstance(value, BaseException):
        return redact_exception(value, sensitive_values=sensitive_values)
    if isinstance(value, str):
        return redact_text(value, sensitive_values=sensitive_values)
    if isinstance(value, Mapping):
        return {
            key: (
                REDACTED
                if isinstance(key, str) and is_sensitive_key(key)
                else redact_data(item, sensitive_values=sensitive_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact_data(item, sensitive_values=sensitive_values) for item in value)
    if isinstance(value, list):
        return [redact_data(item, sensitive_values=sensitive_values) for item in value]
    if isinstance(value, set):
        return {redact_data(item, sensitive_values=sensitive_values) for item in value}
    return value
