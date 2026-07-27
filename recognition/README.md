# recognition — PDF document metadata extraction

Self-contained sub-project inside `survey-scribe`. Unlike the root
pipeline (`pipeline.py` / `fallback.py`), which extracts *survey
variables* into the SVIS schema, this folder extracts general
**document structure metadata** from a PDF: text (pages, heading
hierarchy, language), tables (page, shape, location), and images
(page, format, file path). It is organized like a small repo of its
own — its own `schemas/`, `extractors/`, `agents/`, `tests/`, and
`output/` — so it can grow independently of the SVIS pipeline.

Current status: **Text Structure Agent + Language Agent + Image Agent + Table Agent.**
All four planned agents are built.

## Why a separate sub-project

- Different output schema (document structure, not survey variables).
- Different consumers downstream — this is not part of the
  harmonization pipeline.
- Lets each "agent" (text, language, table, image) be developed and
  tested in isolation, then merged by an orchestrator, mirroring the
  workflow design discussed for this feature.

## Environment

Reuses the repo root's `.venv` (do not create a separate virtual
environment for this folder). Depends on the repo root's existing
`docling` dependency plus one new one added for this sub-project:
`lingua-language-detector` (import name `lingua`), used by the
Language Agent. Both are listed in `requirements.txt` at repo root.

## Structure

```
recognition/
├── README.md                    ← you are here
├── schemas/
│   ├── text_structure.py        ← TextBlock / DocumentTextStructure Pydantic models
│   ├── image_structure.py       ← ImageBlock / DocumentImageStructure Pydantic models
│   ├── table_structure.py       ← TableCellBlock / TableBlock / DocumentTableStructure Pydantic models
│   └── document_metadata.py     ← DocumentMetadata -- merges the three above into one JSON
├── extractors/
│   └── docling_convert.py       ← PDF -> DoclingDocument (reuses the
│                                   PyPdfiumDocumentBackend crash fix from
│                                   fallback.py — see repo memory notes)
├── agents/
│   ├── text_agent.py            ← Text Structure Agent (deterministic, no LLM)
│   ├── language_agent.py        ← Language Agent (deterministic, no LLM;
│                                   fills in TextBlock.language/language_confidence)
│   ├── image_agent.py           ← Image Agent (deterministic, no LLM;
│                                   saves each embedded picture to disk)
│   └── table_agent.py           ← Table Agent (deterministic, no LLM;
│                                   copies each table's full cell grid)
├── pipeline.py                  ← CLI entry point for the text + language + image + table stages
├── tests/
│   ├── test_text_agent.py       ← unit tests for heading-hierarchy logic
│   ├── test_language_agent.py   ← unit tests for language detection
│   ├── test_image_agent.py      ← unit tests for image extraction/saving
│   └── test_table_agent.py      ← unit tests for table grid/merged-cell logic
└── output/                      ← generated JSON + images/ (not tracked by git)
```

## Important: import isolation

`recognition/` intentionally mirrors the root repo's folder names
(`schemas/`, `agents/`, `extractors/`) so it reads like a repo within
a repo. This means **`import schemas...` inside `recognition/` and
`import schemas...` at the repo root are two different packages that
happen to share a name.** To avoid collisions:

- Always run this sub-project as a script from its own file:
  `python recognition/pipeline.py <pdf>` (this puts `recognition/` at
  the front of `sys.path`, so its local `schemas`/`agents`/`extractors`
  resolve correctly).
- Do not `import` both the root pipeline and `recognition/pipeline.py`
  in the same Python process — the two `schemas` packages would
  collide in `sys.modules`. Run them as separate processes instead.

## Running the text stage

```bash
.venv\Scripts\python.exe recognition\pipeline.py tests\samples\surveys\final_interview_HBS_2014.pdf
```

Writes `recognition/output/{pdf_stem}_text_structure.json` containing
one `TextBlock` per text unit in the document (paragraphs, list items,
headings, captions, footnotes, ...), each with:

- `page` — page number (from Docling provenance)
- `label` — Docling's item label (`text`, `section_header`, `list_item`, ...)
- `heading_level` — heading depth if this block is a heading, else `null`
- `parent_path` — text of every currently-open ancestor heading, shallowest first
- `text` / `char_count`
- `language` / `language_confidence` — ISO 639-1 code (e.g. "en", "fr")
  and a 0.0-1.0 confidence score, filled in by the Language Agent.
  `null` for blocks shorter than 12 characters (too short for reliable
  statistical detection) or where no language could be confidently
  identified.

Tables are a separate Docling item type and are handled by the Table
Agent (see below) rather than appearing in the text-structure output.

## Image output

The same `pipeline.py` run also writes
`recognition/output/{pdf_stem}_image_structure.json`, containing one
`ImageBlock` per embedded picture/figure/chart, each with:

- `page` — page number (from Docling provenance)
- `format` — image MIME type (e.g. "image/png"); "unknown" if Docling
  could not render this image
- `file_path` — path of the saved PNG, relative to the output
  directory (`images/{pdf_stem}_img{N}.png`); `null` if the image
  could not be rendered
- `width` / `height` — pixel dimensions of the saved image
- `caption` — caption text if Docling detected one, else `null`

## Table output

The same `pipeline.py` run also writes
`recognition/output/{pdf_stem}_table_structure.json`, containing one
`TableBlock` per table, each with:

- `page` — page number (from Docling provenance)
- `num_rows` / `num_cols` — table dimensions, as resolved by Docling's
  table-structure model
- `cells` — the full row x column grid of cells (outer list = rows,
  inner list = columns), each with `text`, `row_span`/`col_span`, and
  `column_header`/`row_header` flags. Merged cells appear at every grid
  position they span (matching how the table visually reads), rather
  than being collapsed into one entry -- this is the most
  structure-preserving representation available directly from Docling,
  as opposed to flattening the table to a single Markdown/HTML string.
- `caption` — caption text if Docling detected one, else `null`

## Combined output

`pipeline.py` writes one merged file per PDF:
`recognition/output/{pdf_stem}_metadata.json`, containing the exact
output of all three agents nested under `text`, `images`, and `tables`
(see `schemas/document_metadata.py`), plus top-level `source_file`,
`page_count`, `extraction_date`, and a convenience copy of
`primary_language`. Nothing is recomputed or reshaped for this file --
it's a pure merge of the three per-agent structures already described
above.

The three per-agent files (`{pdf_stem}_text_structure.json`,
`{pdf_stem}_image_structure.json`, `{pdf_stem}_table_structure.json`)
are only intermediate artifacts: `pipeline.py` writes them first, then
deletes them once `{pdf_stem}_metadata.json` has been written
successfully, so `output/` doesn't accumulate duplicate copies of the
same data. The saved image files under `output/images/` are **not**
deleted -- only the intermediate JSON files are.


## Design notes

- **No LLM in either agent.** Docling already reports page number and
  heading label/level per text item; building the parent heading path
  from that is a deterministic tree walk, not a reasoning task. Language
  identification is a closed statistical classification task (the
  `lingua` library, n-gram based), not something requiring reasoning.
  Keeping both LLM-free makes them fast, free, and fully
  deterministic/testable — no API key needed for this sub-project at all
  so far.
- **Language Agent design:** built as a separate agent/function from the
  Text Structure Agent, operating on the same `TextBlock` list produced
  by it (mutates `language`/`language_confidence` in place, keyed by
  `block_id`). This keeps the two concerns independently testable and
  swappable (e.g. replacing `lingua` with another detector later) without
  touching heading-hierarchy logic.
- **Image Agent design:** uses Docling's own rendered image for each
  `PictureItem` (enabled via `generate_picture_images=True` in
  `docling_convert.py`) rather than re-extracting the original embedded
  image bytes via PyMuPDF. This keeps the sub-project on a single
  extraction library and a single, consistent image format (PNG) across
  every source PDF, at the cost of not preserving the original embedded
  format (e.g. a source JPEG is saved as a re-rendered PNG). Images
  Docling could not render are still recorded (page, caption) with
  `file_path=None` rather than silently dropped.
- **Table Agent design:** copies Docling's `TableData.grid` (a full
  row x column matrix of resolved `TableCell` objects) directly into
  `TableBlock.cells`, rather than flattening to Markdown/HTML. This
  preserves merged-cell spans and header flags exactly as Docling
  resolved them, at the cost of a more verbose JSON representation than
  a single Markdown table string.
- **Known limitation (inherited from Docling):** dense multi-column
  "roster grid" tables in these questionnaires are not reconstructed
  well by Docling's table model; this can occasionally cause table
  content to leak into the text stream as flattened paragraphs. See
  repo memory notes on Docling table fidelity.
- **Known limitation (inherited from Docling):** the default
  `docling-parse` PDF backend has a silent `std::bad_alloc` crash on
  longer/denser PDFs that drops all subsequent pages with no exception.
  `extractors/docling_convert.py` avoids this by using
  `PyPdfiumDocumentBackend`, exactly as `fallback.py` does at the repo
  root.
