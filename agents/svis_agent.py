"""
SVIS Extraction Agents
=======================
LLM-powered extraction of survey metadata and variable information.

Uses the `instructor` library, which wraps the Anthropic SDK and:
  1. Enforces the Pydantic schema on LLM output
  2. Automatically sends validation errors back to the LLM and retries
  3. Raises an exception after max_retries failed attempts

This means the pipeline never receives malformed output silently.
Either it gets a valid Pydantic object, or it gets an exception that
can be caught, logged, and routed to the human review queue.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Optional

import anthropic
import instructor
from dotenv import load_dotenv
from pydantic import BaseModel

from agents.prompts import SURVEY_METADATA_PROMPT, VARIABLE_EXTRACTION_PROMPT
from extractors.pdf import DocumentChunk
from schemas.svis import StudyType, SurveySVIS, SurveyVariable

load_dotenv()   # reads ANTHROPIC_API_KEY from .env

# ── Client ────────────────────────────────────────────────────────────────────

_client = instructor.from_anthropic(
    anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
)

MODEL      = "claude-sonnet-4-6"
MAX_TOKENS = 4096
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
    meta: _SurveyMeta = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
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

    batch: _VariableBatch = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
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
