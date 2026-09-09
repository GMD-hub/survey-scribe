# Routing API

The routed model is additive. Legacy `SurveyVariable` and `SurveySVIS` fields and
ordered JSON semantics remain unchanged.

## Router methods

| Method | Return | Behavior |
| --- | --- | --- |
| `route(source, svis, source_binding=...)` | `ExtractionResult[RoutedSurveySVIS]` | Synchronous routing outside an event loop |
| `aroute(source, svis, source_binding=...)` | `ExtractionResult[RoutedSurveySVIS]` | Async routing |

The constructor accepts a `StructuredProvider | None`, optional `RoutingConfig`,
and optional `SourceRegistry`. `None` is valid only for complete native routing.
The exact source name, media type, digest, survey ID, and binding version must
match before provider work starts.

Expected source, binding, provider, and graph failures become safe failed result
envelopes. An unexpected programming error can propagate. `route()` raises
`RuntimeError` when called inside an active event loop.

::: survey_scribe.models.routing
    options:
      members:
        - CandidateEdge
        - CandidateStatus
        - Containment
        - DiagnosticSeverity
        - DiscrepancyKind
        - EdgeKind
        - EvidenceRecord
        - InventoryItem
        - LoopDefinition
        - LoopKind
        - RepeatKind
        - RepeatSpec
        - ReplacementEdge
        - ReviewAction
        - ReviewDecision
        - RoutingDiagnostic
        - RoutingDiscrepancy
        - RoutingNode
        - RoutingEdge
        - RoutingSourceBinding
        - TerminalKind
        - QuestionnaireRoutingGraph
        - RoutingAudit
        - RoutedSurveyVariable
        - RoutedSurveySVIS
        - RoutedAnswerCategory
        - RoutedNumericRange
        - canonical_routing_schema_json

::: survey_scribe.routing.contracts
    options:
      members:
        - ActivationEvidence
        - CanonicalRoutingCondition
        - ConditionOperator
        - EvidenceObservation
        - EvidenceOrigin
        - EvidencePerspective
        - ExtractedRoutingCondition
        - ItemReference
        - NodeKind
        - RoutingPassKind
        - RoutingScalar
        - RoutingEvidenceBatch
        - SourceSpan
        - NativeExpression
        - StrictRoutingModel
        - TransitionEvidence
        - TransitionKind
        - project_extracted_condition

::: survey_scribe.routing.pipeline
    options:
      members:
        - QuestionnaireRouter

::: survey_scribe.routing.config
    options:
      members:
        - RoutingConfig
