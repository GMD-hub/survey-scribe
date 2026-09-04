# Command Line

The installed `survey-scribe` command converts local questionnaires, validates
configuration, lists supported provider adapters, and exports public schemas.

## Convert One Source

Set provider configuration with environment variables or a non-secret TOML file:

```console
export SURVEY_SCRIBE_PROVIDER=openai
export SURVEY_SCRIBE_MODEL=gpt-model-name
export OPENAI_API_KEY=your-key
survey-scribe convert questionnaire.pdf --output-dir output
```

Use `--prompt-api-key` or `--prompt-bearer-token` to read a credential without
terminal echo. Credential values are not accepted as command arguments and are
never written to status output or manifests.

The command writes a main JSON artifact, diagnostic sidecar, per-result manifest,
active-generation pointer, and legacy `<survey_id>_svis.json` projection. Existing
artifacts cause a nonzero collision exit unless `--overwrite` is present.

`--no-sidecar` is valid only for a successful result. A partial result always
requires its sidecar. Manifests cannot be disabled.

## Convert A Batch

```console
survey-scribe batch questionnaire-a.pdf questionnaire-b.xlsx \
  --output-dir output
```

Batch conversion preserves input order and applies the configured global
concurrency limit. In addition to each successful or partial result's artifact
set, the command writes `output/batch_manifest.json`. This shared manifest has
one batch run identifier and one ordered record per input. It includes outcome,
diagnostic codes, failed-block count, and artifact digests. It excludes
credentials, diagnostic prose, and questionnaire content.

The batch manifest follows the same collision rule as result artifacts. Use
`--overwrite` to replace it for a later run.

## Exit Status

| Command result | Default | `--strict` |
| --- | ---: | ---: |
| Single success | 0 | 0 |
| Single partial | 0 | nonzero |
| Single failed | nonzero | nonzero |
| Batch with success and partial only | 0 | nonzero when partial exists |
| Batch with any failed result | nonzero | nonzero |
| Required artifact write failure | nonzero | nonzero |

`success` means usable output with no operational failure. `partial` means usable
output plus a failed source unit, failed provider chunk, truncation, validation
failure, or equivalent error diagnostic. `failed` means there is no usable
output. Review warnings such as low confidence do not by themselves make a result
partial. See [Results and Artifacts](guides/results.md#status-rules).

Representative summaries are:

```text
status=success survey_id=SYN_2026_HHS diagnostics=0 failed_blocks=0
status=partial survey_id=SYN_2026_HHS diagnostics=1 codes=SOURCE_UNREADABLE failed_blocks=1
status=failed survey_id=<none> diagnostics=1 codes=PROVIDER_FAILED failed_blocks=1
```

## Check Configuration

```console
survey-scribe config check
survey-scribe config check --config ./settings.toml --provider azure
```

The command validates the complete provider construction without making a model
request. It reports only provider and model identity plus whether a credential is
configured.

CLI precedence, from highest to lowest, is:

1. Explicit flags and a non-echo credential prompt.
2. Generic `SURVEY_SCRIBE_*` environment variables.
3. Provider-standard environment variables.
4. Explicit `--config PATH`.
5. `./survey-scribe.toml`.
6. Package defaults.

No parent or home directory is searched.

See [Configuration](guides/configuration.md) for every setting and environment
name, and [Provider Contracts](reference/providers.md) for the evidence boundary
of each adapter.

## List Providers

```console
survey-scribe providers
```

The output distinguishes reviewed OpenAI-compatible presets, an explicit custom
gateway, and dedicated adapters. Current model capability rows are
`configuration-only`; no live model/version row is advertised as verified.

## Export A Schema

```console
survey-scribe schema export routing > questionnaire-routing-graph-v1.0.json
```

Schema export does not read configuration or credentials and writes only the
canonical JSON Schema to standard output.
