# Documentation Site

The site uses MkDocs, Material for MkDocs, and mkdocstrings. Markdown provides
the guides; mkdocstrings reads Python signatures and docstrings from `src/` for
the API reference.

## Directory layout

```text
survey-scribe/
|-- mkdocs.yml
|-- docs/
|   |-- index.md
|   |-- getting-started/  # installation and first extraction
|   |-- guides/           # extraction, routing, providers, and operations
|   |-- integrations/     # gateway integration patterns
|   |-- platforms/        # hosted-runtime deployment guides
|   |-- reference/        # generated and hand-written API reference
|   |-- project/          # current support ledger
|   |-- contributing/     # documentation maintenance
|   `-- assets/           # generated schemas, CSS, and JavaScript
`-- .github/
    `-- workflows/
        |-- docs.yml
        `-- deploy-docs.yml
```

## Required tooling

Documentation dependencies are pinned in the `dev` dependency group:

- MkDocs 1.6.1
- Material for MkDocs 9.7.7
- mkdocstrings 0.30.0 with its Python handler

The MkDocs configuration enables search, generated Python reference pages,
admonitions, details blocks, syntax highlighting, code copying, tabbed content,
tables, heading permalinks, responsive custom styles, and one default palette.

## Local preview

```console
uv sync --locked
uv run mkdocs serve
```

Open `http://127.0.0.1:8000/`. MkDocs watches documentation and package source
files used by generated references.

## Strict build

Run the strict build:

```console
uv run mkdocs build --strict --clean
```

The generated static site is written to `site/`. Do not commit that directory.

Before merge, run the complete offline content checks:

```console
uv run python scripts/generate_docs_reference.py --check
UV_OFFLINE=1 uv run linkchecker --ignore-url='^https?://' site/
UV_OFFLINE=1 uv run pytest --disable-socket --allow-unix-socket tests/docs
```

## Deployment

`.github/workflows/deploy-docs.yml` builds on every push to `main` and on manual
dispatch. It uploads the generated `site/` directory as a GitHub Pages artifact
and deploys it with GitHub's OpenID Connect flow. Before upload, it checks
generated references, builds in strict offline mode, checks local links, and runs
the offline documentation tests. No long-lived deployment token or provider API
key is required.

In the repository settings, set **Pages > Build and deployment > Source** to
**GitHub Actions**. The workflow's `pages` environment then records the deployed
URL and deployment history.

## Authoring rules

- Document supported package behavior, not plans or repository-only prototypes.
- Use fully typed, runnable snippets with placeholder data.
- Never include real API keys, questionnaire data, internal endpoints, or tokens.
- Add new pages to `nav` in `mkdocs.yml`.
- Run the strict build before merging a documentation change.
