---
name: improve-prompt
description: Suggests new or improved instruction text for agents/prompts.py based on a specific extraction error observed in the SVIS output. Use this when asked to fix a prompt, improve an instruction, or address a recurring extraction error.
---

# Improve a Prompt Instruction

This skill helps draft new or improved instruction text for the
VARIABLE_EXTRACTION_PROMPT in agents/prompts.py to fix a specific
extraction error.

## What to ask the user for

Before drafting any instruction, collect:
1. A plain-language description of the error being observed
2. An example of the wrong JSON output (paste the variable block)
3. The corresponding original question from the questionnaire
4. What the correct output should look like

If any of these are missing, ask for them before proceeding.

## Rules for writing good prompt instructions

**Be specific, not general.**
Bad: "Be careful about missing values."
Good: "Mark is_missing=true for any code whose label contains the words
'don't know', 'refused', 'not applicable', 'not stated', or any equivalent
phrasing in any language, including codes 98, 99, 999, or similar high numeric
values at the end of a code list."

**Add examples directly in the instruction.**
Examples are the most effective way to fix judgment-call errors. Show both
a correct and an incorrect case wherever possible.

**Cover language variations.**
GMD surveys come from many countries. Phrasing like "don't know" may appear as
"ne sait pas", "no sabe", "tidak tahu", or numeric codes 98/99 with no label.
Instructions should cover these variations explicitly.

**One instruction per error type.**
Each instruction should address exactly one type of error so its effect can
be tested independently.

**Target specific fields.**
Each instruction should clearly state which field it applies to (e.g.
is_missing, numeric_range, unit_of_analysis) rather than giving general advice.

## Output format

Always provide:

1. The new instruction text: Formatted exactly as it should appear in the
   prompt, ready to copy and paste. Include a concrete example inside it.

2. Where it goes: State which field section of VARIABLE_EXTRACTION_PROMPT
   it belongs to, and whether it replaces existing text or adds to it.

3. Comment to add above it: Write a one-line comment in this format:
   # CHANGED [date]: [what changed and why]

4. What to keep: If it replaces existing text, quote the original line(s)
   to comment out (not delete).

5. How to test it: Describe one specific variable in the questionnaire
   that should now extract correctly if this instruction works.

## Scope reminder

The intern should only edit agents/prompts.py. Do not suggest changes to
schemas/svis.py, extractors/pdf.py, agents/svis_agent.py, or pipeline.py
unless the project lead has approved it.
