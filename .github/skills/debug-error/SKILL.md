---
name: debug-error
description: Diagnoses and fixes errors that occur when running the surveyscribe pipeline. Use this when the pipeline crashes, produces an unexpected error message, or when asked to explain a Python or API error.
---

# Debug a Pipeline Error

This skill diagnoses errors from the surveyscribe pipeline and provides
a specific fix.

## What to ask the user for

Before diagnosing, collect:
1. The exact command that was run
2. The full error output from the terminal (everything, not just the last line)
3. What the user expected to happen

If any are missing, ask before proceeding.

## Common error types and their fixes

**AuthenticationError or API key not found**
The selected provider credential is missing or incorrect.
Fix: Run `survey-scribe config check`. Set a supported environment variable,
such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, or use the matching non-echo
CLI prompt. Survey Scribe does not load `.env` files automatically.

**ModuleNotFoundError: No module named X**
A required library is not installed, or the virtual environment is not active.
Fix: Check whether (.venv) appears in the terminal prompt.
If not, activate the virtual environment:
  Mac/Linux: source .venv/bin/activate
  Windows: .venv\Scripts\activate
Then run: `uv sync --locked`, including the required optional extra.

**FileNotFoundError**
The PDF path is wrong.
Fix: Check that the file exists and the path is spelled correctly.
Run: ls tests/samples/   to see what files are actually there.

**Scanned PDF dependency or cache error**
Install the `pdf` extra and verify the approved local OCR artifact cache. The
packaged adapter processes scanned PDFs and does not silently skip them.

**ValidationError from Pydantic**
The LLM returned output that does not match the SVIS schema.
The instructor library retries this automatically up to 3 times.
If it still fails, note the chunk name and report to the project lead.

**InstructorRetryException**
All retries exhausted. The chunk is flagged and skipped.
Note which sections failed and report them to the project lead.

**JSONDecodeError**
The LLM returned malformed output. Usually resolved by retrying the same run.

## Output format

Always provide:
1. Plain-language explanation: What does this error mean?
2. Root cause: What specifically caused it?
3. Exact fix: The command to run or the line to change.
4. Verification step: How to confirm the fix worked.
5. Scope check: State whether this is configuration, optional dependencies,
   source validation, provider transport, extraction, or artifact publication.
