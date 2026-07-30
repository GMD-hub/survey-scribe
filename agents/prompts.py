"""
LLM Prompt Templates
=====================
All prompts used by the extraction agents are defined here.

Keeping prompts in one file has a specific purpose: prompt improvement
is the main quality lever for this pipeline. When extraction quality
is poor — answer codes missing, wrong data type, universe not found —
the fix is almost always an edit to one of these prompts, not to the
pipeline logic.

Versioning guidance:
  When you change a prompt, add a comment above the change with:
    # CHANGED [date]: what changed and why
  This creates a lightweight audit trail without requiring a full
  version-control strategy for prompts.

Formatting note:
  {placeholder} tokens are filled by the agent before sending.
  Do not remove or rename them without updating svis_agent.py.
"""


# ── Survey metadata prompt ────────────────────────────────────────────────────

SURVEY_METADATA_PROMPT = """\
You are an expert in household survey methodology.

Below is the opening section of a household survey questionnaire document.
Extract the survey-level administrative information described below.

FIELDS TO EXTRACT:

survey_id
  A short unique identifier for this survey.
  Compose it as: COUNTRYISO3_YEAR_ACRONYM
  Examples: "BGD_2022_HIES", "ETH_2021_ESS", "COL_2020_GEIH"
  If the acronym is not clear from the document, use the initials of
  the survey name.

country_code
  ISO3 alpha code — exactly 3 uppercase letters.
  Examples: BGD, ETH, COL, KEN, VNM, NGA, IND, PAK

year
  Survey reference year as a 4-digit integer.
  Use the fieldwork year, not the publication year if both appear.
  If the survey spans multiple years, use the starting year of data collection.
    Example: 2009-2010, use 2009.
  Look for a year in the document opening, or in the title page, or in the header/footer.
  Example: 2009, 2014, 2024, 2010

survey_name
  Full official name of the survey.
  Example: "Bangladesh Household Income and Expenditure Survey 2022"

study_type
  Classify as one of:
    lsms    Living Standards Measurement Study
    dhs     Demographic and Health Survey
    lfs     Labour Force Survey
    hhs     Household Health Survey
    mics    Multiple Indicator Cluster Survey
    cwiq    Core Welfare Indicators Questionnaire
    census  Population and housing census
    other   Any other type

data_collection_mode
  How data was collected. Use exactly one of:
    CAPI    Computer-assisted personal interview (tablet or laptop)
    paper   Paper questionnaire
    CATI    Computer-assisted telephone interview
    mixed   Combination of modes
    unknown Not stated in the document

language
  Primary language of the questionnaire as a plain English word.
  Examples: "English", "French", "Spanish", "Arabic", "Portuguese"

RULES:
  Return null for any field you cannot determine from the document.
  Do not guess country codes — if unsure, return null.

DOCUMENT OPENING:
{text}
"""


# ── Variable extraction prompt ────────────────────────────────────────────────

VARIABLE_EXTRACTION_PROMPT = """\
You are an expert in household survey questionnaire design and microdata \
harmonization for international poverty measurement.

Below is one section of a household survey questionnaire, converted from PDF \
to Markdown. Extract structured information about every data-collection question \
in this section.

WHAT TO EXTRACT:
Extract every question that collects data from a respondent or interviewer.

DO NOT extract:
  - Section headings or module titles (these are not questions)
  - Interviewer instructions that do not collect data
  - Filter notes or routing instructions (unless they define the universe)
  - Enumerator signatures or administrative fields

FOR EACH QUESTION, provide these fields:

raw_name  [string, required]
  A short, descriptive snake_case identifier for this variable, built from
  the question content (e.g. highest_educ_level, age_completed_years).
  Keep it under 32 characters.
  # CHANGED 2026-07-28: raw_name must never be the questionnaire's own
  # printed item/COICOP code (e.g. "096011", "3 031221", "112011"). Those
  # codes belong in the category `code` sub-field, not in raw_name — using
  # them as raw_name produces meaningless identifiers and breaks downstream
  # harmonization joins.
  raw_name must also be UNIQUE across every variable you return for this
  chunk. If two questions would naturally produce the same name (e.g. two
  separate "Amount paid in Old Leks" questions in different subsections),
  disambiguate them by appending the specific item they refer to
  (e.g. amount_paid_old_leks_equipment, amount_paid_old_leks_vehicle).

label  [string or null]
  A short description of what this variable measures.
  Maximum 80 characters. Write it as a noun phrase, not a sentence.
  Example: "Highest level of education completed"

question_text  [string or null]
  The full question text exactly as written. Preserve placeholders like
  [NAME], [ROSTER], or [HH MEMBER]. Do not paraphrase.
  Example: "What is the highest level of schooling [NAME] has completed?"

data_type  [one of the following]
  numeric             A number used as a number (age, income, household size,
                      years of education). NOT a code from a list.
  categorical_single  Respondent chooses exactly one option from a list.
  categorical_multi   Multiple options can be selected simultaneously.
  text                Free-form string (name, open-ended answer).
  date                A date or datetime.
  other               GPS, photo, audio, barcode.

categories  [list or null]
  For categorical_single and categorical_multi ONLY.
  List EVERY answer option — do not omit any.

  Each category has three sub-fields:
    code        The numeric or string code stored in the data file.
                Must be taken exactly from the questionnaire.
    label       The text of the answer option.
    is_missing  true if this code means "don't know", "refused",
                "not applicable", "not stated", "can't remember", or
                "not present"/"not applicable" — or any similar
                non-substantive response. false for all real answers.
  # CHANGED 2026-07-28: Sentinel codes are common in these questionnaires
  # (e.g. "if no present write 99", "9 = can't remember the amount",
  # codes ending in 98 or 99). Always set is_missing=true for such codes,
  # and give them a label that describes the missing-value meaning itself
  # (e.g. "Not present", "Can't remember") rather than reusing the
  # question's own wording or a neighboring substantive answer's label.
  # A sentinel code must never also be labeled as if it were a literal
  # substantive answer (e.g. code 9 cannot mean both "No" and be marked
  # is_missing=true at the same time — pick one, and it is almost always
  # the missing-value meaning).

  IMPORTANT: Never invent codes that are not in the questionnaire.
  If a table of codes did not extract cleanly, note this in the
  notes field and lower your confidence score.
  # CHANGED 2026-07-28: If you notice the same code appearing more than
  # once with different labels, or a code with no legible label at all
  # (e.g. a garbled multi-column table), do NOT fabricate a plausible-
  # looking placeholder label (like "Equipment 073211" or "Type 1
  # appliance"). Instead, keep only the labels you are confident about,
  # set needs_review=true, set extraction_confidence to 0.5 or below, and
  # describe the garbling in notes.

numeric_range  [object or null]
  For numeric variables ONLY. Leave null for all other types.
  Extract the valid range from validation notes, question instructions,
  or parenthetical remarks in the questionnaire.

  Sub-fields:
    min_value   Minimum valid substantive value (e.g. 0 for age).
    max_value   Maximum valid substantive value (e.g. 120 for age).
    notes       Any context, e.g. "codes 98 and 99 appear in data but
                mean don't know / refused — listed in categories."

  If no range is stated anywhere in the questionnaire text, return null.

universe  [string or null]
  Plain-language description of who is asked this question.
  Write a single sentence. Be specific about age restrictions.
  Examples:
    "All household members"
    "All household members aged 5 and above"
    "Women aged 15 to 49"
    "Household head only"
    "Employed persons only (those with lstatus = 1)"
  If the universe is unrestricted, write: "All household members"
  If you cannot determine it, return null and lower your confidence.

skip_condition_raw  [string or null]
  The raw skip or routing instruction exactly as written.
  Do not interpret or simplify. Preserve it verbatim.
  Example: "If answer is 00, skip to Q20."
  Return null if no skip instruction appears.

module  [string]
  The module or section this variable belongs to.
  Use the nearest Markdown heading above the question.
  Default: "{module_name}"

unit_of_analysis  [one of: individual, household, other]
  Whether this variable describes a person or a household.
  individual  Questions asked for each person in the household roster.
              Examples: age, sex, education, employment, marital status.
  household   Questions about the dwelling or household as a whole.
              Examples: total household income, roof material, asset ownership.
  other       Plot, enterprise, livestock, or other non-person unit.
  When uncertain, choose individual and note your reasoning.

extraction_confidence  [float, 0.0 to 1.0]
  Your overall confidence in the accuracy of this record.
  Score the whole record, not individual fields.
  1.0   All fields clear, unambiguous, complete.
  0.9   One minor uncertainty (a label slightly paraphrased, etc.)
  0.7   Notable uncertainty — one important field unclear or inferred.
  0.5   Multiple fields uncertain; record is plausible but not reliable.
  0.0   You are guessing. Set needs_review=True.

needs_review  [boolean]
  Set true if ANY of the following apply:
    - extraction_confidence is below 0.7
    - question_text is null
    - data_type could not be determined reliably
    - categories is null for a variable that appears to be categorical
    - answer codes could not be extracted cleanly from a table

notes  [string or null]
  Record any uncertainty, ambiguity, or special observation.
  This field is read by the human reviewer — be specific.
  Examples:
    "Answer code table did not extract cleanly; codes 4 and 5 may be missing."
    "Universe inferred from section heading, not stated explicitly."
    "Question appears twice with different wording; used the version at top of page."

IMPORTANT RULES:
  1. Never invent answer codes that are not in the questionnaire text.
  2. Never invent variable names; construct them from question content,
     never from the questionnaire's own printed item/COICOP code, and
     never reuse the same raw_name for two different questions.
  3. If a Markdown table is garbled, note it and lower confidence — do not guess.
  4. Return ONLY the structured output. No preamble, no commentary.

QUESTIONNAIRE SECTION
Module: {module_name}
Chunk: {chunk_index}

{text}
"""
