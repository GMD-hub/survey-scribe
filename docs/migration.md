# Migration From The Legacy Script

The repository-level `docling_pipeline.py` entry point remains available through
1.x for existing automation:

```console
python docling_pipeline.py questionnaire.pdf --output-dir output
```

New automation should use the installed command:

```console
survey-scribe convert questionnaire.pdf --output-dir output
```

Install the extras needed by the selected source and provider before migration.
For example, PDF extraction through OpenAI needs
`python -m pip install "survey-scribe[pdf,openai]"` and a validated local OCR
cache. The installed CLI is not a wrapper around the root script; it uses the
public `SurveyScribe` facade and returns defined result statuses.

## Configuration

The legacy script and installed CLI now use the package configuration system.
Move non-secret settings to `./survey-scribe.toml` or pass an exact `--config`
path. Move credentials to supported environment variables. Neither interface
searches parent or home directories, and TOML files cannot contain credentials.

The installed command also supports a non-echo credential prompt:

```console
survey-scribe convert questionnaire.pdf --prompt-api-key
```

## Behavior Changes

| Legacy entry point | Installed command |
| --- | --- |
| PDF input only | PDF, DOCX, XLSX/XLSForm, CSV, HTML, Markdown, and text |
| Replaces output | Refuses collisions unless `--overwrite` is explicit |
| Legacy projection only | Versioned main, sidecar, manifest, pointer, and legacy projection |
| Exceptions summarized as one legacy error | Result status, diagnostic codes, failed-block count, and artifact paths |
| No batch command | Ordered batch conversion with one shared manifest |

`docling_pipeline.run(Path, Path) -> None` remains available. It preserves the
legacy projection name and overwrite behavior, emits a deprecation warning, and
uses the packaged public API lazily. The script is not part of the wheel.

Partial output is a normal result in the installed CLI. It exits zero by default
after writing its sidecar, or nonzero with `--strict`. Failed conversion and any
required write failure always exit nonzero.

Before replacing automation, test collision behavior and decide whether partial
results can continue the workflow. Legacy runs overwrite their projection. The
installed command requires `--overwrite` and retains immutable generations.
