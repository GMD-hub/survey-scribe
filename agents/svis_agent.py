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

from datetime import date
from typing import Optional

import instructor
from itsai.platform.authentication import DesktopToken
from openai import AzureOpenAI
from pydantic import BaseModel

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
    meta: _SurveyMeta = _client.chat.completions.create(
        model=MODEL,
        max_completion_tokens=MAX_TOKENS,
        max_retries=MAX_RETRIES,
        messages=[{
            "role": "user",
            "content": SURVEY_METADATA_PROMPT.format(text=opening_text),
        }],
        response_model=_SurveyMeta,
    )

    return SurveySVIS(
        survey_id=meta.survey_id,
        country_code=meta.country_code,
        year=meta.year,
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

    batch: _VariableBatch = _client.chat.completions.create(
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
