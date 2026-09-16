# Survey Scribe Foundry Hosted Agent

Survey Scribe is a Python-based Microsoft Foundry hosted agent that extracts structured Survey Variable Information System (SVIS) metadata and variables from questionnaire PDFs. A user supplies a PDF file name; the agent reads the source document from Azure Blob Storage, processes it with Docling and an LLM constrained by Pydantic schemas, then writes the JSON result to Blob Storage.

## Solution flow

1. Send a PDF file name to the agent through the Foundry Responses protocol.
2. [`main.py`](src/survey-scribe/main.py) validates the input and invokes the extraction workflow.
3. [`foundry_blob_agent.py`](src/survey-scribe/foundry_blob_agent.py) downloads `input/<file-name>` from the configured Blob container using `DefaultAzureCredential`.
4. [`docling_pipeline.py`](src/survey-scribe/docling_pipeline.py) and the SVIS extraction agent convert the PDF into schema-validated JSON.
5. The result is uploaded as `output/<file-stem>_result.json` in the same Blob container.

## Foundry hosted-agent integration

The Azure Developer CLI (`azd`) and Foundry Toolkit use [`azure.yaml`](azure.yaml) to package and deploy this project as a containerized hosted agent.

| Artifact | Purpose |
| --- | --- |
| [`azure.yaml`](azure.yaml) | Declares the Foundry project, the `azure.ai.agent` hosted service, the Responses protocol, agent name, runtime resources, environment variables, and Docker build path. |
| [`.foundry/.deployment.json`](.foundry/.deployment.json) | Foundry Toolkit deployment metadata, including the selected container deployment mode and container registry. |
| [`src/survey-scribe/Dockerfile`](src/survey-scribe/Dockerfile) | Creates the Python 3.13 container, installs native Docling dependencies and Python packages, exposes port `8088`, and starts the agent. |
| [`src/survey-scribe/main.py`](src/survey-scribe/main.py) | Implements the Foundry Responses server contract through `azure-ai-agentserver-responses`. |
| [`src/survey-scribe/requirements.txt`](src/survey-scribe/requirements.txt) | Lists the hosted-agent runtime dependencies. |
| [`src/survey-scribe/.dockerignore`](src/survey-scribe/.dockerignore) | Prevents local files, including `.env`, from being copied into the container image. |

At deployment, Foundry builds the image, pushes it to the configured registry, and hosts the Responses-compatible agent. The hosted runtime supplies a managed identity; grant that identity Blob Data Contributor access to the target storage container or account so the agent can read input PDFs and write results.

## Run and deploy

Prerequisites:

- Python 3.13 and Docker Desktop.
- Azure CLI, Azure Developer CLI (`azd`), and the `azure.ai.agents` `azd` extension.
- An authenticated Azure account with access to the Foundry project, container registry, and storage account.

From the repository root:

```powershell
azd ai agent run
azd ai agent invoke --local "questionnaire.pdf"
azd deploy
azd ai agent invoke "questionnaire.pdf"
```

The local agent listens on `http://localhost:8088`. Use the exact blob file name stored below the `input/` prefix.

## Scaffold a new Foundry hosted agent in VS Code

1. Install the Microsoft Foundry extension (Foundry Toolkit) in VS Code and sign in to Azure.
2. Open the Command Palette with `Ctrl+Shift+P`, run `Foundry: Create Agent`, and select **Hosted agent**.
3. Choose Python and the **Responses** protocol, then select or create a Foundry project.
4. Let the toolkit create the agent project and its `azure.yaml`, `.foundry` metadata, Dockerfile, Python entry point, and dependency manifest.
5. Implement the response handler in the generated entry point, add runtime packages to `requirements.txt`, and configure only non-secret settings in `azure.yaml`.
6. Test with `azd ai agent run` and `azd ai agent invoke --local`, then deploy with `azd deploy`.


## Security and configuration

Before running or deploying this solution outside its current environment, replace all environment-specific configuration and secrets. In particular, [`src/survey-scribe/agents/svis_agent.py`](src/survey-scribe/agents/svis_agent.py) currently contains a hard-coded Azure API key, which must be revoked/rotated and replaced with a secret managed outside source control, such as a Key Vault-backed configuration or managed-identity authentication. Do not commit `.env` files, storage keys, connection strings, API keys, tokens, or customer survey documents.

The storage account and container names in [`foundry_blob_agent.py`](src/survey-scribe/foundry_blob_agent.py) are deployment-specific and must also be changed for the target environment.

## Test

Install the test dependency, then run the schema test from the agent directory:

```powershell
python -m pip install pytest
python -m pytest tests/test_schema.py
```
