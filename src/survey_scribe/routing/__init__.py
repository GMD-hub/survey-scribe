"""Stable lazy public questionnaire routing API and typed contracts."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from survey_scribe.models.routing import (
        CandidateEdge,
        CandidateStatus,
        Containment,
        DiagnosticSeverity,
        DiscrepancyKind,
        EdgeKind,
        EvidenceRecord,
        InventoryItem,
        LoopDefinition,
        LoopKind,
        QuestionnaireRoutingGraph,
        RepeatKind,
        RepeatSpec,
        ReplacementEdge,
        ReviewAction,
        ReviewDecision,
        RoutedAnswerCategory,
        RoutedNumericRange,
        RoutedSurveySVIS,
        RoutedSurveyVariable,
        RoutingAudit,
        RoutingDiagnostic,
        RoutingDiscrepancy,
        RoutingEdge,
        RoutingNode,
        RoutingSourceBinding,
        TerminalKind,
        canonical_routing_schema_json,
    )
    from survey_scribe.routing.config import RoutingConfig
    from survey_scribe.routing.contracts import (
        ActivationEvidence,
        CanonicalRoutingCondition,
        ConditionOperator,
        EvidenceObservation,
        EvidenceOrigin,
        EvidencePerspective,
        ExtractedRoutingCondition,
        ItemReference,
        NativeExpression,
        NodeKind,
        RoutingEvidenceBatch,
        RoutingPassKind,
        RoutingScalar,
        SourceSpan,
        StrictRoutingModel,
        TransitionEvidence,
        TransitionKind,
        project_extracted_condition,
    )
    from survey_scribe.routing.pipeline import QuestionnaireRouter

_MODEL_EXPORTS = frozenset(
    {
        "CandidateEdge",
        "CandidateStatus",
        "Containment",
        "DiagnosticSeverity",
        "DiscrepancyKind",
        "EdgeKind",
        "EvidenceRecord",
        "InventoryItem",
        "LoopDefinition",
        "LoopKind",
        "QuestionnaireRoutingGraph",
        "RepeatKind",
        "RepeatSpec",
        "ReplacementEdge",
        "ReviewAction",
        "ReviewDecision",
        "RoutedAnswerCategory",
        "RoutedNumericRange",
        "RoutedSurveySVIS",
        "RoutedSurveyVariable",
        "RoutingAudit",
        "RoutingDiagnostic",
        "RoutingDiscrepancy",
        "RoutingEdge",
        "RoutingNode",
        "RoutingSourceBinding",
        "TerminalKind",
        "canonical_routing_schema_json",
    }
)
_CONTRACT_EXPORTS = frozenset(
    {
        "ActivationEvidence",
        "CanonicalRoutingCondition",
        "ConditionOperator",
        "EvidenceObservation",
        "EvidenceOrigin",
        "EvidencePerspective",
        "ExtractedRoutingCondition",
        "ItemReference",
        "NativeExpression",
        "NodeKind",
        "RoutingEvidenceBatch",
        "RoutingPassKind",
        "RoutingScalar",
        "SourceSpan",
        "StrictRoutingModel",
        "TransitionEvidence",
        "TransitionKind",
        "project_extracted_condition",
    }
)

__all__ = [
    "ActivationEvidence",
    "CandidateEdge",
    "CandidateStatus",
    "CanonicalRoutingCondition",
    "ConditionOperator",
    "Containment",
    "DiagnosticSeverity",
    "DiscrepancyKind",
    "EdgeKind",
    "EvidenceObservation",
    "EvidenceOrigin",
    "EvidencePerspective",
    "EvidenceRecord",
    "ExtractedRoutingCondition",
    "InventoryItem",
    "ItemReference",
    "LoopDefinition",
    "LoopKind",
    "NativeExpression",
    "NodeKind",
    "QuestionnaireRouter",
    "QuestionnaireRoutingGraph",
    "RepeatKind",
    "RepeatSpec",
    "ReplacementEdge",
    "ReviewAction",
    "ReviewDecision",
    "RoutedAnswerCategory",
    "RoutedNumericRange",
    "RoutedSurveySVIS",
    "RoutedSurveyVariable",
    "RoutingAudit",
    "RoutingConfig",
    "RoutingDiagnostic",
    "RoutingDiscrepancy",
    "RoutingEdge",
    "RoutingEvidenceBatch",
    "RoutingNode",
    "RoutingPassKind",
    "RoutingScalar",
    "RoutingSourceBinding",
    "SourceSpan",
    "StrictRoutingModel",
    "TerminalKind",
    "TransitionEvidence",
    "TransitionKind",
    "canonical_routing_schema_json",
    "project_extracted_condition",
]


def __getattr__(name: str) -> Any:
    """Load public routing objects without creating model-contract import cycles."""
    if name in _MODEL_EXPORTS:
        module_name = "survey_scribe.models.routing"
    elif name in _CONTRACT_EXPORTS:
        module_name = "survey_scribe.routing.contracts"
    elif name == "RoutingConfig":
        module_name = "survey_scribe.routing.config"
    elif name == "QuestionnaireRouter":
        module_name = "survey_scribe.routing.pipeline"
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
