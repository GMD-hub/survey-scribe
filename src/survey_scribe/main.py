# Copyright (c) Microsoft. All rights reserved.

import asyncio
import os
import tempfile
from pathlib import Path

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient
from dotenv import load_dotenv

from survey_scribe import SurveyScribe
from survey_scribe.errors import redact_exception
from survey_scribe.models.svis import SurveySVIS
from survey_scribe.providers import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.azure import AzureOpenAIProvider
from survey_scribe.results import ExtractionResult, ResultStatus

# Load environment variables from .env file
load_dotenv()

# Azure OpenAI-compatible scope used to mint tokens for the extraction model.
_MODEL_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"

_INPUT_FOLDER = "input"
_OUTPUT_FOLDER = "output"

# Selects which backend serves the extraction model. "foundry" means running
# as a Foundry hosted agent: use the Foundry project's own model deployment
# via a token callback. "mai" means a private mAI Factory Azure OpenAI-
# compatible gateway. The questionnaire input mechanism (download by file
# name from blob storage) is the same in both modes.
_MODEL_SOURCE_ENV = "SURVEY_SCRIBE_MODEL_SOURCE"
_MODEL_SOURCE_FOUNDRY = "foundry"
_MODEL_SOURCE_MAI = "mai"


def _model_source() -> str:
    source = os.getenv(_MODEL_SOURCE_ENV, _MODEL_SOURCE_FOUNDRY).strip().lower()
    if source not in (_MODEL_SOURCE_FOUNDRY, _MODEL_SOURCE_MAI):
        raise RuntimeError(
            f"{_MODEL_SOURCE_ENV} must be '{_MODEL_SOURCE_FOUNDRY}' or '{_MODEL_SOURCE_MAI}', "
            f"got '{source}'."
        )
    return source


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not configured. Set it in the environment or .env file.")
    return value


def _container_client() -> ContainerClient:
    account_url = _require_env("AZURE_STORAGE_ACCOUNT_URL")
    container_name = _require_env("AZURE_STORAGE_CONTAINER_NAME")
    return ContainerClient(
        account_url=account_url,
        container_name=container_name,
        credential=DefaultAzureCredential(),
    )


def _upload_file(container: ContainerClient, folder: str, path: Path) -> str:
    blob_name = f"{folder}/{path.name}"
    with path.open("rb") as handle:
        container.upload_blob(name=blob_name, data=handle, overwrite=True)
    return blob_name


def _survey_scribe_client(credential: DefaultAzureCredential) -> SurveyScribe:
    if _model_source() == _MODEL_SOURCE_MAI:
        return SurveyScribe(_mai_provider(credential))

    def _token_callback() -> str:
        return credential.get_token(_MODEL_TOKEN_SCOPE).token

    return SurveyScribe(token_callback=_token_callback, resolve_environment=True)


def _mai_provider(credential: DefaultAzureCredential) -> AzureOpenAIProvider:
    deployment = _require_env("MAI_API_DEPLOYMENT")
    token_scope = os.getenv("MAI_API_TOKEN_SCOPE", _MODEL_TOKEN_SCOPE)

    def _token_callback() -> str:
        return credential.get_token(token_scope).token

    capabilities = ModelCapabilities(
        provider="azure_openai",
        model=deployment,
        structured_output=True,
        strict_schema=True,
        max_input_tokens=32_000,
        max_output_tokens=4_096,
        supported_generation_settings=frozenset({"temperature", "max_output_tokens", "seed"}),
        evidence=CapabilityEvidence.configuration_only,
        tested_sdk_version="application-managed",
    )
    return AzureOpenAIProvider(
        deployment=deployment,
        azure_endpoint=_require_env("MAI_API_ENDPOINT"),
        api_version=_require_env("MAI_API_VERSION"),
        token_callback=_token_callback,
        capabilities=capabilities,
    )


def _download_questionnaire(container: ContainerClient, file_name: str, destination_dir: Path) -> Path:
    """Download a questionnaire from the input folder, raising a clear error if absent."""
    name = Path(file_name).name
    if not name:
        raise RuntimeError("file_name must not be empty.")

    blob_name = f"{_INPUT_FOLDER}/{name}"
    destination = destination_dir / name
    try:
        with destination.open("wb") as handle:
            container.download_blob(blob_name).readinto(handle)
    except ResourceNotFoundError:
        raise RuntimeError(
            f"Questionnaire file not found in storage: '{blob_name}'. Verify the file "
            "name and that it was uploaded to the input folder."
        ) from None
    return destination


def convert_questionnaire(file_name: str) -> str:
    """Convert a questionnaire already staged in blob storage to SVIS.

    Downloads the named file from the `input` folder of the configured
    storage container, runs the Survey Scribe extraction pipeline against it,
    and uploads the resulting SVIS artifacts into the container's `output`
    folder.

    Args:
        file_name: Questionnaire file name, including extension, as it exists
            under the storage container's `input` folder.

    Returns:
        A status summary naming the extraction status, survey identifier, and
        the blob paths for the archived output artifacts, or an `error=`
        message describing what went wrong. Errors are returned rather than
        raised because the hosting framework replaces a raised tool-call
        exception with a generic "Function failed." message, hiding the
        detail the agent is instructed to relay to the user.
    """
    try:
        container = _container_client()
        with tempfile.TemporaryDirectory() as staging_dir:
            source = _download_questionnaire(container, file_name, Path(staging_dir))

            credential = DefaultAzureCredential()

            async def _convert() -> ExtractionResult[SurveySVIS]:
                # Run conversion and provider teardown in one event loop; the
                # provider's async HTTP client is loop-bound, so opening it in
                # convert() and closing it in a later asyncio.run() call would
                # raise "RuntimeError: Event loop is closed".
                async with _survey_scribe_client(credential) as client:
                    return await client.aconvert(source)

            try:
                result = asyncio.run(_convert())
            except Exception as error:
                raise RuntimeError(redact_exception(error)) from None

            if result.status is ResultStatus.failed:
                details = "; ".join(
                    f"{diagnostic.code}: {diagnostic.message}" for diagnostic in result.diagnostics
                )
                raise RuntimeError(
                    f"Extraction produced no usable output (diagnostics={details or '<none>'})."
                )

            written = result.write(staging_dir, sidecar=True, overwrite=True)
            output_blobs = [
                _upload_file(container, _OUTPUT_FOLDER, artifact.path)
                for artifact in written.artifacts
            ]
    except Exception as error:
        return f"error={error}"

    return (
        f"status={written.status.value} survey_id={written.survey_id or '<none>'} "
        f"output_blobs={','.join(output_blobs)}"
    )


def main():
    model_name = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME") or os.getenv("FOUNDRY_MODEL_NAME")
    if not model_name:
        raise RuntimeError(
            "Model deployment name is not configured. Set "
            "AZURE_AI_MODEL_DEPLOYMENT_NAME or FOUNDRY_MODEL_NAME."
        )

    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=model_name,
        credential=DefaultAzureCredential(),
    )

    tools = convert_questionnaire
    instructions = (
        "You are a survey scribing assistant. Ask the user for the file name "
        "of a questionnaire, including its extension, that is already "
        "available in the input folder of the configured Azure Storage "
        "container. Call convert_questionnaire with that file name to "
        "download it, extract its SVIS, and archive the results. Report the "
        "returned status, survey id, and output blob locations. If the file "
        "cannot be found, relay the returned error so the user can verify "
        "the file name and re-upload if needed. Keep other answers brief."
    )

    agent = Agent(
        client=client,
        instructions=instructions,
        tools=tools,
        # History will be managed by the hosting infrastructure, thus there
        # is no need to store history by the service. Learn more at:
        # https://developers.openai.com/api/reference/resources/responses/methods/create
        default_options={"store": False},
    )

    server = ResponsesHostServer(agent)
    server.run()


if __name__ == "__main__":
    main()
