# SVIS Field Reference Guide

Complete field-by-field reference for the Survey Variable Information Schema.
Use this when reviewing extracted output or editing prompts.

---

## SurveyVariable fields

### `raw_name` — required

The variable name as it appears in the raw microdata file.

Examples: `q14`, `hh_educ`, `s2b_q4`, `B3a`

If no code is printed in the questionnaire, the LLM constructs a descriptive
snake_case name from the question content. Examples: `highest_educ_level`,
`age_completed_years`.

Keep under 32 characters (the Stata variable name limit).

---

### `label` — optional

A short, human-readable description of what the variable measures.
Maximum 80 characters (the Stata variable label limit).
Written as a noun phrase, not a sentence.

Good: `"Highest level of education completed"`
Bad: `"This variable measures the highest level of education."`

---

### `question_text` — optional but important

The full question text exactly as written in the questionnaire.
Placeholders like `[NAME]` or `[ROSTER]` are preserved verbatim.

This is the richest semantic signal the harmonization AI has.
A missing `question_text` should always trigger `needs_review = true`.

---

### `data_type` — required

| Value | Meaning | GMD examples |
|---|---|---|
| `numeric` | A number used as a number | age, educy, household size |
| `categorical_single` | One code chosen from a list | male, urban, marital, lstatus |
| `categorical_multi` | Multiple codes can apply | assets owned, income sources |
| `text` | Free-form string | household member name |
| `date` | A date or datetime | date of birth |
| `other` | GPS, photo, audio, barcode | not relevant to PoC |

---

### `categories` — required for categorical variables

List of all answer options. Omitting categories is the most common and most
damaging extraction error. The harmonization AI cannot propose a correct mapping
without the full code list.

Each category has three sub-fields:

| Sub-field | Type | Description |
|---|---|---|
| `code` | int or str | The value stored in the raw data file |
| `label` | str | The answer text from the questionnaire |
| `is_missing` | bool | True if this code means "don't know", "refused", etc. |

The `is_missing` flag is critical. Non-substantive codes must be recoded to
missing (`.`) in GMD. Flagging them here prevents silent errors downstream.

Mark `is_missing = true` for any code meaning:
"Don't know" / "Refused" / "Not applicable" / "Not stated" / "No information" /
"Inapplicable" / "Missing" / or any regional equivalent.

---

### `numeric_range` — for numeric variables only

Valid value range for a numeric variable.

| Sub-field | Type | Description |
|---|---|---|
| `min_value` | float or null | Minimum valid substantive value |
| `max_value` | float or null | Maximum valid substantive value |
| `notes` | str or null | Additional context |

**Why this matters:** A value of 99 in a variable with stated maximum 90 is
almost certainly a missing-value code masquerading as a number. The range
makes this detectable without manual inspection.

Common ranges to expect:

| Variable | Typical range | Notes |
|---|---|---|
| Age | 0 to 120 | 98/99 often = don't know / refused |
| Years of education | 0 to 25 | 98/99 often = don't know |
| Household size | 1 to 30 | Rarely has missing codes |
| Hours worked per week | 0 to 168 | |

---

### `universe` — optional but important

Plain-language description of who is asked this question.
A single sentence, specific about age restrictions.

Good: `"All household members aged 5 and above"`
Bad: `"People"` or `"As applicable"`

The harmonization AI uses this to determine which observations should be
set to missing in the GMD file. An incorrectly broad universe causes
spurious values; an incorrectly narrow one causes real data to be dropped.

---

### `skip_condition_raw` — optional

The skip instruction as written verbatim in the questionnaire.
Preserved exactly — not interpreted or simplified.

Example: `"If Q3 = 00 (never attended school), skip to Q20."`

This is for reference and audit. The `universe` field above is what the
harmonization AI uses operationally.

---

### `module` — optional

The section or module this variable belongs to.
Examples: `"Section 4: Education"`, `"Labour Module"`, `"Household Roster"`

The module provides semantic context. A variable named `educ` inside an
"Education" module is more clearly mappable than the same variable inside a
"Job History" module.

Set automatically to the nearest Markdown heading by the pipeline.
Override in review if the automatic assignment is wrong.

---

### `unit_of_analysis` — required

| Value | Meaning | Examples |
|---|---|---|
| `individual` | Describes a person | age, sex, education, labor status |
| `household` | Describes the household unit | dwelling type, total income, assets |
| `other` | Plot, enterprise, livestock, etc. | Not relevant to PoC |

This is one of the most consequential fields. Variables at the wrong level
cause silent errors in poverty and welfare calculations. When uncertain,
flag for review.

---

### `extraction_confidence` — required

Float between 0.0 and 1.0. The LLM's self-assessment of the whole record.

| Score | Meaning |
|---|---|
| 1.0 | All fields clear, unambiguous, complete |
| 0.9 | One minor uncertainty |
| 0.7 | Notable uncertainty — one important field unclear or inferred |
| 0.5 | Multiple fields uncertain; plausible but not reliable |
| 0.0 | The LLM is guessing |

Scores below 0.7 automatically set `needs_review = true`.

---

### `needs_review` — required

Boolean flag for the human review queue.

Set `true` if any of the following apply:
- `extraction_confidence` is below 0.7
- `question_text` is null
- `data_type` could not be determined reliably
- `categories` is null for a variable that appears to be categorical
- Answer codes could not be extracted cleanly

Human reviewers check all variables with `needs_review = true` and either
correct the record or confirm it. They then set `needs_review = false`.

---

### `notes` — optional

Free text for the LLM to record uncertainties, ambiguities, or observations.
This field is read by the human reviewer. Be specific.

Good: `"Answer code table did not extract cleanly. Codes 4 and 5 may be missing."`
Good: `"Universe inferred from section heading, not stated explicitly."`
Bad: `"Extracted with some uncertainty."` (too vague)

---

## SurveySVIS fields

### `survey_id`

Convention: `COUNTRYISO3_YEAR_ACRONYM`

Examples: `BGD_2022_HIES`, `ETH_2021_ESS`, `COL_2020_GEIH`, `KEN_2019_KIHBS`

---

### `study_type`

| Value | Survey type |
|---|---|
| `lsms` | Living Standards Measurement Study |
| `dhs` | Demographic and Health Survey |
| `lfs` | Labour Force Survey |
| `hhs` | Household Health Survey |
| `mics` | Multiple Indicator Cluster Survey |
| `cwiq` | Core Welfare Indicators Questionnaire |
| `census` | Population and housing census |
| `other` | Any other type |

---

### `source_format`

| Value | Meaning |
|---|---|
| `pdf` | PDF questionnaire (current PoC scope) |
| `xlsx` | Excel codebook (future scope) |
| `ss_json` | Survey Solutions JSON export (future scope) |
