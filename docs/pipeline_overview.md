# Pipeline Overview

This document describes every stage of the surveyscribe pipeline in detail and
explains the design decisions behind each stage. It is the technical reference
for anyone working on or extending the project.

Read `schemas/svis.py` and `docs/svis_field_guide.md` before reading this
document.

> **Copilot tip:** You can ask GitHub Copilot Chat questions about this document
> at any time. Open Copilot Chat and use `@workspace` to ask about the project
> as a whole. For example:
> `@workspace How does the chunking step in pipeline.py relate to the
> extraction calls in svis_agent.py?`

---

## What the pipeline does

surveyscribe reads a household survey questionnaire PDF and produces a structured
JSON file describing every variable in the questionnaire. That JSON file follows
the Survey Variable Information Schema (SVIS) defined in `schemas/svis.py`.

The pipeline has nine phases:

```
Phase 1   Input documents
Phase 2   Pre-processing: PDF type detection
Phase 3   Conversion: PDF to Markdown
Phase 4   Chunking: split into sections
Phase 5   LLM extraction (two parallel calls)
Phase 6   Schema validation
Phase 7   Quality gate: confidence scoring
Phase 8   Human review (flagged items only)
Phase 9   Output: SVIS JSON file
```

---

## Phase 1: Input

**File:** `pipeline.py`

The pipeline accepts a single PDF file as input. PDFs are the primary format
for the current PoC scope. Excel codebooks and CSV files are out of scope for
this phase.

```bash
python pipeline.py path/to/questionnaire.pdf
python pipeline.py path/to/questionnaire.pdf --output-dir ./output
```

---

## Phase 2: Pre-processing — PDF type detection

**File:** `extractors/pdf.py`, function `is_scanned_pdf()`

Not all PDFs have readable text. The pipeline detects which type it has by reading
the first five pages using PyMuPDF and checking whether any page yields more than
50 characters of text. If none do, the document is treated as a scanned image and
the pipeline stops, logging the filename for manual follow-up.

**Why PyMuPDF here but not for conversion:** PyMuPDF is fast and lightweight for
a simple text-presence check. The full MarkItDown conversion would be wasteful if
the PDF turns out to be a scan.

**Out of scope for PoC:** OCR for scanned PDFs. Scanned PDFs are flagged and
skipped.

---

## Phase 3: Conversion — PDF to Markdown

**File:** `extractors/pdf.py`, function `pdf_to_markdown()`
**Library:** `markitdown`

Digital-native PDFs are converted to Markdown using the MarkItDown library.

**Why Markdown and not raw text?**

Raw text extraction from PyMuPDF returns positional text that loses structure.
A table of answer codes in a raw extraction looks like this:

```
1 Male 2 Female 9 Not stated
```

The same table after MarkItDown conversion looks like this:

```markdown
| Code | Label      |
|------|------------|
| 1    | Male       |
| 2    | Female     |
| 9    | Not stated |
```

The second version is what the LLM receives. Tables of answer codes are the most
critical piece of information for mapping categorical variables, and Markdown
tables are something the LLM handles reliably. MarkItDown also preserves section
headings as `##` headings, which drives the chunking in Phase 4.

**Limitation:** MarkItDown quality varies depending on how the PDF was created.
Questionnaires with complex multi-column layouts may not convert cleanly. The
intern's Subtask 3 evaluation is designed to identify these cases.

---

## Phase 4: Chunking — split into sections

**File:** `extractors/pdf.py`, function `chunk_markdown()`

The Markdown document is split into one chunk per section or module by detecting
Markdown headings (`#`, `##`, `###`). Each chunk is a `DocumentChunk` object:

| Field | Description |
|---|---|
| `module_name` | The heading text that started this chunk |
| `text` | The full Markdown text of this section |
| `page_start` | PDF page number (set to 0 in current version) |
| `chunk_index` | Position of this chunk in the document |

**Why chunk at all?** A full questionnaire can exceed 20,000 tokens. Chunking by
section means each LLM call receives a semantically coherent piece of the
questionnaire, and the module name travels with the chunk and becomes the `module`
field in the extracted variables.

**Fallback:** If no headings are detected, the whole document is returned as one
chunk named `full_document`.

---

## Phase 5: LLM extraction — two parallel calls

**File:** `agents/svis_agent.py`
**Prompts:** `agents/prompts.py`
**Library:** `instructor`, `anthropic`

### Call A: Survey metadata

One call per survey document. The first chunk (cover page) is sent with
`SURVEY_METADATA_PROMPT`. The LLM extracts country code, year, survey name,
study type, data collection mode, and language.

### Call B: Variable extraction

One call per chunk. Each chunk is sent with `VARIABLE_EXTRACTION_PROMPT`. The
LLM returns a list of `SurveyVariable` objects. The full schema definition is
embedded in the prompt.

**Why two separate calls?** Mixing metadata extraction and variable extraction
in one prompt produces worse results for both and makes the prompts harder to
read and improve.

**The `instructor` library** wraps the Anthropic API and validates the returned
output against the Pydantic schema automatically. If the output does not match
the schema, `instructor` sends the validation error back to the LLM and retries,
up to `MAX_RETRIES` times (currently 3). If all retries fail, an exception is
raised.

---

## Phase 6: Schema validation

**Library:** `pydantic`, `instructor`

Validation happens automatically as part of Phase 5. Key rules enforced:

- `extraction_confidence` must be between 0.0 and 1.0
- `data_type` must be one of the six allowed values in `DataType`
- `unit_of_analysis` must be one of `individual`, `household`, or `other`
- Every `AnswerCategory` must have both a `code` and a `label`

---

## Phase 7: Quality gate — confidence scoring

**File:** `pipeline.py`
**Threshold:** `REVIEW_THRESHOLD = 0.70`

Variables with `extraction_confidence` below 0.70 have `needs_review` set to
`True`. Variables are also flagged if critical fields are null: `question_text`,
`data_type`, or `categories` on a categorical variable.

The threshold is a constant at the top of `pipeline.py` and can be adjusted.

---

## Phase 8: Human review

Not yet implemented as a UI. In the current PoC, human review means opening the
JSON output file and manually correcting variables with `needs_review = true`,
then setting the flag to `false`.

The `notes` field on each variable is the LLM's explanation of its uncertainty.
Reviewers should read this first before looking at the source PDF.

A dedicated review interface is planned for a later phase.

---

## Phase 9: Output

**File:** `pipeline.py`

The completed `SurveySVIS` object is serialized to JSON and written to `output/`:

```
output/{survey_id}_svis.json
```

This file is the deliverable of the extraction pipeline and the input to the
next stage of the GMD harmonization pipeline.

---

## Key design decisions

### Why MarkItDown over raw PyMuPDF text extraction

PyMuPDF extracts raw positional text. Tables of answer codes become garbled
single lines. MarkItDown converts the same PDF to structured Markdown where tables
are preserved as Markdown tables. This single decision has the largest impact on
extraction accuracy.

### Why `instructor` over raw API calls

Without `instructor`, the pipeline would need to parse and validate JSON from raw
LLM text output, handle malformed responses, and write retry logic manually.
`instructor` handles all of this automatically.

### Why two separate LLM calls instead of one

Survey metadata extraction and variable extraction are different cognitive tasks.
Mixing them in one prompt produces worse results for both and makes each prompt
harder to improve independently.

### Why the confidence score is self-reported by the LLM

Having the LLM score its own confidence is imperfect but practical. It catches
the cases that matter most: garbled tables, unclear question text, ambiguous data
types. The threshold of 0.70 is a starting point, not a fixed value, and should
be adjusted based on empirical evaluation.

### Why scanned PDFs are out of scope

OCR introduces significant additional complexity and potential licensing costs.
Solving the PoC for digital PDFs first validates the architecture before adding
this complexity.

---

## Extending the pipeline

**Adding support for Excel codebooks:**
Create a new extractor in `extractors/` (for example, `xlsx.py`). MarkItDown
already supports Excel files, so the conversion step may be as simple as calling
`MarkItDown().convert(xlsx_path)`.

**Improving chunking for headingless documents:**
Some questionnaires use visual separators that MarkItDown does not convert to
headings. A preprocessing LLM call could identify section boundaries before
chunking.

**Adding a review UI:**
Replace JSON file review in Phase 8 with a lightweight web interface. R Shiny
or a simple Python Flask app are both viable options.

> **Copilot tip:** If you are planning any of these extensions, open Copilot Chat
> and ask: `@workspace I want to add support for Excel codebook files to this
> pipeline. Based on the existing code structure, where would I add this and
> what would it look like?`