# Project Context

Additional context for Copilot and the Compound GPID plugin. Edit freely —
this file is committed to git and shared with the team.

## Data Sources
<!-- Where does data come from? File paths, databases, APIs, vintage conventions -->

## Domain Rules
<!-- Project-specific rules that Copilot should always follow -->

### Provider secret boundaries

- Keep auxiliary request credentials in adapter-only, attempt-local mappings.
- Replace raw request failures with fresh package errors after secret-bearing
  traceback frames are detached; safe messages alone are not sufficient.
- Hash and record the exact strict schema sent to a provider, and do not
  serialize or revalidate an already validated wire-model subtype.

## Work in Progress
<!-- Modules, features, or migrations currently underway -->

## Workspace Notes
<!-- Related folders, dependencies on other projects in the VS Code workspace -->

## Wiki Configuration
<!-- folder: wiki -->
<!-- audience: developers | researchers | end-users -->
<!-- tone: technical | conversational | formal -->
