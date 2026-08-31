"""Legacy-compatible main JSON serialization."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, TypeAdapter


def legacy_payload(output: Any) -> Any:
    """Convert structured output to JSON values while preserving field order.

    Args:
        output: Pydantic model or another value supported by Pydantic's type
            adapter.

    Returns:
        A JSON-compatible value with model field order preserved.

    Raises:
        TypeError: A nested mapping uses a non-string key.
    """
    if isinstance(output, BaseModel):
        _require_string_mapping_keys(output.model_dump(mode="python"))
        return output.model_dump(mode="json")
    _require_string_mapping_keys(output)
    return TypeAdapter(type(output)).dump_python(output, mode="json")


def legacy_json_bytes(output: Any) -> bytes:
    """Serialize the compatibility projection as deterministic UTF-8 JSON.

    Args:
        output: Pydantic model or another supported Python value.

    Returns:
        Two-space-indented UTF-8 JSON bytes with field order preserved.

    Raises:
        TypeError: A nested mapping uses a non-string key.
        ValueError: The converted value contains a non-finite JSON number.
    """
    rendered = json.dumps(
        legacy_payload(output),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    return rendered.encode("utf-8")


def _require_string_mapping_keys(value: Any) -> None:
    if isinstance(value, BaseModel):
        _require_string_mapping_keys(value.model_dump(mode="python"))
    elif isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Legacy JSON mappings must use string keys")
        for item in value.values():
            _require_string_mapping_keys(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _require_string_mapping_keys(item)
