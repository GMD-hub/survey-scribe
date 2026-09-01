"""Typed routed SVIS projection and manifest v2 serialization."""

from __future__ import annotations

import hashlib
from copy import deepcopy

from pydantic import ValidationError

from survey_scribe.errors import ArtifactWriteError
from survey_scribe.models.routing import RoutedSurveySVIS
from survey_scribe.results import ArtifactKind, ArtifactProvenance
from survey_scribe.routing.contracts import EvidenceOrigin
from survey_scribe.serialization.artifacts import (
    ArtifactManifestV1,
    ArtifactManifestV2,
    ArtifactPlan,
    RoutedManifestMetadata,
    SerializedArtifact,
    parse_artifact_manifest,
)
from survey_scribe.serialization.legacy import legacy_json_bytes


class RoutedSurveySVISArtifactSerializer:
    """Build one detached routed main and exact ordered v1 projection."""

    def __init__(self, *, provenance: ArtifactProvenance | None = None) -> None:
        self._provenance = provenance

    def build_plan(self, output: RoutedSurveySVIS, *, survey_id: str) -> ArtifactPlan:
        """Revalidate a frozen routed snapshot before any filesystem operation."""
        if type(output) is not RoutedSurveySVIS:
            raise ArtifactWriteError(
                "validation",
                "Routed SVIS serialization requires the exact routed output type",
            )
        try:
            snapshot = RoutedSurveySVIS.model_validate(deepcopy(output.model_dump(mode="json")))
        except (TypeError, ValueError, ValidationError):
            raise ArtifactWriteError(
                "validation",
                "Routed artifact validation failed",
            ) from None
        if snapshot.survey_id != survey_id:
            raise ArtifactWriteError(
                "validation",
                "The detached routed survey identity does not match the result",
            )
        try:
            routed_content = legacy_json_bytes(snapshot)
            projection = snapshot.to_survey_svis()
            projection_content = legacy_json_bytes(projection)
        except (TypeError, ValueError):
            raise ArtifactWriteError(
                "validation",
                "Routed artifact serialization failed",
            ) from None

        provenance = self._validated_provenance(snapshot)
        routed_filename = f"{survey_id}_routed_svis.json"
        projection_filename = f"{survey_id}_svis.json"
        return ArtifactPlan(
            survey_id=survey_id,
            files=(
                SerializedArtifact(
                    kind=ArtifactKind.main,
                    generation_filename=routed_filename,
                    content=routed_content,
                ),
                SerializedArtifact(
                    kind=ArtifactKind.projection,
                    generation_filename=projection_filename,
                    content=projection_content,
                    publication_filename=projection_filename,
                    publication_kind=ArtifactKind.legacy,
                ),
            ),
            manifest_schema_version=2,
            routed_metadata=RoutedManifestMetadata(
                routing_schema_version=snapshot.routing_schema_version,
                graph_schema_version=snapshot.routing_graph.schema_version,
                routed_main_sha256=_sha256(routed_content),
                legacy_projection_sha256=_sha256(projection_content),
                prompt_versions=provenance.prompt_versions,
                source_sha256=provenance.source_sha256,
                model_response_sha256=provenance.model_response_sha256,
            ),
        )

    def _validated_provenance(self, snapshot: RoutedSurveySVIS) -> ArtifactProvenance:
        binding_digest = snapshot.routing_graph.routing_audit.source_binding.snapshot_sha256
        model_evidence = tuple(
            record
            for record in snapshot.routing_graph.routing_audit.evidence
            if record.observation.origin is not EvidenceOrigin.native_parser
        )
        if self._provenance is None:
            if model_evidence or snapshot.routing_graph.routing_audit.review_decisions:
                raise ArtifactWriteError(
                    "validation",
                    "Routed model provenance is required for model-derived evidence",
                )
            return ArtifactProvenance(
                source_sha256=(binding_digest,),
                model_response_sha256=(),
                prompt_versions=(),
            )

        try:
            provenance = ArtifactProvenance.model_validate(
                deepcopy(self._provenance.model_dump(mode="json"))
            )
        except (TypeError, ValueError, ValidationError):
            raise ArtifactWriteError(
                "validation",
                "Routed artifact provenance is invalid",
            ) from None
        if provenance.source_sha256 != (binding_digest,):
            raise ArtifactWriteError(
                "validation",
                "Routed source provenance does not match the detached source binding",
            )
        if model_evidence and (
            not provenance.model_response_sha256 or not provenance.prompt_versions
        ):
            raise ArtifactWriteError(
                "validation",
                "Routed model provenance is incomplete",
            )
        prompt_keys = {
            (item.pass_kind, item.version, item.prompt_sha256)
            for item in provenance.prompt_versions
        }
        response_digests = set(provenance.model_response_sha256)
        for decision in snapshot.routing_graph.routing_audit.review_decisions:
            if (
                "reviewer",
                decision.prompt_version,
                decision.prompt_sha256,
            ) not in prompt_keys or decision.provider_response_sha256 not in response_digests:
                raise ArtifactWriteError(
                    "validation",
                    "Routed review provenance is incomplete",
                )
        return provenance


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


__all__ = [
    "ArtifactManifestV1",
    "ArtifactManifestV2",
    "RoutedSurveySVISArtifactSerializer",
    "parse_artifact_manifest",
]
