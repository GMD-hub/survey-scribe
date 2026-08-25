# Survey-Scribe Daily Project Log

Maintained by the "Daily Project Log" agent (`.github/agents/daily-project-log.agent.md`). Newest entries first.

## 2026-08-06

**Window:** `2026-08-03T19:53:34Z` to `2026-08-06T19:48:08Z`
**Branch:** `doclingAI`
**State:** uncommitted changes only (no commits since `fcc234e` on 2026-07-31) — `README.md`, `agents/prompts.py`, `agents/svis_agent.py`, `docling_pipeline.py`, `extractors/docling_pdf.py`, `requirements.txt` modified; `docs/project-log.md` staged as new; `agents/review_agent.py` and `review_pipeline.py` staged as added, then deleted from the working tree (net no-op)

### Key Changes
- Switched `MODEL` in `agents/svis_agent.py` from `gpt-4.1-mini` to `gpt-4.1` and re-ran extraction on the Burkina Faso EBCVM 2009-10 questionnaire, producing `output/BFA_2009_OTHER_svis.json` for comparison against the earlier `gpt-4.1-mini` run (`output/BFA_2009_HHM_svis.json`).
- Built a review-agent prototype (`agents/review_agent.py`, `review_pipeline.py`, a `REVIEW_PROMPT` in `agents/prompts.py`, and markdown-persistence support in `docling_pipeline.py`/`extractors/docling_pdf.py`), then fully reverted all of it after deciding to scrap the idea ahead of the internship's end, to avoid leaving untested code behind.
- Cleaned up stale comments/docstrings left over from earlier deletions (references to `pipeline_docling.py`, `extractors/pdf.py`, MarkItDown, and the removed `recognition/` sub-project) in `docling_pipeline.py` and `extractors/docling_pdf.py`.
- Removed unused dependencies (`marker-pdf`, git`python-dotenv`) from `requirements.txt` after confirming zero imports anywhere in the codebase; fixed a stale comment that attributed `lingua-language-detector` to the now-deleted `recognition/` sub-project.
- Fixed `README.md`'s hardcoded claim that the model is `gpt-4.1-mini` (now points to the settings table instead, since the constant changes over time) and added a new **Next steps** section covering: the review-agent idea, an auto-fix/improver-agent idea, the `gpt-4.1` completeness-regression finding (below), the unfinished page-tracking (`source_page` always `0`), and remaining handoff loose ends.

### What Worked
- Model comparison completed with concrete per-module evidence: `gpt-4.1` improved judgment/accuracy on individual fields (fixed a real category/question mismatch, cleaner categorical codes, smarter `data_type` calls) but **dropped 50–90% of variables in the largest, most repetitive modules** compared to `gpt-4.1-mini` (Governance 37→14, Housing 17→8, ICT access 10→1), while gaining coverage on smaller structured sections (Services access 1→11).
- `pytest tests/test_schema.py -v` — 27/27 passed after the revert/cleanup edits.
- `py_compile` on the three edited modules (`docling_pipeline.py`, `extractors/docling_pdf.py`, `agents/prompts.py`) completed with no errors.
- `grep_search` confirmed `marker-pdf` and `python-dotenv` have no imports anywhere before removing them from `requirements.txt`.

### What Did Not Work
- A teammate (different machine/username, `wb643887`) hit `ModuleNotFoundError: No module named 'itsai'` running `docling_pipeline.py` in their own `.venv` — `itsai` is a World Bank-internal package, not listed in `requirements.txt` and not on public PyPI. Root cause is confirmed (package never installed) but the correct internal source to install it from was not identified in this session.
- Several terminal commands hit the previously-documented PowerShell "unterminated string" continuation-state quirk while verifying the cleanup edits; recovered using the documented workaround (send a lone `"`).

### Open Questions
- Whether to keep `MODEL = "gpt-4.1"` or revert to `gpt-4.1-mini` given the completeness regression on dense/repetitive modules — not decided this session.
- Which internal package source provides `itsai` for teammates setting up on a fresh machine.
- The README `Contact` section still has a placeholder (`[Andres — add contact info]`) — not filled in.

### Next Steps
1. Decide and document the final `MODEL` choice (`gpt-4.1` vs `gpt-4.1-mini`), weighing the accuracy-vs-completeness tradeoff found this session, before the internship handoff.
2. Identify and document the internal package source for `itsai` so new teammates don't hit the `ModuleNotFoundError`.
3. Fill in the `Contact` section placeholder in `README.md`.
4. Commit the outstanding working-tree changes — nothing from this window has been committed yet.

### Evidence
- `git status --short`, `git diff --stat`, `git diff --cached --stat` — file-level change summary above.
- `git log -5` — last commit `fcc234e` (2026-07-31); no commits in this window.
- `pytest tests/test_schema.py -v` — 27 passed.
- `output/BFA_2009_HHM_svis.json` vs `output/BFA_2009_OTHER_svis.json` — per-module variable-count comparison (PowerShell `Group-Object`).
- Copilot session `aabf5db4-a15d-449c-8412-341c8bd274dc`, turns 43–51 (2026-08-04T14:46Z – 2026-08-06T19:48Z).

### Evidence Gaps
- The teammate's `itsai` error was reported second-hand in chat, not independently reproduced or investigated in this repo's own environment.
- Window end timestamp approximated from the session store's `updated_at` rather than a discrete logged event.

## 2026-08-03

**Window:** `2026-08-02T19:53:34Z` to `2026-08-03T19:53:34Z`
**Branch:** `doclingAI`
**State:** clean (no uncommitted changes; no commits in this window)

### Key Changes
- No code changes in this window. Activity was a planning/advisory discussion about building a new custom Copilot agent that would run at the end of a work session and write a file into a new folder, modeled on the existing `daily-project-log` agent.

### What Worked
- Confirmed `.github/agents/daily-project-log.agent.md` as a working, invokable template (via trigger phrase or the agent picker) to base the new agent on.

### What Did Not Work
- No verified failures in this window.

### Open Questions
- What should the new per-session agent's output file contain (full session summary vs. a simple marker/timestamp file)?
- What folder/file naming convention should it use (e.g. `session-logs/<date>_<time>/summary.md` vs. one shared folder with a per-run file)?

### Next Steps
1. Get the user's answer on output content and folder-naming convention for the new per-session agent.
2. Create the new `.github/agents/<name>.agent.md` file once those requirements are confirmed.

### Evidence
- `git log --since="24 hours ago"` — no commits.
- `git status --short` — clean working tree.
- Copilot session `aabf5db4-a15d-449c-8412-341c8bd274dc`, turns 39–41 (2026-08-03T17:48–19:51 UTC).

### Evidence Gaps
- No code/file diffs exist for this window since no edits were made, so this entry is based solely on conversation content.
