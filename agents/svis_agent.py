"""
SVIS Extraction Agents
=======================
LLM-powered extraction of survey metadata and variable information.

Uses the `instructor` library, which wraps the World Bank Azure OpenAI
gateway (via the OpenAI SDK) and:
  1. Enforces the Pydantic schema on LLM output
  2. Automatically sends validation errors back to the LLM and retries
  3. Raises an exception after max_retries failed attempts

This means the pipeline never receives malformed output silently.
Either it gets a valid Pydantic object, or it gets an exception that
can be caught, logged, and routed to the human review queue.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

import instructor
from itsai.platform.authentication import DesktopToken
from openai import AzureOpenAI, RateLimitError
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from agents.prompts import SURVEY_METADATA_PROMPT, VARIABLE_EXTRACTION_PROMPT
from extractors.pdf import DocumentChunk
from schemas.svis import StudyType, SurveySVIS, SurveyVariable

# ── Client ────────────────────────────────────────────────────────────────────
# Authenticates against the World Bank Azure OpenAI gateway using an
# Azure AD token (via DesktopToken) instead of a static API key.

_AZURE_ENDPOINT = "https://azapimdev.worldbank.org/conversationalai/v2/"
_AZURE_API_VERSION = "2025-04-01-preview"

_token_class = DesktopToken()
_token_provider = lambda: _token_class.get_token(env="DEV_DESKTOP")

_client = instructor.from_openai(
    AzureOpenAI(
        azure_endpoint=_AZURE_ENDPOINT,
        api_version=_AZURE_API_VERSION,
        azure_ad_token_provider=_token_provider,
    )
)

MODEL      = "gpt-4.1-mini"
MAX_TOKENS = 16384
MAX_RETRIES = 3   # instructor will retry this many times on schema validation failure

# The Azure OpenAI gateway enforces a short-window request-rate limit —
# under sustained per-chunk extraction calls this surfaces as HTTP 429
# ("Rate limit is exceeded. Try again in N seconds"). instructor's own
# max_retries only governs schema-validation retries, not this kind of
# transport-level error, so it is retried here explicitly with
# exponential backoff (respecting jitter to avoid retry storms) before
# giving up.
RATE_LIMIT_MAX_ATTEMPTS = 6


@retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_random_exponential(min=2, max=30),
    stop=stop_after_attempt(RATE_LIMIT_MAX_ATTEMPTS),
    reraise=True,
)
def _create(**kwargs):
    """Thin wrapper around _client.chat.completions.create() that adds
    rate-limit retry/backoff on top of instructor's schema-validation retries."""
    return _client.chat.completions.create(**kwargs)


# ── Internal response models ──────────────────────────────────────────────────
# These are minimal models used only for individual LLM calls.
# They are separate from the full SVIS schema so the metadata call
# does not ask the LLM to also produce variables (and vice versa).

class _SurveyMeta(BaseModel):
    """Response model for the survey metadata extraction call."""
    survey_id: str
    country_code: str
    year: int
    survey_name: str
    study_type: Optional[StudyType] = None
    data_collection_mode: Optional[str] = None
    language: Optional[str] = None


class _VariableBatch(BaseModel):
    """
    Response model for the variable extraction call.
    Wraps a list so the LLM returns zero or more variables from one chunk.
    """
    variables: list[SurveyVariable]


# The LLM's raw `year` field has proven unreliable -- it is a required
# `int` (not Optional), so when it can't find a year it may fall back to
# a placeholder like 0, and it has also been observed to hallucinate an
# unrelated year (e.g. the current year) even when a correct year is
# present in the sampled text. The survey name and filename are far more
# reliable: questionnaire titles conventionally embed the reference year
# (e.g. "EICVM 2009-2010", "...HBS_2014.pdf"), so the year is derived
# from those deterministically via regex and only falls back to the LLM's
# raw value if neither contains a parseable year.
_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")


def _resolve_year(meta_year: int, survey_name: str | None, source_file: str) -> int:
    """Prefers a year parsed from survey_name, then source_file, then
    falls back to the LLM-reported meta_year if neither yields one."""
    for text in (survey_name, source_file):
        if text:
            match = _YEAR_RE.search(text)
            if match:
                return int(match.group(0))
    return meta_year


# ── Agent functions ───────────────────────────────────────────────────────────

def extract_survey_metadata(
    opening_text: str,
    source_file: str,
    source_format: str = "pdf",
) -> SurveySVIS:
    """
    Calls the LLM to extract survey-level metadata from the document
    opening (typically the cover page or title page text).

    Returns a SurveySVIS with an empty variables list.
    Variables are added by subsequent calls to extract_variables_from_chunk().

    Raises:
        instructor.exceptions.InstructorRetryException if the LLM fails
        to produce valid output after MAX_RETRIES attempts.
    """
    meta: _SurveyMeta = _create(
        model=MODEL,
        max_completion_tokens=MAX_TOKENS,
        max_retries=MAX_RETRIES,
        messages=[{
            "role": "user",
            "content": SURVEY_METADATA_PROMPT.format(text=opening_text),
        }],
        response_model=_SurveyMeta,
    )

    year = _resolve_year(meta.year, meta.survey_name, source_file)

    return SurveySVIS(
        survey_id=meta.survey_id,
        country_code=meta.country_code,
        year=year,
        survey_name=meta.survey_name,
        study_type=meta.study_type,
        data_collection_mode=meta.data_collection_mode,
        language=meta.language,
        variables=[],
        source_file=source_file,
        source_format=source_format,
        extraction_date=date.today(),
    )


def extract_variables_from_chunk(chunk: DocumentChunk) -> list[SurveyVariable]:
    """
    Calls the LLM to extract all variable information from one
    questionnaire section chunk.

    Returns a list of SurveyVariable objects (may be empty if the chunk
    contains no extractable questions — e.g. a cover image or pure
    instruction text).

    Provenance fields (source_page, module) are stamped after the LLM
    call using data from the chunk, not from the LLM output.
    This prevents the LLM from hallucinating page numbers.

    Raises:
        instructor.exceptions.InstructorRetryException if the LLM fails
        to produce valid output after MAX_RETRIES attempts.
    """
    prompt = VARIABLE_EXTRACTION_PROMPT.format(
        module_name=chunk.module_name,
        chunk_index=chunk.chunk_index,
        text=chunk.text,
    )

    batch: _VariableBatch = _create(
        model=MODEL,
        max_completion_tokens=MAX_TOKENS,
        max_retries=MAX_RETRIES,
        messages=[{"role": "user", "content": prompt}],
        response_model=_VariableBatch,
    )

    # Stamp provenance fields the LLM cannot reliably know
    for var in batch.variables:
        var.source_page = chunk.page_start
        # Preserve the LLM's module assignment if it provided a better one;
        # fall back to the chunk's module name
        if not var.module:
            var.module = chunk.module_name

    return batch.variables
