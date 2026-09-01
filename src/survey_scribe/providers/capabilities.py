"""Named provider/model capabilities and strict request-schema transformation."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from pydantic import BaseModel

from survey_scribe.config import GenerationConfig
from survey_scribe.providers.base import ProviderCapabilityError, ProviderMessage, SchemaDescriptor


class CapabilityEvidence(str, Enum):
    """Evidence state for one named provider and model capability row."""

    verified = "verified"
    configuration_only = "configuration-only"
    unknown = "unknown"


class TokenEstimator(Protocol):
    """Provider-neutral deterministic token estimation contract."""

    def estimate(self, text: str) -> int:
        """Estimate tokens for one string without network access."""
        ...


@dataclass(frozen=True, slots=True)
class ConservativeTokenEstimator:
    """Dependency-free conservative estimate of one token per UTF-8 byte."""

    def estimate(self, text: str) -> int:
        """Return a safe deterministic upper estimate."""
        return len(text.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """One explicit tested or configuration-only provider/model capability row."""

    provider: str
    model: str
    structured_output: bool
    strict_schema: bool
    max_input_tokens: int
    max_output_tokens: int
    supported_generation_settings: frozenset[str]
    evidence: CapabilityEvidence
    tested_sdk_version: str
    token_estimator: TokenEstimator = field(default_factory=ConservativeTokenEstimator)

    def __post_init__(self) -> None:
        if not self.provider or not self.model or not self.tested_sdk_version:
            raise ValueError("capability row identifiers must not be empty")
        for value in (self.max_input_tokens, self.max_output_tokens):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("capability token limits must be positive integers")
        known = frozenset({"temperature", "max_output_tokens", "seed"})
        if not self.supported_generation_settings.issubset(known):
            raise ValueError("capability row contains an unknown generation setting")

    def inspect_schema(self, response_model: type[BaseModel]) -> SchemaDescriptor:
        """Fail closed, then return canonical and transformed schema hashes."""
        if not self.structured_output or not self.strict_schema:
            raise ProviderCapabilityError("strict")
        if self.evidence is CapabilityEvidence.unknown:
            raise ProviderCapabilityError("strict")
        return schema_descriptor(response_model)

    def validate_generation(self, generation: GenerationConfig) -> None:
        """Reject active unsupported settings and output limits before transport."""
        active = {"temperature", "max_output_tokens"}
        if generation.seed is not None:
            active.add("seed")
        if not active.issubset(self.supported_generation_settings):
            raise ProviderCapabilityError("setting")
        if generation.max_output_tokens > self.max_output_tokens:
            raise ProviderCapabilityError("output_limit")

    def estimate_messages(self, messages: tuple[ProviderMessage, ...]) -> int:
        """Estimate complete role and content transport deterministically."""
        return sum(
            self.token_estimator.estimate(message.role)
            + self.token_estimator.estimate(message.content)
            + 4
            for message in messages
        )


def schema_descriptor(response_model: type[BaseModel]) -> SchemaDescriptor:
    """Build deterministic canonical and strict OpenAI-compatible request schemas."""
    if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
        raise TypeError("response model must be a Pydantic model class")
    canonical = response_model.model_json_schema()
    _reject_semantically_open_schema(canonical)
    request = copy.deepcopy(canonical)
    _transform_strict_schema(request)
    canonical_json = _canonical_json(canonical)
    request_json = _canonical_json(request)
    return SchemaDescriptor(
        canonical_schema_sha256=_sha256(canonical_json),
        request_schema_sha256=_sha256(request_json),
        canonical_schema_json=canonical_json,
        request_schema_json=request_json,
    )


def _reject_semantically_open_schema(value: object, *, in_additional: bool = False) -> None:
    if isinstance(value, dict):
        if in_additional and value:
            raise ProviderCapabilityError("schema")
        if value.get("type") == "object" and "properties" not in value:
            raise ProviderCapabilityError("schema")
        additional = value.get("additionalProperties")
        if additional is True or isinstance(additional, dict):
            raise ProviderCapabilityError("schema")
        for key, nested in value.items():
            _reject_semantically_open_schema(nested, in_additional=key == "additionalProperties")
    elif isinstance(value, list):
        for nested in value:
            _reject_semantically_open_schema(nested)


def _transform_strict_schema(value: object) -> None:
    if isinstance(value, dict):
        value.pop("default", None)
        value.pop("discriminator", None)
        value.pop("title", None)
        if "oneOf" in value:
            value["anyOf"] = value.pop("oneOf")
        properties = value.get("properties")
        if isinstance(properties, dict):
            value["required"] = list(properties)
            value["additionalProperties"] = False
        for nested in value.values():
            _transform_strict_schema(nested)
    elif isinstance(value, list):
        for nested in value:
            _transform_strict_schema(nested)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "CapabilityEvidence",
    "ConservativeTokenEstimator",
    "ModelCapabilities",
    "TokenEstimator",
    "schema_descriptor",
]
