# Survey Scribe

Extracts structured variable information from household survey questionnaire PDFs and saves it as a **Survey Variable Information Schema (SVIS)** JSON file. The SVIS output feeds the GMD AI-assisted harmonization pipeline.

> **Engineering status**: Phase 1 provides an installable schema package,
> characterization tests, and a bootstrap CLI. The legacy World Bank pipeline
> remains frozen for compatibility and still requires unavailable internal
> authentication. No license or public release has been approved.

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

The LLM calls go to the World Bank's Azure OpenAI gateway (model configured via `MODEL` in `agents/svis_agent.py` — see the settings table below), authenticated with your own Azure AD identity (no shared API key). The pipeline never sends the raw PDF to the model — only the Docling-converted Markdown text, chunked by section.

------------------------------------------------------------------------

## Repository structure

```
survey-scribe/
├── README.md                  ← you are here
├── pyproject.toml             ← Authoritative package and dependency metadata
├── uv.lock                    ← Reproducible dependency lock
├── src/survey_scribe/         ← Installable package and canonical SVIS models
├── requirements.txt           ← Deprecated legacy dependency list
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

### 2. Install the locked engineering environment

```powershell
uv sync --locked --python 3.11
```

This creates `.venv`, installs the package in editable mode, and installs the
locked development tools. `requirements.txt` is retained only to document the
pre-package proof of concept and is no longer an installation authority.

Verify the package bootstrap with `uv run survey-scribe --help` and
`uv run pytest tests/characterization tests/test_schema.py`.

### 4. Configure World Bank Azure OpenAI (mAI) authentication

The frozen legacy pipeline does **not** use a static API key. Authentication is
handled by the internal `itsai` package. `itsai` is deliberately not a public
package dependency and no client or credential provider is loaded by package
import or CLI help.

- `itsai` is a World Bank-internal package and is not available from public PyPI. The legacy extraction command is unavailable in a public clean install until its later compatibility shim is completed.
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

## Next steps

This project was built during an internship and handed off before every idea below could be implemented. None of these are required for the pipeline to work — they are recommendations for what to tackle next, roughly in priority order.

### 1. An independent review agent (highest priority)

The pipeline currently has no automated way to check whether its own output is accurate — quality checking so far has been manual (see `tests/samples/quality_review.md` for the methodology used on one file). The idea: a second script that

  - loads a `*_svis.json` output file,
  - loads the Markdown/source text Docling produced for that same PDF (currently discarded after chunking — you'd need to persist it, e.g. write it to `output/{survey_id}.md` in `docling_pipeline.py`, so the reviewer isn't re-running slow Docling conversion),
  - and sends each variable + its source section text to an LLM call, asking it to verify the extraction against the source and return a verdict (`correct` / `partial` / `wrong`) with specific issues.

**Important: call this through a different model than `agents/svis_agent.py` uses** (e.g. a Claude or Gemini model available on the same mAI gateway). Using the same model to check its own work will tend to rubber-stamp its own systematic errors. Give this reviewer its own client/config, entirely separate from `svis_agent.py`, so changing the extraction model can never silently change what reviews it. Known failure modes worth specifically prompting the reviewer to check for (found via manual review): fabricated/hallucinated categories, sentinel codes (don't know/refused) not flagged `is_missing`, `question_text`/`categories` mismatched with a neighboring question, and `raw_name` copied from the questionnaire's printed code instead of being descriptive.

Scope the first version to just the variables already flagged `needs_review: true` or with low `extraction_confidence` — reviewing everything is more thorough but much slower and more expensive.

### 2. An auto-fix / improver agent

Once the review agent above produces verdicts, a natural follow-up is a script that takes `wrong`/`partial` verdicts plus their suggested fixes and re-generates just those variables (not the whole chunk) — then writes a corrected JSON. Keep a human-in-the-loop step here (e.g. write a diff/summary of what changed rather than silently overwriting) until this has been validated against a hand-reviewed file like the ALB one.

### 3. Known model-quality tradeoff (needs investigation before switching models)

An empirical comparison between `gpt-4.1-mini` and `gpt-4.1` on the same PDF (Burkina Faso EBCVM 2009-10) found that the bigger model, while more accurate on individual fields, **silently dropped 50-90% of variables in the largest, most repetitive chunks** (e.g. a governance module with many similar Likert-scale sub-questions went from 37 extracted variables down to 14). It appears to summarize/consolidate repeated patterns rather than exhaustively enumerating every one, whereas `gpt-4.1-mini` extracted every instance. If you change `MODEL` in `agents/svis_agent.py`, re-run this kind of per-module variable-count comparison on a densely-repetitive test PDF before trusting the new output — don't assume a "smarter" model is more complete. Splitting the largest chunks into smaller pieces, or adding an explicit "do not consolidate repeated rows — extract every one separately" instruction to `VARIABLE_EXTRACTION_PROMPT`, are both worth trying.

### 4. Page tracking

`SurveyVariable.source_page` is currently always stamped as the chunk's `page_start`, which `chunk_markdown()` in `extractors/docling_pdf.py` always sets to `0` (see the comment `# page tracking: future improvement` in that function) — real page numbers aren't tracked through the Docling → chunk pipeline yet. Worth fixing so `source_page` is actually useful for manual review.

### 5. Other handoff loose ends

  - **Fill in the Contact section below** — it still has a placeholder.
  - Consider adding a GitHub Actions workflow to run `pytest tests/test_schema.py` on every push/PR, so schema regressions are caught automatically instead of relying on someone remembering to run it.
  - `tests/samples/quality_review.md` documents the manual review methodology and the prompt fixes it led to — worth repeating on a new output file periodically to catch prompt/quality regressions, until the review agent above exists to automate it.

------------------------------------------------------------------------

## Contact

**Project lead:** \[Andres — add contact info\] **Supervision sessions:** weekly (see calendar invite)
