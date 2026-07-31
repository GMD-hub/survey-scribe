# GMD Survey Parser

Extracts structured variable information from household survey questionnaire PDFs and saves it as a **Survey Variable Information Schema (SVIS)** JSON file. The SVIS output feeds the GMD AI-assisted harmonization pipeline.

If you are new to this repo, read this whole document before running anything.

------------------------------------------------------------------------

## What this pipeline does

```
Questionnaire PDF
      │
      ▼
Docling → Structured Markdown (OCR + table-structure enabled)
      │
      ▼
Section chunking (one chunk per heading/module)
      │
      ├──► LLM call A: survey metadata (country, year, study type, language)
      │
      └──► LLM call B (per chunk): variable extraction → Pydantic validation
                │
                ├── Confidence ≥ 0.7 → accepted
                └── Confidence < 0.7 → flagged for human review
                          │
                          ▼
                    SVIS JSON output (output/{survey_id}_svis.json)
```

The LLM calls go to the World Bank's Azure OpenAI gateway (model: `gpt-4.1-mini`), authenticated with your own Azure AD identity (no shared API key). The pipeline never sends the raw PDF to the model — only the Docling-converted Markdown text, chunked by section.

------------------------------------------------------------------------

## Repository structure

```
survey-scribe/
├── README.md                  ← you are here
├── requirements.txt           ← Python dependencies
├── docling_pipeline.py        ← main orchestrator; run this
│
├── schemas/
│   └── svis.py                ← THE CORE ARTIFACT. Pydantic models
│                                 defining the SVIS output format.
│                                 Read this first.
│
├── extractors/
│   └── docling_pdf.py          ← PDF scan detection, Docling conversion,
│                                  section chunking
│
├── agents/
│   ├── prompts.py              ← ALL LLM prompts live here.
│   │                              This is the main quality lever —
│   │                              when extraction is poor, edit here.
│   └── svis_agent.py           ← LLM calls: Azure auth, instructor client,
│                                  rate-limit retry, metadata/year/language
│                                  post-processing fixes
│
├── tests/
│   ├── test_schema.py          ← run before anything else
│   └── samples/
│       └── surveys/            ← put input questionnaire PDFs here
│                                  (not tracked by git)
│
├── output/                     ← generated SVIS JSON files (not tracked by git)
│
└── docs/
    └── svis_field_guide.md     ← field-by-field reference for the SVIS schema
```

------------------------------------------------------------------------

## Setup

### 1. Get the code

Either clone the repo:

``` powershell
git clone <repo-url>
cd survey-scribe
```

...or, if you received this project as a `.zip` file, extract it and open a terminal in the extracted `survey-scribe` folder.

### 2. Create a virtual environment

``` powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, run once per session:
``` powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 3. Install Python dependencies

``` powershell
python -m pip install -r requirements.txt
```

This installs Docling (PDF → Markdown, OCR, table structure), the Azure OpenAI SDK, `instructor` (structured LLM output), `pydantic`, `tenacity` (retry/backoff), and `lingua-language-detector` (language-detection fallback). See `requirements.txt` for the full list with comments on why each package is needed.

### 4. Configure World Bank Azure OpenAI (mAI) authentication

This pipeline does **not** use a static API key. Authentication is handled by the internal `itsai` package (`itsai.platform.authentication.DesktopToken`), which acquires a token for your own Azure AD identity via MSAL — the same pattern used across World Bank mAI projects.

- `itsai` is a World Bank-internal package, not on public PyPI — make sure it's available in your Python environment (ask your team lead if `pip install -r requirements.txt` doesn't resolve it; it may need to come from an internal package index already configured on your machine).
- The first time the pipeline actually calls the model, MSAL may open an interactive sign-in window (native Windows/broker dialog, sometimes a browser tab). It can appear behind other windows — check your taskbar if the terminal seems to hang after starting a run. After you sign in once, subsequent runs typically reuse a cached/silent token.
- No `.env` file or API key is required for the Azure OpenAI calls themselves.

------------------------------------------------------------------------

## Changing the model, token limits, or other pipeline settings

| Setting | File | Constant |
|---|---|---|
| Model name (e.g. `gpt-4.1-mini`) | `agents/svis_agent.py` | `MODEL` |
| Max output tokens per LLM call | `agents/svis_agent.py` | `MAX_TOKENS` |
| Schema-validation retry attempts | `agents/svis_agent.py` | `MAX_RETRIES` |
| Rate-limit (HTTP 429) retry attempts | `agents/svis_agent.py` | `RATE_LIMIT_MAX_ATTEMPTS` |
| Azure endpoint / API version | `agents/svis_agent.py` | `_AZURE_ENDPOINT`, `_AZURE_API_VERSION` |
| Confidence threshold for `needs_review` | `docling_pipeline.py` | `REVIEW_THRESHOLD` |
| How much text is sampled for metadata extraction | `docling_pipeline.py` | `METADATA_CHAR_LIMIT`, `MAX_CHUNKS_FOR_METADATA`, `MAX_CHARS_PER_CHUNK_FOR_METADATA` |

------------------------------------------------------------------------

## Verify the setup

``` powershell
.venv\Scripts\python.exe -m pytest tests/test_schema.py -v
```

All tests should pass. If they fail, something is wrong with the `pydantic`/schema install — fix this before running the pipeline.

> **Windows gotcha:** always invoke tools as `.venv\Scripts\python.exe -m <tool>` (e.g. `-m pytest`, `-m pip`) rather than calling `.venv\Scripts\pytest.exe` directly or relying on a bare `python`/`pip` on PATH — a different, unrelated global Python install may be found first and won't have any of this repo's dependencies.

------------------------------------------------------------------------

## Where input PDFs go

Put questionnaire PDFs in `tests/samples/surveys/`. This folder is git-ignored (survey PDFs may be restricted data), so it won't exist with content after a fresh clone — create it and add your own PDFs.

The pipeline is designed for digitally-created PDFs (a real text layer). Scanned image-only PDFs are detected and skipped (OCR quality is out of scope).

------------------------------------------------------------------------

## Running the pipeline

### On one PDF

``` powershell
.venv\Scripts\python.exe docling_pipeline.py "tests\samples\surveys\your_file.pdf"
```

Optionally choose a different output folder:

``` powershell
.venv\Scripts\python.exe docling_pipeline.py "tests\samples\surveys\your_file.pdf" --output-dir output
```

Output is written to `output/{survey_id}_svis.json` (default output directory is `output/`). If a JSON file for that same survey already exists, it is replaced.

Expect this to take a few minutes per PDF — Docling's OCR and table-structure models are the slow part, not the LLM calls.

### On multiple PDFs

``` powershell
Get-ChildItem "tests\samples\surveys\*.pdf" | ForEach-Object {
    .venv\Scripts\python.exe docling_pipeline.py $_.FullName
}
```

------------------------------------------------------------------------

## Where things live (quick reference)

| What | Where |
|---|---|
| Main entry point / CLI | `docling_pipeline.py` |
| SVIS schema (Pydantic models) | `schemas/svis.py` (field-by-field docs: `docs/svis_field_guide.md`) |
| PDF → Markdown → chunks | `extractors/docling_pdf.py` |
| LLM prompts | `agents/prompts.py` — **edit this first when extraction quality is poor** |
| LLM client, Azure auth, retries | `agents/svis_agent.py` |
| Input PDFs | `tests/samples/surveys/` |
| Output SVIS JSON | `output/` |
| Schema tests | `tests/test_schema.py` |

------------------------------------------------------------------------

## Improving extraction quality

Almost every quality issue traces back to one of two places:

1. **The Markdown conversion itself** — if Docling garbles a table or misreads a heading, the LLM never sees the correct source text. Inspect `output/*_svis.json` variables with `needs_review: true` and cross-check the `notes` field for hints (e.g. "garbled table", "codes inferred").
2. **The prompts** — `agents/prompts.py` (`SURVEY_METADATA_PROMPT`, `VARIABLE_EXTRACTION_PROMPT`) is the main quality lever. When you change a prompt, add a `# CHANGED [date]: what changed and why` comment above the edit so there's a lightweight audit trail.

Every extracted variable carries `extraction_confidence` and `needs_review` — use these to prioritize manual review instead of reading every variable.

------------------------------------------------------------------------

## Key design decisions (do not change without discussion)

| Decision | Reason |
|---|---|
| Docling for PDF → Markdown conversion | OCR + table-structure recognition handle dense, image-heavy questionnaires better than lighter-weight converters; uses `PyPdfiumDocumentBackend` specifically to avoid a known `docling-parse` crash that silently drops pages on long PDFs |
| `instructor` library for LLM calls | Enforces the Pydantic schema on every response and automatically retries on validation failures — do not replace with raw API calls |
| Explicit rate-limit retry in `agents/svis_agent.py` | `instructor`'s own retries only cover schema-validation failures, not HTTP 429s from the Azure gateway, so a separate `tenacity` backoff wraps every API call |
| `year`/`survey_id`/`language` post-processed after the LLM call | The LLM's own metadata fields proved unreliable (wrong/placeholder years, mismatched IDs, null language) — these are now derived deterministically from the filename/survey name or a language detector instead of trusted as-is |
| Confidence score + `needs_review` per variable | Lets the quality gate flag uncertain extractions without manual inspection of every variable |
| `is_missing` flag on `AnswerCategory` | Non-substantive codes (don't know, refused, not applicable) must be recoded to missing in GMD; flagging them at extraction time prevents downstream errors |
| Scanned PDFs skipped | OCR quality assurance is a separate, complex problem; skipping now keeps scope manageable |

------------------------------------------------------------------------

## Contact

**Project lead:** \[Andres — add contact info\] **Supervision sessions:** weekly (see calendar invite)