---
name: review-extraction
description: Reviews the accuracy of a single extracted SVIS variable against the original questionnaire question. Use this when asked to check, review, or validate a variable extraction, or when comparing a JSON variable block to a questionnaire question.
---

# Review an Extracted Variable

This skill assesses the accuracy of one extracted SurveyVariable JSON block
against the original question from a household survey questionnaire.

## What to ask the user for

Before starting the review, make sure you have both:
1. The original question from the questionnaire (question text, answer options,
   any skip instructions)
2. The extracted JSON block for that variable from the SVIS output file

If either is missing, ask the user to provide it.

## How to perform the review

Go through each field in the JSON block and check it against the questionnaire:

**raw_name**
Does it match the variable code printed in the questionnaire (e.g. Q4, h_educ)?
If no code was printed, is the constructed snake_case name reasonable?

**question_text**
Is it copied verbatim from the questionnaire? Note any paraphrasing or
differences, however minor.

**data_type**
Is it the correct type? Key rules:
- A number used as a number (age, income, years of schooling) → numeric
- One option chosen from a list → categorical_single
- Multiple options can apply → categorical_multi
- Free text → text
- A date → date

**categories** (for categorical variables only)
- Are ALL answer options present? List any that are missing by name.
- Is the code for each option exactly as printed in the questionnaire?
- Is is_missing correctly set to true for "don't know", "refused",
  "not applicable", "not stated", and similar non-substantive options?
- Is is_missing incorrectly set to true for any substantive option?
- Omitting categories is the most serious extraction error — flag it clearly.

**numeric_range** (for numeric variables only)
Is the range stated anywhere in the questionnaire text or instructions?
If yes, was min_value and max_value captured correctly?

**universe**
Does it correctly describe who is asked this question?
Examples of good universe descriptions:
- "All household members aged 5 and above"
- "Household head only"
- "Women aged 15 to 49"

**unit_of_analysis**
Is individual or household correct for this question?
Questions asked for each person in a roster → individual
Questions about the dwelling or household as a whole → household

**extraction_confidence**
Given the errors found, does the score seem appropriate?
A score above 0.7 with missing answer codes is an underestimate.

## Output format

Always provide:
1. Verdict: Correct, Partial, or Wrong
2. Error list: Bullet points for each specific error or missing field
3. Recommended confidence score: What you would assign (0.0 to 1.0)
4. needs_review recommendation: true or false
5. One-line summary: e.g. "Missing 2 answer codes; question text paraphrased"
