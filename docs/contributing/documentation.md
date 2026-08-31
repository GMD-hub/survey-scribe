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
|   |-- getting-started/
|   |   |-- installation.md
|   |   `-- quickstart.md
|   |-- guides/
|   |   |-- configuration.md
|   |   |-- results.md
|   |   |-- security.md
|   |   |-- sources.md
|   |   |-- svis.md
|   |   `-- use-cases.md
|   |-- reference/
|   |   |-- index.md
|   |   |-- cli.md
|   |   |-- configuration.md
|   |   |-- exceptions.md
|   |   |-- models.md
|   |   |-- results.md
|   |   |-- serialization.md
|   |   `-- sources.md
|   |-- contributing/
|   |   `-- documentation.md
|   `-- assets/
|       `-- stylesheets/
|           `-- extra.css
`-- .github/
    `-- workflows/
        `-- deploy-docs.yml
```

## Required tooling

Documentation dependencies are pinned in the `dev` dependency group:

- MkDocs 1.6.1
- Material for MkDocs 9.6.18
- mkdocstrings 0.30.0 with its Python handler

The MkDocs configuration enables search, generated Python reference pages,
admonitions, details blocks, syntax highlighting, code copying, tabbed content,
tables, heading permalinks, responsive custom styles, and light/dark palettes.

## Local preview

```console
uv sync --locked
uv run mkdocs serve
```

Open `http://127.0.0.1:8000/`. MkDocs watches documentation and package source
files used by generated references.

## Strict build

Run the same strict build used by deployment:

```console
uv run mkdocs build --strict --clean
```

The generated static site is written to `site/`. Do not commit that directory.

## Deployment

`.github/workflows/deploy-docs.yml` builds on every push to `main` and on manual
dispatch. It uploads the generated `site/` directory as a GitHub Pages artifact
and deploys it with GitHub's OpenID Connect flow. No long-lived deployment token
or provider API key is required.

In the repository settings, set **Pages > Build and deployment > Source** to
**GitHub Actions**. The workflow's `pages` environment then records the deployed
URL and deployment history.

## Authoring rules

- Document supported package behavior, not plans or repository-only prototypes.
- Use fully typed, runnable snippets with placeholder data.
- Never include real API keys, questionnaire data, internal endpoints, or tokens.
- Add new pages to `nav` in `mkdocs.yml`.
- Run the strict build before merging a documentation change.
