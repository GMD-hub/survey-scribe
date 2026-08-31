# Exceptions and Redaction

Package exceptions expose stable `code` values for application-level handling.
Redaction helpers reduce accidental disclosure in logs and diagnostics, but they
do not replace careful data classification and access controls.

::: survey_scribe.errors
    options:
      members:
        - SurveyScribeError
        - ConfigurationError
        - AmbiguousCredentialError
        - ArtifactError
        - ArtifactCollisionError
        - ArtifactWriteError
        - redact_text
        - is_sensitive_key
        - is_sensitive_query_key
        - redact_exception
        - redact_data
