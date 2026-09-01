"""Tests for the documented top-level package API."""

from __future__ import annotations

from importlib.metadata import version

import survey_scribe
from survey_scribe import models, routing


def test_public_api_exports_models_and_version() -> None:
    legacy = {
        "AnswerCategory",
        "DataType",
        "NumericRange",
        "StudyType",
        "SurveySVIS",
        "SurveyVariable",
        "UnitLevel",
    }
    routed_models = {
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
    expected_models = legacy | routed_models
    expected = expected_models | {"QuestionnaireRouter", "RoutingConfig", "__version__"}

    assert set(survey_scribe.__all__) == expected
    assert set(models.__all__) == expected_models
    assert all(hasattr(survey_scribe, name) for name in expected)
    assert all(getattr(survey_scribe, name) is getattr(models, name) for name in routed_models)


def test_routing_api_exports_router_configuration_and_contract_models() -> None:
    required = {
        "ActivationEvidence",
        "CanonicalRoutingCondition",
        "ConditionOperator",
        "Containment",
        "ExtractedRoutingCondition",
        "ItemReference",
        "NativeExpression",
        "NodeKind",
        "QuestionnaireRouter",
        "RoutingConfig",
        "RoutingEvidenceBatch",
        "SourceSpan",
        "TransitionEvidence",
    }

    assert required.issubset(routing.__all__)
    assert all(hasattr(routing, name) for name in required)


def test_source_package_contains_step_10_runtime_modules(repository_root) -> None:
    required = {
        "src/survey_scribe/models/routing.py",
        "src/survey_scribe/serialization/routing.py",
    }
    expected_routing_modules = {
        "src/survey_scribe/routing/__init__.py",
        "src/survey_scribe/routing/algorithms.py",
        "src/survey_scribe/routing/config.py",
        "src/survey_scribe/routing/contracts.py",
        "src/survey_scribe/routing/diagnostics.py",
        "src/survey_scribe/routing/extraction.py",
        "src/survey_scribe/routing/identity.py",
        "src/survey_scribe/routing/inventory.py",
        "src/survey_scribe/routing/native.py",
        "src/survey_scribe/routing/pipeline.py",
        "src/survey_scribe/routing/prompts.py",
        "src/survey_scribe/routing/reconcile.py",
        "src/survey_scribe/routing/review.py",
        "src/survey_scribe/routing/validate.py",
    }
    routing_root = repository_root / "src/survey_scribe/routing"
    actual_routing_modules = {
        path.relative_to(repository_root).as_posix() for path in routing_root.glob("*.py")
    }

    assert all((repository_root / relative).is_file() for relative in required)
    assert actual_routing_modules == expected_routing_modules
    pyproject = (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'packages = ["src/survey_scribe", "schemas"]' in pyproject


def test_runtime_version_comes_from_distribution_metadata() -> None:
    assert survey_scribe.__version__ == version("survey-scribe")
