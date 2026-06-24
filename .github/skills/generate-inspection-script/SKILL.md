---
name: generate-inspection-script
description: Generates the inspect_output.py script for reading and summarizing SVIS JSON output files. Use this once in Subtask 5 when the user needs to create the inspection script, or when asked to regenerate or improve it.
---

# Generate the Output Inspection Script

This skill generates inspect_output.py, a script that reads a SVIS JSON
output file and prints a structured summary to the terminal.

## When to use this skill

Use this once, in Subtask 5, to create inspect_output.py for the first time.
It can also be used to improve or regenerate the script if needed later.

## What the script must do

**1. Find the output file**
Find the most recently modified JSON file in the output/ folder using pathlib.
If no JSON files exist, print a clear message and exit without raising an error.

**2. Load and parse the file**
Load the JSON and parse it as a SurveySVIS object by importing from schemas.svis.
Use Pydantic's model_validate_json() so schema mismatches are caught explicitly.

**3. Print a header section**
Show in a clearly formatted block:
- Survey name
- Country code and year
- Study type and data collection mode
- Source file and extraction date
- Total number of variables extracted
- Number flagged for review (needs_review = true)

**4. Print a module breakdown table**
Group variables by their module field and show for each module:
- Module name
- Number of variables
- Number flagged for review in that module
Use a simple text-based table with column alignment. No external libraries.

**5. Print a data type breakdown**
Count how many variables of each data_type were extracted.

**6. Print all flagged variables**
If any variables have needs_review = true, list each one showing:
- raw_name
- data_type
- extraction_confidence (rounded to 2 decimal places)
- notes field, or "No notes provided" if null

**7. Print a closing summary line**
e.g. Output file: output/BGD_2022_HIES_svis.json

## Technical requirements

- Use only the Python standard library plus pathlib and pydantic
- Do not use tabulate, pandas, rich, or any other external library
- Add clear section separators between sections
- Run with: python inspect_output.py  (no command-line arguments)

## After generating

Tell the user to:
1. Save the output as inspect_output.py in the project root
2. Run it with: python inspect_output.py
3. If it produces an error, paste the error back into this chat for a fix
4. Keep this script — it will be used after every pipeline run in Subtask 7
