# Completed Questionnaires

Survey Scribe has two different meanings of questionnaire extraction. The
standard client extracts the structure of an instrument. A custom structured
pipeline can extract an application-defined record from a filled document.

## Support boundary

| Use case | Support |
| --- | --- |
| Extract instrument variables and answer options | Native `SurveyScribe` output |
| Extract native XLSForm instrument metadata | Provider-free `SourceRegistry.convert_for_svis()` |
| Extract caller-defined answers from a filled PDF or document | Supported through a custom Pydantic model and provider |
| Parse ODK, Kobo, or another submission export | No specialized parser |
| Produce respondent microdata rows | No built-in schema or table output |
| Detect whether a blank answer was skipped, missing, or unreadable | Caller-defined logic only |
| Apply routing conditions to observed answers | Not implemented |
| Expand roster or repeat instances | Not implemented |

`AnswerCategory` describes an allowed option in an instrument. It is not an
observed response. `None` in `SurveySVIS` means that metadata is absent. It does
not mean that a respondent skipped a question.

## Define an answer contract

Use a closed Pydantic model. Make answer state explicit instead of assigning one
meaning to `None`:

```python
# docs-exec: completed-answer-contract
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

NonEmptyText = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1),
]
FiniteStrictFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
AnswerValue = StrictStr | StrictInt | FiniteStrictFloat | StrictBool


class CompletedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: NonEmptyText
    value: AnswerValue | None
    state: Literal["answered", "skipped", "missing", "unreadable"]
    source_block_ids: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    repeat_instance: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_answer_state(self) -> Self:
        if self.state == "answered" and self.value is None:
            raise ValueError("an answered record requires a value")
        if self.state == "answered" and isinstance(self.value, str) and not self.value.strip():
            raise ValueError("an answered text record requires nonempty text")
        if self.state != "answered" and self.value is not None:
            raise ValueError("a non-answered record cannot contain a value")
        if len(set(self.source_block_ids)) != len(self.source_block_ids):
            raise ValueError("source block identifiers must be unique")
        return self


class CompletedQuestionnaire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    survey_id: NonEmptyText
    respondent_id: NonEmptyText | None = None
    answers: tuple[CompletedAnswer, ...]


synthetic_record = CompletedQuestionnaire(
    survey_id="SYN_2026_COMPLETED",
    answers=(
        CompletedAnswer(
            question_id="age",
            value=42,
            state="answered",
            source_block_ids=("block-000001",),
        ),
    ),
)

try:
    CompletedAnswer(
        question_id="age",
        value=42,
        state="skipped",
        source_block_ids=("block-000001",),
    )
except ValidationError:
    pass
else:
    raise AssertionError("a skipped answer cannot contain a value")

for invalid_answer in (
    {
        "question_id": "   ",
        "value": 42,
        "state": "answered",
        "source_block_ids": ("block-000001",),
    },
    {
        "question_id": "age",
        "value": float("nan"),
        "state": "answered",
        "source_block_ids": ("block-000001",),
    },
):
    try:
        CompletedAnswer.model_validate(invalid_answer)
    except ValidationError:
        pass
    else:
        raise AssertionError("invalid completed-answer data was accepted")
```

These classes are application code. Survey Scribe does not provide or interpret
them. Keep `respondent_id=None` when the source has no visible, authorized
identifier. Do not infer one.

## Extract one bounded document

Given an application-configured `StructuredProvider` named `provider`:

For PDF input, install both the selected provider extra and the `pdf` extra, then
configure the approved local OCR artifacts. Use DOCX or text when OCR is not
required.

```python
from survey_scribe import ResultStatus, StructuredPipeline
from survey_scribe.sources import SourceRegistry

pipeline = StructuredPipeline(
    provider,
    CompletedQuestionnaire,
    instructions=(
        "Extract only answer marks that are visible in the source. "
        "Record the exact normalized source block IDs for each answer. "
        "Use skipped only when the source gives direct skip evidence. "
        "Use missing for a blank applicable answer and unreadable when a mark "
        "cannot be read. Do not infer respondent identity or answer values."
    ),
    max_request_tokens=32_000,
    max_concurrency=2,
)

async def extract_completed_questionnaire():
    document = SourceRegistry.default().convert("completed-questionnaire.pdf")
    result = await pipeline.extract(document)
    if result.status is not ResultStatus.success or result.output is None:
        codes = tuple(item.code for item in result.diagnostics)
        raise RuntimeError(f"Send completed-form extraction to review: {codes}")

    known_block_ids = {block.id for block in document.blocks}
    unknown_block_ids = {
        block_id
        for answer in result.output.answers
        for block_id in answer.source_block_ids
        if block_id not in known_block_ids
    }
    if unknown_block_ids:
        raise RuntimeError("Provider returned unknown source block identifiers")
    return result
```

The provider must support strict structured output for the closed schema.
Open-ended mappings such as `dict[str, object]` fail capability inspection before
source content is sent.

## Extract a long completed questionnaire

Use `ChunkedStructuredPipeline` when one request cannot hold the normalized
document. The reducer owns duplicate removal, answer conflicts, repeat assembly,
and cross-chunk validation:

```python
from pydantic import BaseModel, ConfigDict

from survey_scribe import ChunkedStructuredPipeline, ResultStatus
from survey_scribe.providers import ProviderResponse
from survey_scribe.results import FailedBlock
from survey_scribe.sources import SourceRegistry


class AnswerChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: tuple[CompletedAnswer, ...]


class CompletedBatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    survey_id: NonEmptyText
    answers: tuple[CompletedAnswer, ...]
    failed_chunks: tuple[str, ...]


def combine_answers(
    responses: tuple[ProviderResponse[AnswerChunk], ...],
    failures: tuple[FailedBlock, ...],
) -> CompletedBatchRecord:
    return CompletedBatchRecord(
        survey_id="SYN_2026_COMPLETED",
        answers=tuple(
            answer
            for response in responses
            for answer in response.output.answers
        ),
        failed_chunks=tuple(item.block_id for item in failures),
    )


pipeline = ChunkedStructuredPipeline(
    provider,
    AnswerChunk,
    combine_answers,
    allow_partial=True,
    overlap_tokens=1_000,
    max_concurrency=4,
)

async def extract_long_completed_questionnaire():
    document = SourceRegistry.default().convert("completed-questionnaire.pdf")
    result = await pipeline.extract(document)
    if result.status is not ResultStatus.success or result.output is None:
        codes = tuple(item.code for item in result.diagnostics)
        raise RuntimeError(f"Send long-form extraction to review: {codes}")

    known_block_ids = {block.id for block in document.blocks}
    if any(
        block_id not in known_block_ids
        for answer in result.output.answers
        for block_id in answer.source_block_ids
    ):
        raise RuntimeError("Provider returned unknown source block identifiers")
    return result
```

This minimal reducer concatenates answers. A production reducer must also:

- Remove overlap duplicates with source-aware keys.
- Reject conflicting values for one question and repeat instance.
- Preserve stable source order.
- Validate expected question identifiers.
- Define whether a failed chunk makes the final record publishable.
- Record application-level provenance for each accepted answer.

Custom pipelines do not populate Survey Scribe artifact prompt and model
provenance. Add application provenance before you publish the result.

## Skip-pattern handling

The routing graph and completed-answer output are independent products. Survey
Scribe does not evaluate `RoutingEdge.condition` or
`RoutingNode.activation_condition` against extracted answers.

Use this safe application sequence:

1. Extract or load the questionnaire instrument and its stable question IDs.
2. Build and review the routed instrument separately.
3. Extract completed answers with an explicit answer-state model.
4. Join only on reviewed question identities.
5. Run an application-owned condition evaluator if your policy permits it.
6. Keep evaluator output separate from source-observed answer state.

Do not relabel an empty value as `skipped` only because a routing condition could
make the question inactive. That is an inference, not a source observation.

## Repeats and rosters

Questionnaire routing stores repeat groups as logical templates. It does not
create respondent instances. Add a stable application field such as
`repeat_instance` and define its source evidence before extraction.

For long files, the reducer must assemble answers that belong to the same roster
instance. Survey Scribe does not use XLSForm `repeat_count` to set an iteration
limit or to validate completed records.

## Quality controls

Before publication, validate at least these rules in your application:

- Every answer has a known questionnaire identifier.
- Each answer value matches the expected data type.
- Categorical codes belong to the reviewed choice list.
- Numeric values satisfy the approved range policy.
- Answer state and value are consistent.
- Repeat-instance identifiers are complete and unique.
- Source evidence exists for all extracted values.
- Partial results are quarantined until review.

The standard SVIS model does not perform these respondent-level checks.

## Privacy and retention

Completed questionnaires can contain direct identifiers and sensitive response
data. Survey Scribe does not remove that content from a custom output model.
The configured provider receives normalized source content. Before model-assisted
extraction, confirm source authorization, endpoint location, retention, model
training policy, abuse monitoring, and host logging.

Use the smallest source and output permissions possible. Do not write a primary
answer artifact to the same location as digest-only diagnostics unless both have
the same approved access class.

See [Privacy and Local-First Boundaries](privacy.md),
[Security and API Keys](security.md), and
[Custom Structured Output](custom-models.md).
