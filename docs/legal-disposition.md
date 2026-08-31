# Legal Disposition

## Scope

This is an operational engineering disposition, not legal advice and not a
license grant. It records the controls applied to the repository while formal
copyright, licensing, and contribution decisions remain unresolved.

## Repository State

- Repository: `https://github.com/GMD-hub/survey-scribe`
- Visibility checked on 2026-08-26: public
- Default branch: `main`
- Approved license metadata: MIT, selected in the 2026-08-27 package-readiness
  instruction
- Recorded contributor identities: StephenON, Stephen Obundah Nwobike,
  R.Andres Castaneda, and R.Andres Castaneda with accented spelling
- Copyright ownership and accepted-contribution provenance: not established by
  repository files and requiring institutional review

## Limited Authorization

The 2026-08-26 execution instruction explicitly authorizes creating an
engineering branch, implementing the approved production-package plan, and
opening one pull request. Under that instruction:

- Continued local engineering work is permitted.
- A push of this engineering branch and its pull request is permitted.
- Build-and-test CI associated with that pull request is permitted.
- Only synthetic fixtures created for this repository may be committed unless
  a fixture has a separate rights and checksum record.

This authorization does not establish ownership, approve a license, accept
outside contributions, or authorize package publication. The 2026-08-27
package-readiness instruction separately approved the MIT license and authorized
release-readiness engineering. The 2026-08-31 documentation instruction formally
approved publication of synthetic-only package documentation to GitHub Pages
through GitHub Actions. It did not approve package registry publication.

## Prohibited Until Formal Approval

- PyPI, TestPyPI, package release, or package deployment
- Restricted, confidential, personal, or unsanitized questionnaires
- Public model responses or traces derived from restricted inputs
- Workflows with tag triggers, repository-wide write permission, or package
  publication credentials

GitHub Pages deployment is limited to the generated documentation site. It uses
the scoped `pages: write` and `id-token: write` permissions, immutable action
revisions, the locked project environment, and no provider or package registry
credentials.

If institutional review rejects continued public development, the repository
must be made private and pushes must stop. Any ambiguity is resolved in favor
of no publication and synthetic-only fixtures.

## Fixture Disposition

The Phase 1 golden corpus is synthetic-only. Its manifest records authorship,
purpose, restrictions, and SHA-256 checksums. Historical questionnaire outputs
mentioned in narrative project documents are not approved fixtures and do not
count as quality evidence.

## Review Trigger

Revisit this disposition before adding real fixtures, accepting contributions,
enabling public artifacts beyond build-only workflow output, or performing any
release action.
