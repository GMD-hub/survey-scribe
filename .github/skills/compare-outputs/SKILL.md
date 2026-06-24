---
name: compare-outputs
description: Compares two versions of an extracted SVIS variable (before and after a prompt change) to assess whether the change improved the extraction. Use this after re-running the pipeline in Subtask 7, or whenever asked to compare extraction outputs.
---

# Compare Before and After Extractions

This skill assesses whether a prompt change in agents/prompts.py improved
the extraction of a specific variable.

## What to ask the user for

Before comparing, collect:
1. A description of the prompt change that was made
2. The variable JSON block from the v0 output (before the change)
3. The variable JSON block from the v1 output (after the change)
4. The original question from the questionnaire

All four are needed. Ask for any that are missing before proceeding.

## How to perform the comparison

**Step 1: Assess v0**
Review the v0 block using the same criteria as the review-extraction skill.
Identify all errors present in v0.

**Step 2: Assess v1**
Review the v1 block with the same criteria.
Identify errors still present, any errors fixed, and any new errors introduced.

**Step 3: Link changes to outcomes**
For each error targeted by the prompt change:
- Was it fixed completely?
- Was it partially fixed?
- Was it unchanged?

For each field that was correct in v0:
- Is it still correct in v1?
- Did the prompt change accidentally break something?

## Output format

Always provide:

1. Target error verdict: Was the specific error resolved? (Yes / Partially / No)

2. Regression check: Did anything correct in v0 break in v1?
   (Yes — describe what / No)

3. Overall verdict: Improvement / No change / Regression

4. Comparison table row (ready to paste into the review document):

   | Variable | Error in v0 | Fixed in v1? | Notes |
   |---|---|---|---|
   | [raw_name] | [describe v0 error] | Yes / Partially / No | [notes] |

5. Next step recommendation:
   - If fixed: "This change is working. Move to the next error type."
   - If partially fixed: "Try adding [specific suggestion] to the instruction."
   - If unchanged: "Consider [specific alternative approach]."

## Scope reminder

Limit recommendations to changes in agents/prompts.py only, unless the
project lead has approved changes to other files.
