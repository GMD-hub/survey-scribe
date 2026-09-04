# Client and Pipeline API

`SurveyScribe` is the public SVIS extraction facade. It supports synchronous,
asynchronous, and ordered batch conversion. It accepts an injected
`StructuredProvider` or explicit provider configuration.

::: survey_scribe.client.SurveyScribe

`StructuredPipeline` makes one bounded provider call for a caller-defined
Pydantic model. `ChunkedStructuredPipeline` requires a caller reducer and defines
explicit strict and partial behavior.

::: survey_scribe.pipeline.StructuredPipeline

::: survey_scribe.pipeline.ChunkedStructuredPipeline

See [Custom Structured Output](../guides/custom-models.md) for guarantees,
limits, and a credential-free executable example.
