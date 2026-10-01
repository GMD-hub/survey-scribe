# Hosting Survey Scribe as a Microsoft Foundry Coded Agent

This note documents the changes applied to the Survey Scribe package to run
it as a **Microsoft Foundry hosted agent** — a containerized, coded agent
deployed with the Azure Developer CLI (`azd`) into
[Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents).
Use it as a checklist when converting another package to the same hosting
model.

## What changed

| File | Purpose |
| --- | --- |
| [`azure.yaml`](../../azure.yaml) | Declares the `azd` project: a Foundry AI project (model deployment) plus a `hosted` agent service pointing at `src/survey_scribe`. |
| [`AGENTS.md`](../../AGENTS.md) | Points contributors and coding agents at the `azd ai agent` workflow instead of ad hoc scripts. |
| [`src/survey_scribe/main.py`](../../src/survey_scribe/main.py) | New agent entry point. Wraps `SurveyScribe` in an Agent Framework `Agent` served over the Responses protocol. `SURVEY_SCRIBE_MODEL_SOURCE` selects only the model backend; the file-input tool downloads the named questionnaire from blob storage regardless of backend. |
| [`src/survey_scribe/Dockerfile`](../../src/survey_scribe/Dockerfile) | Container definition used for the coded-agent build (headless system libraries + `pip install`). |
| [`src/survey_scribe/requirements.txt`](../../src/survey_scribe/requirements.txt) | Runtime dependency list scoped to the container build context (replaces the deleted root `requirements.txt`). |
| [`src/survey_scribe/.dockerignore`](../../src/survey_scribe/.dockerignore) | Keeps virtualenvs, caches, and `.env` out of the image. |
| [`src/survey_scribe/.azdignore`](../../src/survey_scribe/.azdignore) | Keeps `.env.example` out of the `azd` deployment package. |
| `requirements.txt` (root, deleted) | Superseded by `src/survey_scribe/requirements.txt` because the container build context is the agent project directory, not the repo root. |
| `.foundry/.deployment.json` | `azd`-managed metadata linking this workspace to a Foundry project id. Generated the first time `azd` provisions; do not hand-author it. |

## `azure.yaml`: declaring the agent service

`azd` needs one `azure.ai.project` service (the Foundry project and its model
deployment) and one `azure.ai.agent` service (the coded agent container):

```yaml
services:
  ai-project:
    host: azure.ai.project
    deployments:
      - name: gpt-5.4-mini
        model: { format: OpenAI, name: gpt-5.4-mini, version: '2026-03-17' }
        sku: { name: GlobalStandard, capacity: 10 }
  survey-scribe-package-agent:
    host: azure.ai.agent
    project: src/survey_scribe        # build context / project root
    language: python
    codeConfiguration:
      runtime: python_3_13
      entryPoint: main.py            # module invoked by CMD in the Dockerfile
    uses: [ai-project]
    kind: hosted
    protocols:
      - protocol: responses
        version: 2.0.0
    environmentVariables: [...]        # forwarded to the running container
    container:
      resources: { cpu: '2.0', memory: '4.0Gi' }
infra:
  provider: microsoft.foundry
```

Key points when adapting another package:

- `project` must point at the directory that contains the `Dockerfile`,
  `requirements.txt`, and entry point — this becomes the container build
  context.
- `protocols: responses` is required for a coded agent invoked through the
  Agent Framework's Responses API (`ResponsesHostServer`).
- `environmentVariables` is the only supported way to pass secrets/config
  into the container; the package itself never reads a checked-in `.env` at
  runtime in production (`load_dotenv()` is for local `azd ai agent run`
  only).

## `main.py`: adapting the package to a hosted agent

The package's public `SurveyScribe` facade is synchronous/async, file-in,
file-out. A hosted agent instead needs a conversational tool surface. `main.py`
bridges the two:

1. **Blob storage as the file boundary, both directions.** The agent takes
   only a *file name* from the user, downloads that file from the `input`
   prefix of a configured Azure Storage container
   (`AZURE_STORAGE_ACCOUNT_URL` / `AZURE_STORAGE_CONTAINER_NAME`), and
   uploads the resulting SVIS output artifacts back under the `output`
   prefix. There is no local-path or base64-upload input mode — the caller
   is expected to have already placed the questionnaire in the input folder
   (for example via `azd ai agent files upload` into the container, or an
   out-of-band upload to the storage account) before asking the agent to
   convert it.
2. **One tool function.** `convert_questionnaire(file_name)` resolves the
   blob at `input/<file_name>` with `_download_questionnaire`, stages it to a
   temporary directory, and calls `SurveyScribe.convert(...)` — the same call
   an application would make when using the package directly. If the blob
   does not exist, `_download_questionnaire` catches
   `azure.core.exceptions.ResourceNotFoundError` and raises a `RuntimeError`
   naming the resolved blob path, which becomes the tool-call error the model
   relays back to the user.
3. **`SURVEY_SCRIBE_MODEL_SOURCE` now only selects the extraction model
   backend** — it no longer changes the input mechanism:
   - `foundry` (default): uses the Foundry project's own model deployment via
     a `DefaultAzureCredential` token callback (Cognitive Services scope).
   - `mai`: builds an `AzureOpenAIProvider` pointed at a private mAI Factory
     gateway (for parity with the package's existing
     [mAI Factory integration](../integrations/mai-factory.md)).
4. **Errors are redacted before they reach the model.** `redact_exception` (an
   existing package API) prevents leaking credentials or raw provider
   payloads through the agent's tool-call response.
5. **The chat model and the agent are separate concerns.** `main()` builds a
   `FoundryChatClient` (the conversational model backing the `Agent`) from
   `AZURE_AI_MODEL_DEPLOYMENT_NAME`/`FOUNDRY_PROJECT_ENDPOINT`, independent of
   whichever model `SurveyScribe` itself uses for extraction. `store=False` in
   `default_options` disables server-side history because the hosting
   infrastructure already manages conversation state. The agent's
   instructions tell it to ask the user for a file name already present in
   the input folder and to relay the not-found error verbatim so the user can
   correct the name or re-upload.
6. **`ResponsesHostServer(agent).run()`** is the only line that talks to the
   Foundry hosting runtime — it starts the HTTP server the platform expects
   on port `8088`.

## `Dockerfile`: container build

```dockerfile
FROM python:3.13-slim
RUN apt-get install ... libgl1 libglib2.0-0 ...   # headless Docling/OpenCV deps
COPY . user_agent/
WORKDIR /app/user_agent
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt
EXPOSE 8088
CMD ["python", "main.py"]
```

Notes:

- The native libraries are required because Docling/OpenCV need a graphics
  stack even though the container never renders anything — omit them and PDF
  conversion fails at import time.
- The CPU-only PyTorch index avoids pulling multi-gigabyte CUDA wheels into a
  container that has no GPU.
- Build context is the whole `project` directory (`src/survey_scribe`), so
  anything the entry point imports from the package must be installable from
  that same `requirements.txt` (or vendored). `.dockerignore` trims caches and
  local secrets from that context.

## `requirements.txt`: hosted-agent dependency set

The root `requirements.txt` was deleted and its contents merged into
`src/survey_scribe/requirements.txt`, because the Docker build context is the
agent project directory, not the repository root — a requirements file
outside that context is invisible to the build. The new file adds hosting-only
dependencies on top of the existing pipeline dependencies:

```text
# Hosted agent runtime
azure-ai-agentserver-responses>=2.2.0b1,<3
azure-identity==1.25.3
agent-framework-foundry
agent-framework-foundry-hosting>=1.0.0a260630
debugpy>=1.8.14            # local debugging via the Foundry Toolkit VS Code extension

# Core pipeline (unchanged from the package's own requirements)
docling>=2.0.0
openai>=1.0.0
instructor>=1.0.0
...
azure-storage-blob>=12.23.0  # blob IO added for input/output archiving
```

## `AGENTS.md`: documenting the new workflow

Replaces bespoke run/test instructions with the standard `azd` lifecycle so
any contributor or coding agent knows how to iterate locally and deploy:

```bash
azd ai agent run                           # http://localhost:8088
azd ai agent invoke --local "your message"
azd deploy
azd ai agent invoke "your message"
```

## Converting another package with this pattern

1. Add an `azure.ai.agent` service to `azure.yaml` with `project` pointing at
   a directory containing a `Dockerfile`, `requirements.txt`, and an entry
   point module.
2. Write a `main.py` that:
   - Loads config/secrets from environment variables only (no checked-in
     secrets in the image).
   - Exposes the package's existing public API as one or more `Agent` tool
     functions — don't reimplement business logic in the agent layer.
   - Builds a `FoundryChatClient`, wraps it with `Agent(...)`, and serves it
     with `ResponsesHostServer(agent).run()`.
3. Add a `Dockerfile` that installs from a requirements file colocated with
   the entry point, exposes port `8088`, and runs `python main.py`.
4. Add `.dockerignore`/`.azdignore` to keep local artifacts and secrets out of
   the image and deployment package.
5. Update `AGENTS.md` to describe the `azd ai agent` workflow instead of any
   previous run/debug instructions.
