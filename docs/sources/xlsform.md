# XLSForm

XLSForm is a core source format. Survey Scribe tests the `XLSForm 1.3 core`
profile with ODK-compatible `.xlsx` workbook structure and `openpyxl 3.1.5`.
The support-matrix version is `1.0`.

The package parses an XLSForm into a typed `SurveySVIS` without a model call.
Workbook names, labels, category codes, relevance, and retained logic are
authoritative. A model provider cannot replace these values.

## Supported sheets

| Sheet | Support |
| --- | --- |
| `survey` | Required. Rows remain in source order. |
| `choices` | Optional. `list_name`, `name`, and multilingual labels are retained. |
| `settings` | Optional, with zero or one data row. Metadata fields are retained. |
| External CSV | Supported only for explicitly listed, confined `SourceBundle` companions. |

The parser matches sheet and column names without case sensitivity. It uses
`settings.default_language` to select `label::<language>` when present, then
falls back to `label` and the native item name.

## Question Types

| SVIS type | XLSForm types |
| --- | --- |
| `numeric` | `integer`, `decimal`, `range` |
| `categorical_single` | `select_one`, `select_one_from_file` |
| `categorical_multi` | `select_multiple`, `select_multiple_from_file` |
| `text` | `text` |
| `date` | `date`, `dateTime`, `time`, `start`, `end`, `today` |
| `other` | `acknowledge`, `audio`, `barcode`, `calculate`, `file`, `geopoint`, `geoshape`, `geotrace`, `hidden`, `image`, `username`, `video` |

`note` rows are retained as source records but do not become SVIS variables.
Unknown question types become `other`, require review, and produce
`XLSFORM_TYPE_UNSUPPORTED`.

## Retained Semantics

- `name` is the authoritative `raw_name`.
- Selected multilingual text is both the SVIS label and question text.
- Internal and external choice rows become ordered `AnswerCategory` values.
- `form_id`, `form_title`, `country_code`, `year`, `default_language`, and
  `data_collection_mode` populate survey metadata when present.
- `relevant` and `bind::relevant` remain exact in `skip_condition_raw` and in
  native routing evidence.
- `constraint`, `bind::constraint`, `calculation`, `bind::calculate`,
  `choice_filter`, and `repeat_count` remain exact in source records and the
  variable notes.
- Groups and repeats become strict logical containment. A closing marker must
  match the currently open container.
- Repeats remain one logical template. They are not expanded into instances.

Reference comparisons, `selected()`, and Boolean `and`, `or`, and `not` have
typed routing projections. Other functions and arithmetic stay as exact native
expressions with an opaque projection.

## Diagnostics

| Code | Meaning |
| --- | --- |
| `XLSFORM_CHOICE_LIST_MISSING` | A select question names no matching internal choice list. |
| `XLSFORM_TYPE_UNSUPPORTED` | A survey row uses an unsupported question type. |
| `XLSFORM_FUNCTION_UNSUPPORTED` | Retained logic calls a function outside `selected()`, `not()`, `true()`, and `false()`. |
| `XLSFORM_EXPRESSION_UNSUPPORTED` | Retained logic contains arithmetic that is not projected into typed routing. |
| `XLSFORM_REFERENCE_UNRESOLVED` | Retained logic refers to an unknown survey item name. |
| `XLSFORM_FEATURE_UNSUPPORTED` | The workbook uses `trigger`, `xml-external`, or search appearance behavior. |

Diagnostics do not discard retained rows. Unsupported types are marked for
review. Unsupported functions and expressions remain exact source text.

## Limits And Rejections

One `SourceLimits.deadline_seconds` deadline covers XLSX inspection, workbook
parsing, native parsing, and all external CSV reads. The aggregate workbook and
external-choice cell count must not exceed `max_cells`.

Survey Scribe rejects:

- formulas, macros, macro sheets, dialog sheets, and external workbook links;
- malformed or corrupt XLSX packages;
- external-choice URLs, absolute paths, path traversal, missing companions, and
  companions not explicitly present in the `SourceBundle`;
- duplicate required headers or survey item names;
- missing required `survey` headers or missing item names;
- duplicate settings rows, empty groups or repeats, unbalanced containers, and
  mismatched group/repeat end markers.

Dynamic instances, XML external data, `rank`, search appearances, trigger
behavior, arbitrary XPath functions, and arithmetic evaluation are not core
features. Survey Scribe does not execute any XLSForm expression.
