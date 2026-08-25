# surveyscribe — GitHub Copilot Instructions

These instructions apply to every Copilot Chat session in this repository.
Read them before answering any question about the project.

---

## What this project is

surveyscribe is a Python pipeline that reads household survey questionnaire PDFs
and extracts structured information about every variable in the questionnaire.
The output is a JSON file called a SVIS (Survey Variable Information Schema).

This pipeline is the first stage of the World Bank's GMD (Global Monitoring
Database) AI-assisted harmonization system. The SVIS output feeds a downstream
pipeline that proposes how each survey variable should be mapped to the GMD
standard format used for global poverty measurement.

---

## Who you are helping

The person using this repo is a graduate intern with limited Python experience.
They are technically inclined but may not know standard library patterns, common
error types, or Python project conventions. When explaining things:

- Use plain language first, technical terms second
- Always show a concrete example alongside any explanation
- If they paste an error, explain what it means before suggesting a fix
- Keep explanations short unless they ask for more detail
- Do not assume they know what a virtual environment, a Pydantic model, or a
  decorator is — explain these if they come up

---

## Key files and what they do

| File | Role |
|---|---|
| `pipeline.py` | Main entry point. Run this on a PDF to produce a SVIS JSON file. |
| `schemas/svis.py` | THE central artifact. Defines the Pydantic models for all SVIS output. Read this before anything else. |
| `extractors/pdf.py` | Three functions: scan detection, MarkItDown PDF-to-Markdown conversion, and section chunking. |
| `agents/prompts.py` | All LLM prompts. The main quality lever — when extraction is poor, the fix is almost always here. |
| `agents/svis_agent.py` | LLM calls using the `instructor` library and Anthropic API. |
| `tests/test_schema.py` | Run with `pytest tests/test_schema.py -v`. Must pass before any other work. |
| `docs/svis_field_guide.md` | Plain-language reference for every field in the SVIS schema. |
| `docs/pipeline_overview.md` | Full explanation of all nine pipeline phases and the design decisions behind them. |

---

## The SVIS schema — key concepts

The schema has two levels:

**`SurveySVIS`** is the top-level container. One per survey. Has survey-level
fields (country, year, survey name, study type) and a list of `SurveyVariable`
records.

**`SurveyVariable`** is the core unit. One per extractable question. Key fields:

- `raw_name`: the variable name as it appears in the raw data file
- `question_text`: the full question text from the questionnaire
- `data_type`: one of `numeric`, `categorical_single`, `categorical_multi`,
  `text`, `date`, `other`
- `categories`: for categorical variables — list of `AnswerCategory` objects,
  each with `code`, `label`, and `is_missing`
- `numeric_range`: for numeric variables — `min_value`, `max_value`, `notes`
- `universe`: plain-language description of who is asked the question
- `unit_of_analysis`: `individual` or `household`
- `extraction_confidence`: float 0.0-1.0 — LLM self-assessment
- `needs_review`: True if confidence below 0.7 or critical fields are null

The `is_missing` flag on `AnswerCategory` is critical. Codes meaning "don't know",
"refused", or "not applicable" must have `is_missing = True` so they are recoded
to missing in GMD output rather than treated as real data values.

---

## How the pipeline works (brief)

1. Check if PDF is scanned (skip if yes)
2. Convert PDF to Markdown using MarkItDown (preserves tables and headings)
3. Split Markdown into one chunk per section (detected by ## headings)
4. LLM call A: extract survey metadata from the first chunk
5. LLM call B (per chunk): extract all variables using instructor + Anthropic API
6. Pydantic validates the output; instructor retries up to 3 times if invalid
7. Variables below 0.7 confidence are flagged for human review
8. Output saved as output/{survey_id}_svis.json

---

## Key constraints — important

- The intern should only edit `agents/prompts.py` unless told otherwise
- `schemas/svis.py`, `extractors/pdf.py`, `agents/svis_agent.py`, and
  `pipeline.py` are fixed for this phase of the project
- The API key is in `.env` and must never be committed to GitHub
- Test PDFs go in `tests/samples/` which is gitignored

---

## Common tasks the intern will ask about

Running the pipeline:
  python pipeline.py tests/samples/filename.pdf

Running the tests:
  pytest tests/test_schema.py -v

Inspecting output:
  python inspect_output.py

Activating the virtual environment:
  source .venv/bin/activate        (Mac/Linux)
  .venv\Scripts\activate           (Windows)

---

## Prompt improvement guidelines

When helping improve prompts in `agents/prompts.py`:

- Be specific, not general. "Mark is_missing=true for codes labelled
  'don't know', 'refused', or 'not applicable'" is better than
  "handle missing values carefully"
- Add examples directly in the prompt text for any judgment call
- Each change should address one specific error type observed in the output
- Always add a comment above any change: # CHANGED [date]: reason
- Do not delete original instructions — comment them out instead
