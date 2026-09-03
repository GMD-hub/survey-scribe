# Routing API

The routed model is additive. Legacy `SurveyVariable` and `SurveySVIS` fields and
ordered JSON semantics remain unchanged.

::: survey_scribe.models.routing
    options:
      members:
        - CandidateEdge
        - CandidateStatus
        - DiagnosticSeverity
        - DiscrepancyKind
        - EdgeKind
        - EvidenceRecord
        - InventoryItem
        - LoopDefinition
        - LoopKind
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
        - canonical_routing_schema_json

::: survey_scribe.routing.contracts
    options:
      members:
        - CanonicalRoutingCondition
        - ConditionOperator
        - EvidenceObservation
        - EvidenceOrigin
        - EvidencePerspective
        - ExtractedRoutingCondition
        - NodeKind
        - RoutingEvidenceBatch
        - SourceSpan
        - NativeExpression

::: survey_scribe.routing.pipeline
    options:
      members:
        - QuestionnaireRouter

::: survey_scribe.routing.config
    options:
      members:
        - RoutingConfig
