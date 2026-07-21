# GMD Survey Parser

Extracts structured variable information from household survey questionnaire PDFs and saves it as a **Survey Variable Information Schema (SVIS)** JSON file. The SVIS output feeds the GMD AI-assisted harmonization pipeline.

------------------------------------------------------------------------

## What this pipeline does

```         
Questionnaire PDF
      │
      ▼
MarkItDown → Structured Markdown
      │
      ▼
Section chunking (one chunk per module)
      │
      ├──► LLM call A: survey metadata (country, year, study type)
      │
      └──► LLM call B (per chunk): variable extraction → Pydantic validation
                │
                ├── Confidence ≥ 0.7 → accepted
                └── Confidence < 0.7 → flagged for human review
                          │
                          ▼
                    SVIS JSON output
```

See `docs/pipeline_overview.md` for a detailed description of every stage.

------------------------------------------------------------------------

## Repository structure

```         
gmd-survey-parser/
├── README.md                  ← you are here
├── .env.example               ← copy to .env and add your API key
├── requirements.txt
│
├── schemas/
│   └── svis.py                ← THE CORE ARTIFACT. Pydantic models
│                                 defining the SVIS output format.
│                                 Read this first.
│
├── extractors/
│   └── pdf.py                 ← PDF scan detection, MarkItDown conversion,
│                                 section chunking
│
├── agents/
│   ├── prompts.py             ← ALL LLM prompts live here.
│   │                            This is the main quality lever —
│   │                            when extraction is poor, edit here.
│   └── svis_agent.py          ← LLM calls using instructor + anthropic
│
├── pipeline.py                ← main orchestrator; run this
│
├── tests/
│   ├── test_schema.py         ← run before anything else
│   └── samples/               ← put test PDFs here (not tracked by git)
│
├── output/                    ← generated SVIS JSON files (not tracked by git)
│
└── docs/
    ├── pipeline_overview.md   ← full pipeline documentation
    └── svis_field_guide.md    ← field-by-field reference for the SVIS schema
```

------------------------------------------------------------------------

## Setup

### 1. Clone the repo and create a virtual environment

``` bash
git clone <repo-url>
cd gmd-survey-parser
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

``` bash
pip install -r requirements.txt
```

### 3. Configure your API key

``` bash
cp .env.example .env
# Open .env and add your Anthropic API key
```

------------------------------------------------------------------------

## Intern starting sequence

Follow these steps **in order**. Each step verifies the previous one before adding more complexity. Do not skip ahead.

### Step 1 — Verify the schema works

``` bash
pytest tests/test_schema.py -v
```

All tests should pass. If any fail, the Pydantic installation has a problem. Fix this before anything else. Read `schemas/svis.py` while you wait — understanding the schema is more important than understanding the pipeline.

### Step 2 — Get a real questionnaire PDF

Add a questionnaire PDF to `tests/samples/`. Use any real GMD survey questionnaire you have access to. The pipeline is designed for digitally-created PDFs (not scans). If you are unsure what you have, Step 3 will tell you.

### Step 3 — Test MarkItDown on the PDF

``` python
from extractors.pdf import pdf_to_markdown, is_scanned_pdf
from pathlib import Path

pdf = Path("tests/samples/your_file.pdf")

print("Is scanned:", is_scanned_pdf(pdf))

md = pdf_to_markdown(pdf)
print(md[:3000])          # inspect the first 3000 characters
```

**What to look for in the output:** - Section headings preserved as `##` or `###` - Answer option tables preserved as Markdown tables (columns of codes and labels) - Question numbering visible

If the output is garbled or tables are broken, note which sections are affected. This tells you where the LLM extraction will be less reliable.

### Step 4 — Test section chunking

``` python
from extractors.pdf import process_pdf
from pathlib import Path

is_scanned, chunks = process_pdf(Path("tests/samples/your_file.pdf"))

for c in chunks:
    print(f"[{c.chunk_index}] {c.module_name[:60]}  ({len(c.text)} chars)")
```

Check: are the chunks meaningful sections, or are they random splits? If no headings were detected, all content will be one large chunk — add a note.

### Step 5 — Run the full pipeline

``` bash
python pipeline.py tests/samples/your_file.pdf
```

Inspect the output JSON in `output/`. Check: - Is the survey metadata (country, year, survey name) correct? - Did the variable names extract correctly? - Are answer codes and labels present for categorical variables? - Which variables have `needs_review: true`? Why?

### Step 6 — Improve the prompts

Almost certainly, the first run will have errors. Open `agents/prompts.py` and edit `VARIABLE_EXTRACTION_PROMPT`. Run again. Compare outputs.

Prompt improvement is the main quality lever for this pipeline. Document what you changed and why in a `CHANGELOG.md` file.

------------------------------------------------------------------------

## Running on multiple PDFs

``` bash
for f in tests/samples/*.pdf; do
    python pipeline.py "$f"
done
```

------------------------------------------------------------------------

## Key design decisions (do not change without discussion)

| Decision | Reason |
|------------------------------------|------------------------------------|
| MarkItDown for conversion, not raw PyMuPDF | MarkItDown preserves tables and headings, which are critical for extracting answer codes from categorical questions |
| `instructor` library for LLM calls | Handles automatic schema validation and retries; do not replace with raw API calls |
| Confidence score per variable | Lets the quality gate identify uncertain extractions without manual inspection of every variable |
| `is_missing` flag on AnswerCategory | Non-substantive codes (don't know, refused) must be recoded to missing in GMD; flagging them at extraction time prevents errors downstream |
| Scanned PDFs skipped in PoC | OCR is a separate, complex problem; skipping now keeps scope manageable |

------------------------------------------------------------------------

## Contact

**Project lead:** \[Andres — add contact info\] **Supervision sessions:** weekly (see calendar invite)