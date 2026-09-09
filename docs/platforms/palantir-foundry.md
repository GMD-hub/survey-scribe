# Palantir Foundry

Survey Scribe does not ship or test a Palantir Foundry adapter. The package can
run as ordinary Python code only after a Foundry repository supplies the package,
materializes questionnaire files, and publishes the generated artifacts.

This page adapts Survey Scribe to the dataset filesystem pattern in Palantir's
public documentation. The repository has not run this pattern in Palantir. It
does not declare general Palantir production support.

!!! warning "Current support status"

    No Palantir SDK, Transform, Ontology, media-set, secret-store, or deployment
    integration exists in `survey_scribe`. Model-assisted extraction also needs
    a tested transport adapter for Foundry-managed external connections.

## Compatibility matrix

| Path | Status | Reason |
| --- | --- | --- |
| XLSForm dataset to routed and SVIS artifacts | Conditional | Uses documentation-derived Foundry dataset filesystem APIs and tested provider-free Survey Scribe APIs |
| PDF or DOCX normalization without a provider | Conditional | File materialization works, but PDF needs approved local OCR artifacts |
| Model-assisted extraction with built-in provider | Not verified | Palantir documents a source-managed synchronous client; Survey Scribe providers use async SDK clients |
| Palantir media-set transform | Not documented here | The code below is scoped to dataset `Input` and `Output` objects only |
| Palantir Python Function | Not recommended for this workflow | The file and artifact workflow is designed as a batch transform |

## Prerequisites

1. Create a Palantir Code Repository of type **Pipelines** with Python.
2. Use Python 3.11 or 3.12. These versions are supported by both platforms.
3. Make Survey Scribe and its dependencies available through an approved Foundry library repository.
4. Add the required package through the **Libraries** panel so that it enters `conda_recipe/meta.yaml` and the lock.
5. Add `openpyxl` through the `tabular` dependency set for XLSForm input.
6. Create one unstructured input dataset and one unstructured output dataset.
7. Grant the repository access to both datasets.

No approved PyPI release exists. Palantir's public library guide does not
document direct wheel installation. An administrator must first publish an
approved Conda-compatible Survey Scribe artifact to a library source that your
repository can access.

## End-to-end native XLSForm transform

The following transform requires exactly one `.xlsx` file in the input dataset.
It copies the non-seekable Foundry stream to a local file, runs provider-free
native extraction, creates the Survey Scribe artifact set, and writes each file
to the output dataset.

Replace the resource paths with your approved dataset identifiers.

```python
import shutil
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO

from transforms.api import Input, Output, transform

from survey_scribe import QuestionnaireRouter, ResultStatus
from survey_scribe.sources import SourceLimits, SourceRegistry


def copy_bounded(source: BinaryIO, target: BinaryIO, *, max_bytes: int) -> None:
    copied = 0
    while chunk := source.read(1024 * 1024):
        copied += len(chunk)
        if copied > max_bytes:
            raise RuntimeError("Questionnaire exceeds the configured byte limit")
        target.write(chunk)


@transform.using(
    questionnaires=Input("<questionnaire-input-dataset>"),
    artifacts=Output("<survey-scribe-output-dataset>"),
)
def compute(questionnaires, artifacts) -> None:
    input_fs = questionnaires.filesystem()
    output_fs = artifacts.filesystem()
    input_files = tuple(input_fs.ls(glob="*.xlsx"))

    if len(input_files) != 1:
        raise RuntimeError("Expected exactly one XLSForm workbook")

    limits = SourceLimits(max_source_bytes=50 * 1024 * 1024)
    if input_files[0].size > limits.max_source_bytes:
        raise RuntimeError("Questionnaire exceeds the configured byte limit")

    with TemporaryDirectory() as temporary_directory:
        workspace = Path(temporary_directory).resolve()
        local_source = workspace / "questionnaire.xlsx"
        local_output = (workspace / "artifacts").resolve()

        with input_fs.open(input_files[0].path, "rb") as source_stream:
            with local_source.open("wb") as local_stream:
                copy_bounded(
                    source_stream,
                    local_stream,
                    max_bytes=limits.max_source_bytes,
                )

        registry = SourceRegistry.default()
        conversion = registry.convert_for_svis(
            local_source,
            extraction_date=date.today(),
            limits=limits,
        )
        if conversion.svis is None:
            raise RuntimeError("Input workbook is not a supported XLSForm")

        source_conversion = registry.convert_with_native(
            local_source,
            conversion.svis,
            limits=limits,
        )
        result = QuestionnaireRouter(None, sources=registry).route(
            local_source,
            conversion.svis,
            source_binding=source_conversion.source_binding,
        )
        if result.status is not ResultStatus.success or result.diagnostics:
            codes = tuple(item.code for item in result.diagnostics)
            raise RuntimeError(f"Review native extraction before publication: {codes}")

        written = result.write(local_output)
        for reference in written.artifacts:
            relative_path = reference.path.relative_to(local_output).as_posix()
            with reference.path.open("rb") as local_stream:
                with output_fs.open(relative_path, "wb") as output_stream:
                    shutil.copyfileobj(local_stream, output_stream)
```

Palantir documents `TransformInput.filesystem()` as read-only and
`TransformOutput.filesystem()` as write-only. Its input streams do not support
`seek()` or `tell()`. Survey Scribe requires a local path and XLSX readers need
random access, so the temporary copy is required. The example checks the
Palantir-reported size before copying and enforces the same byte limit while it
copies and parses.

For reproducible metadata, replace `date.today()` with a date that comes from
your versioned pipeline configuration.

## Build and verify

1. Commit the repository change.
2. Confirm that Foundry resolves the package and `openpyxl` in the locked environment.
3. Run the transform against a synthetic XLSForm first.
4. Verify that the output has a stable `<survey_id>_svis.json` and a `.survey-scribe/` generation tree.
5. Parse the generated `manifest.json` with `parse_artifact_manifest()` in a repository unit test.
6. Add dataset health checks for a missing stable projection or manifest.
7. Schedule the build only after the synthetic test passes.

The transform fails closed when the input count is not one, the workbook is too
large, the workbook is not an XLSForm, extraction or routing needs review,
source validation fails, or artifact publication fails.

## Process more than one file

For a bounded set, iterate over `input_fs.ls(glob="*.xlsx")` and materialize one
file at a time. Use unique local names and preserve each input path in an
application audit table. Survey Scribe rejects duplicate active survey identities
unless overwrite is explicit.

Palantir documents a thread-pool pattern and a distributed
`filesystem().files()` Spark DataFrame. Do not add either until you set a global
provider and memory limit. Survey Scribe's own limiter is per conversion or
batch, not process-global.

## Model-assisted extraction boundary

Palantir external transforms use an imported Data Connection source and the
`@external_systems` decorator. The built-in source client is a preconfigured
`requests.Session`. A source can also provide a synchronous proxy URI for a
custom client.

Survey Scribe's built-in OpenAI, Azure, and Anthropic adapters create their own
asynchronous SDK clients. They do not accept a Palantir `ResolvedSource` or the
source-managed `requests.Session`. The public Palantir documentation checked for
this guide does not establish async OpenAI or Azure SDK compatibility with that
connection mechanism.

Use model-assisted extraction in Palantir only after you implement and test an
application-owned `StructuredProvider` that:

- Uses the imported Foundry source connection and its approved egress policy.
- Retrieves secrets with the source API and never stores them in package configuration.
- Preserves Foundry proxy and certificate behavior.
- Implements Survey Scribe strict-schema, retry, usage, and error contracts.
- Has offline tests and one authorized live contract test for the exact endpoint.

Do not pass a source secret to `metadata_headers`. Do not assume that the
`AzureOpenAIProvider` token callback routes SDK traffic through a Foundry source.

## Export controls

Palantir treats a transform that combines Foundry input data and an open external
connection as export-capable. The source owner must enable exports and authorize
the applicable markings and organizations, even when the code does not intend to
send input content.

This platform control is separate from Survey Scribe. Survey Scribe cannot
configure Foundry egress, export markings, source permissions, certificates, or
secret storage.

## Operations checklist

- Pin the Survey Scribe artifact and all resolved dependencies.
- Use one approved Python version for build and test.
- Keep input and primary output datasets access-controlled.
- Set smaller `SourceLimits` for shared compute.
- Keep temporary files inside the transform lifetime.
- Do not log questionnaire blocks, routed quotes, tokens, or output payloads.
- Test collision and partial-result policy before scheduling.
- Monitor failed builds and missing manifests.
- Revalidate package and Palantir runtime compatibility before upgrades.

## Official Palantir references

- [Python transforms: Getting started](https://www.palantir.com/docs/foundry/transforms-python/getting-started/)
- [Discover and use Python libraries](https://www.palantir.com/docs/foundry/transforms-python/use-python-libraries/)
- [Python version support](https://www.palantir.com/docs/foundry/transforms-python/python-versions/)
- [Unstructured files](https://www.palantir.com/docs/foundry/transforms-python/unstructured-files/)
- [External transforms](https://www.palantir.com/docs/foundry/data-connection/external-transforms/)

See [Questionnaire Extraction](../guides/extraction.md) for package behavior and
[Features and Limitations](../project/features.md) for the current support state.
