# Deployment guide

> From a local machine (offline mode, no Azure credentials) all the way to a
> full deployment on Azure Container Apps via `azd`. For the demo's own
> configuration, see [`demo-guide.md`](demo-guide.md).

## 1. Prerequisites

| Scenario | Prerequisites |
|----------|-----------|
| Local dev, offline mode (`StubChatClient`) | Python 3.11+, Node.js 20+ (for the web UI) — **no Azure credentials** |
| Local dev against real Azure OpenAI / AI Search / Cosmos | + `az login` (Azure CLI), access to the resources |
| Docker | Docker (multi-stage build: Node 20 then Python 3.11) |
| Azure deployment | [Azure Developer CLI (`azd`)](https://aka.ms/azd), Azure subscription |

No Azure credentials are required to run the demo: as long as
`AZURE_OPENAI_ENDPOINT` is not configured with a real endpoint (or stays the
placeholder from `.env.example`), `Settings.use_real_azure_openai` is false
and every agent uses `StubChatClient` (`src/agents/clients.py`), which is
deterministic and makes no network calls.

## 2. Local development

### 2.1 Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 2.2 CLI

```bash
python -m src.main --logs data/payment-incident.log
```

Streams every agent output, including the reflection loop, then stops at the
HITL gate:

```
Approve proceeding to remediation? [y/N]:
```

- `y` / `yes` → `RemediationPlan` then `IncidentReport` displayed.
- Any other answer (or EOF / non-interactive input) → immediate stop, no
  plan or report.

### 2.3 Web interface (FastAPI + React)

Two processes in development:

```bash
# Terminal 1: API (port 8000)
pip install -e ".[dev]"
uvicorn src.api.app:app --reload

# Terminal 2: frontend (port 5173, proxy /api -> :8000 via vite.config.ts)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173:
- "Run diagnosis" → `POST /api/runs` (SSE), animates the `PipelineHUD`
  (8-node SVG pipeline: the six agents, the `GatherEvidence` loop node, and
  the `HumanApproval` diamond) as `step` events arrive, with a scrolling
  `ActivityFeed` ("Orchestration Log") alongside it, and a `DetailPanel`
  showing each agent's detailed structured output.
- At the HITL gate, the `ApprovalCard` (embedded inside `DetailPanel` at the
  human-approval step) is displayed → Approve/Reject calls
  `POST /api/runs/{run_id}/approval`.
- "History" tab → `GET /api/history` / `GET /api/history/{run_id}`
  (`src/tools/persistence.py`).

## 3. Configuration reference

All configuration goes through the environment / `.env` (see
`.env.example`), loaded by `src/config.py::Settings` (pydantic-settings).
**Nothing is hardcoded**, and `.env` stays out of the git repo
(`.gitignore`) — only `.env.example` is versioned.

| Variable | Role | Default |
|----------|------|--------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI / Foundry endpoint. Absent or placeholder → `StubChatClient` | _(none)_ |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | "Strong" deployment (`RootCause`, `Remediation`) | `gpt-4o` |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT` | "Light" deployment (other agents) | `gpt-4o-mini` |
| `AZURE_OPENAI_API_VERSION` | Azure OpenAI API version | `2024-10-21` |
| `AZURE_AUTH_MODE` | `cli` (local, `az login` → `AzureCliCredential`) or `managed_identity` (deployed → `DefaultAzureCredential`) | `cli` |
| `AZURE_AI_SEARCH_ENDPOINT` | Azure AI Search endpoint (`azure_search` mode) | _(none)_ |
| `AZURE_AI_SEARCH_INDEX` | Azure AI Search index name | `incident-kb` |
| `KB_MODE` | `local` (`data/knowledge_base.json`) or `azure_search` | `local` |
| `COSMOS_ENDPOINT` | Cosmos DB endpoint. Absent → local persistence (`output/runs/`) | _(none)_ |
| `COSMOS_DATABASE` | Cosmos DB database | `incidents` |
| `COSMOS_CONTAINER` | Cosmos DB container (partition key `/id`) | `records` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights connection string — enables OTel instrumentation (`src/observability.py`, §8.12). Absent → no-op (offline mode) | _(none)_ |
| `CONFIDENCE_THRESHOLD` | `RootCause` confidence threshold | `0.75` |
| `MAX_REFLECTION_LOOPS` | Max number of `RootCause ↔ GatherEvidence` reflection loops | `2` |
| `AZURE_FOUNDRY_PROJECT_ENDPOINT` | Microsoft Foundry project endpoint (`scripts/register_foundry_agents.py` only, §8.13 — unrelated to actually running the agents) | _(none)_ |

`GET /api/meta` exposes the non-sensitive subset to the UI:
`confidence_threshold`, `max_reflection_loops`, `kb_mode`,
`use_real_azure_openai`, `cosmos_enabled`.

## 4. Switching to Azure OpenAI (real models)

1. `az login` (`AZURE_AUTH_MODE=cli` mode, the local default).
2. Set in `.env`: `AZURE_OPENAI_ENDPOINT` (a real endpoint, not starting
   with `https://<`) and the deployment names
   (`AZURE_OPENAI_CHAT_DEPLOYMENT`, `AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT`).
3. `python -m src.main` (or the API) then uses
   `AzureOpenAIStructuredChatClient` (`src/agents/clients.py`) — same
   agents, same pydantic contracts, JSON output forced via
   `response_format`.

> With real models, the outputs (in particular the `confiance` scores) are
> **no longer guaranteed to be identical** to the fixed `StubChatClient`
> scenario — see [`demo-guide.md`](demo-guide.md) "Variant: real Azure
> OpenAI".

## 5. Switching the knowledge base to Azure AI Search

1. Create an Azure AI Search index and load `data/knowledge_base.json`
   into it (see `SPEC.md` §7 for the schema).
2. Set in `.env`: `KB_MODE=azure_search`, `AZURE_AI_SEARCH_ENDPOINT`,
   `AZURE_AI_SEARCH_INDEX`.
3. `get_knowledge_base()` (`src/tools/knowledge_base.py`) automatically
   switches to `AzureAISearchKnowledgeBase`, which implements the same
   `KnowledgeBase` interface as `LocalKnowledgeBase`.

> Note: `azd up` provisions the Azure AI Search index **empty** (no
> indexing pipeline). `KB_MODE` stays `local` even after deployment, as
> long as `data/knowledge_base.json` has not been indexed manually —
> otherwise `KBSearch` would return no precedent at all (see
> `DECISIONS.md` #22).

## 6. Persistence: local vs Cosmos DB

- **By default** (`COSMOS_ENDPOINT` absent): `LocalPersistenceStore` writes
  one JSON file per run under `output/runs/`.
- **If `COSMOS_ENDPOINT` is set**: `CosmosPersistenceStore` (one document
  per run, partition key `/id`). The account/database/container are
  provisioned by `infra/` (azd) — the application code only does data-plane
  operations (`upsert_item`/`read_item`/`query_items`).

## 7. Containerization (Docker)

```bash
docker build -t incident-rca-agents .
docker run --rm -it -p 8000:8000 incident-rca-agents
```

Open http://localhost:8000 — the image (multi-stage build, `Dockerfile`)
serves the API **and** the built UI (`frontend/dist/`) on the same port via
a single `uvicorn src.api.app:app` process.

- **Stage 1** (`node:20-slim`): `npm ci && npm run build` in `frontend/` →
  produces `frontend/dist/`.
- **Stage 2** (`python:3.11-slim`): `pip install -e .` (keeps
  `src.config.REPO_ROOT` aligned with `/app`, where `data/` is copied — the
  default paths `data/payment-incident.log` and `data/knowledge_base.json`
  work with no configuration) then copies `frontend/dist/` from stage 1.

`AZURE_AUTH_MODE=managed_identity` is set by default in the image (for a
Container Apps deployment with managed identity). To point at real Azure
resources, pass the `AZURE_*` variables via `docker run -e ...` or
Container Apps secrets. Locally, offline (without
`AZURE_OPENAI_ENDPOINT`), `StubChatClient` is used and **no variable is
required**.

## 8. Deployment to Azure (`azd`) — step-by-step guide

`infra/` (Bicep) + `azure.yaml` provision the target architecture described
by `CLAUDE.md` and deploy the Docker image (§7) to **Azure Container
Apps**, in a single command (`azd up`). This section is a step-by-step
guide, from a blank Azure account all the way to the public URL.

### 8.1 Before you start (prerequisites)

| Prerequisite | Detail |
|---|---|
| Azure subscription | Sufficient rights to create a resource group and role assignments (*Owner* role, or *Contributor* + *User Access Administrator*, on the target subscription or resource group) |
| **Azure OpenAI access and quota** | The subscription must have Azure OpenAI access enabled, with **GlobalStandard** quota available for `gpt-4o` *and* `gpt-4o-mini` (capacity 10 each — `infra/resources.bicep`). Without this quota, `azd up` fails at the model deployment creation step. Request/check: Azure OpenAI Studio → *Quotas*, or https://aka.ms/oai/access |
| Target region | A region where these **GlobalStandard** GPT-4o / GPT-4o-mini deployments are available (e.g. `swedencentral`, `eastus2`, `francecentral`) — check current availability in the "Azure OpenAI Models" docs |
| Local tools | [Azure Developer CLI (`azd`)](https://aka.ms/azd), Azure CLI (`az`), Docker (used by `azd` to build the image — falls back to ACR Tasks otherwise), Git |

> These prerequisites are **at the Azure subscription level**, independent
> of this repo's code: no amount of Bicep can provision a quota that hasn't
> been granted to the subscription.

### 8.2 Step 1 — Authentication

```bash
azd auth login
```

Opens a browser for Microsoft Entra ID authentication. If the account has
access to several subscriptions, check/select the right one (`az account
show`, `az account set --subscription <id>`) before the next step.

### 8.3 Step 2 — Provision and deploy (`azd up`)

```bash
azd up
```

`azd up` = `azd provision` (infra) + `azd deploy` (application), in a single
command. On first run, `azd` asks two questions:

| Prompt | Example | Note |
|---|---|---|
| `Enter a new environment name` | `incident-rca-demo` | Prefix for resource names (`rg-incident-rca-demo`, etc.) — becomes `AZURE_ENV_NAME` |
| `Select an Azure location` | `swedencentral` | **Must support GPT-4o / GPT-4o-mini GlobalStandard** (§8.1) — becomes `AZURE_LOCATION` |

(If the account has several subscriptions, `azd` also asks which one to
use.)

Flow (~10–15 minutes):

1. **Provisioning** (`infra/main.bicep` → `infra/resources.bicep`,
   subscription scope): creates `rg-<environment>` then the 20 resources —
   Log Analytics, Application Insights, managed identity, Container
   Registry, Azure OpenAI + `gpt-4o`/`gpt-4o-mini` deployments, Azure AI
   Search, Cosmos DB (`incidents` database + `records` container),
   Container Apps Environment and Container App (placeholder image) — plus
   all the RBAC role assignments (§8.6).
2. **Build**: `docker build` on the multi-stage `Dockerfile` (React
   frontend then FastAPI API), or a remote build via ACR Tasks if Docker
   isn't available locally.
3. **Push**: the image is pushed to the Container Registry provisioned in
   the previous step.
4. **Deploy**: new Container App revision with the real image and the
   environment variables injected automatically (§8.6).

At the end, `azd up` displays the public URL (`SERVICE_API_URI`), for
example:

```
https://api-xxxxxxxx.<region>.azurecontainerapps.io
```

### 8.4 Step 3 — Verify the deployment

1. Open `SERVICE_API_URI` in a browser → the React UI (`frontend/dist/`,
   served by FastAPI) should display.
2. `GET /api/health` → `{"status": "ok"}`.
3. `GET /api/meta` → `use_real_azure_openai: true` (the agents now call
   real Azure OpenAI via `AzureOpenAIStructuredChatClient`, no longer
   `StubChatClient`).
4. In the UI, "Run diagnosis" → the orchestration pipeline animates live
   (SSE). With real models, the outputs (in particular the `confiance`
   scores) may differ from the fixed scenario — see
   [`demo-guide.md`](demo-guide.md) "Variant: real Azure OpenAI".
5. At the human-approval gate, approve/reject from the UI (`ApprovalCard`)
   as described in [`demo-guide.md`](demo-guide.md) §4.

### 8.5 Provisioned resources (`infra/resources.bicep`)

| Resource | Azure type | Role |
|-----------|------------|------|
| Log Analytics workspace | `Microsoft.OperationalInsights/workspaces` | Container Apps Environment logs |
| Application Insights | `Microsoft.Insights/components` | observability: connection string injected, Agent Framework OTel wired on the code side (`src/observability.py`, §8.12) |
| Managed identity (user-assigned) | `Microsoft.ManagedIdentity/userAssignedIdentities` | Container App identity, holder of the role assignments |
| Container Registry | `Microsoft.ContainerRegistry/registries` (Basic) | API images |
| Azure OpenAI / Microsoft Foundry | `Microsoft.CognitiveServices/accounts` (kind `AIServices`, sku `S0`, `allowProjectManagement: true`) | + 2 deployments: `gpt-4o` (`2024-11-20`) and `gpt-4o-mini` (`2024-07-18`), sku `GlobalStandard` |
| Microsoft Foundry project | `Microsoft.CognitiveServices/accounts/projects` | sub-resource of the account above; shows the `WorkflowBuilder` orchestration in Observability > Traces once connected to Application Insights (§8.12) |
| Azure AI Search | `Microsoft.Search/searchServices` (sku `basic`) | RAG knowledge base (empty index at creation) |
| Azure Cosmos DB | `Microsoft.DocumentDB/databaseAccounts` (serverless) | `incidents` database, `records` container (partition key `/id`) |
| Container Apps Environment | `Microsoft.App/managedEnvironments` | runtime environment |
| Container App | `Microsoft.App/containerApps` | hosts the API+UI, external ingress port 8000, `azd-service-name: api` |

### 8.6 Security: no secrets in plaintext

`disableLocalAuth: true` on Azure OpenAI **and** Cosmos DB disables
API/master keys. All data-plane authentication goes through **Microsoft
Entra ID role assignments**, granted to the Container App's managed
identity:

| Role | Target | Usage |
|------|-------|-------|
| `Cognitive Services OpenAI User` | Azure OpenAI | completion calls |
| `Search Index Data Reader` | Azure AI Search | reading the RAG index |
| Cosmos DB *Built-in Data Contributor* (`00000000-0000-0000-0000-000000000002`) | Cosmos DB | reading/writing records |
| `AcrPull` | Container Registry | pulling the image at startup |

The Container App receives `AZURE_AUTH_MODE=managed_identity` and
`AZURE_CLIENT_ID=<identity.clientId>` (so that `DefaultAzureCredential`
selects this identity). An optional `principalId` parameter (filled in by
`azd` via `AZURE_PRINCIPAL_ID`) grants the **same data-plane roles** to the
developer's account, to be able to point a local `.env`
(`AZURE_AUTH_MODE=cli`) at the actually deployed resources (§8.7).

> `Microsoft.App/containerApps` is configured with `scale: {minReplicas: 1,
> maxReplicas: 1}`: `app.state.runs` (`src/api/runs.py`) is an in-memory,
> per-process registry — multiple replicas would break HITL resumption
> between the two SSE calls.

### 8.7 Developing locally against the deployed resources

```bash
azd env get-values >> .env   # AZURE_OPENAI_ENDPOINT, COSMOS_ENDPOINT, ...
az login                      # AZURE_AUTH_MODE=cli (default) -> AzureCliCredential
uvicorn src.api.app:app --reload
```

`KB_MODE` stays `local` by default even after `azd up` (§8.9).

### 8.8 Updating the deployment after a code change

```bash
azd deploy   # rebuild + push + new Container App revision (infra unchanged)
# if infra/*.bicep has changed:
azd up
```

### 8.9 (Optional) Switching the knowledge base to Azure AI Search

The Azure AI Search index is provisioned **empty** (§5): `KB_MODE` stays
`local` after deployment and the app uses the `data/knowledge_base.json`
bundled in the image. To enable real RAG search:

1. Index `data/knowledge_base.json` into the `incident-kb` index
   (`AZURE_AI_SEARCH_ENDPOINT`, schema in `SPEC.md` §7) — **manual step, no
   indexing pipeline in the repo** (DECISIONS.md #22).
2. Switch the Container App to `KB_MODE=azure_search`:
   ```bash
   azd env set KB_MODE azure_search
   azd deploy
   ```
3. `get_knowledge_base()` (`src/tools/knowledge_base.py`) automatically
   switches to `AzureAISearchKnowledgeBase`.

Without step 1, `KBSearch` would return no precedent at all — which is why
`KB_MODE` stays `local` by default after `azd up`.

### 8.10 Cleanup

```bash
azd down            # deletes all resources in the environment (including the resource group)
azd down --purge    # + permanently purges soft-delete resources (Azure OpenAI, Cosmos DB)
```

### 8.11 Troubleshooting

| Symptom | Likely cause | Solution |
|---|---|---|
| `azd up` fails on `openAiChatDeployment` / `openAiChatDeploymentLight` (quota exceeded) | No GlobalStandard quota for GPT-4o/GPT-4o-mini in the chosen region | Request the quota in Azure OpenAI Studio, or choose another region (§8.1) |
| `azd up` fails with `ServiceModelDeprecating: ... is in deprecating state and cannot be used for new deployments` | The model version pinned in `infra/resources.bicep` was deprecated by Microsoft in the meantime | Check the [Model Retirement Schedule](https://learn.microsoft.com/azure/ai-foundry/openai/concepts/model-retirement-schedule) and update `properties.model.version` (e.g. `gpt-4o` `2024-08-06`/`2024-05-13` → `2024-11-20`) in `infra/resources.bicep`, then rerun `azd up` |
| `azd up` fails on `Microsoft.CognitiveServices/accounts` (access denied) | Azure OpenAI access not enabled on the subscription | Request access via https://aka.ms/oai/access |
| `azd up` fails on the role assignments (`AuthorizationFailed`) | The account doesn't have the *User Access Administrator* role (or *Owner*) on the subscription/resource group | Request that role, or have an admin with the right permissions provision it |
| `package-api` fails with `building image: signal: killed` during `npm run build` / `pip install` | `azd up` runs the Docker build **in parallel** with provisioning ("Packaging overlaps with provisioning") — on a machine/container with little RAM, the two together trigger an OOM kill of the Docker build | Rerun `azd provision` then `azd deploy` separately (sequential, no overlap), or increase the memory allocated to Docker, or rerun `azd up` (often transient / tied to cache state) |
| The UI loads but `POST /api/runs` fails or the agents raise an error | Azure OpenAI deployments not yet fully propagated | Wait a few minutes then retry, check `GET /api/meta` |
| `KBSearch` returns no precedent despite `KB_MODE=azure_search` | Azure AI Search index empty (provisioned without an indexing pipeline) | Index `data/knowledge_base.json` (§8.9), or revert to `KB_MODE=local` |
| `azd up` fails on `foundryProject` with `BadRequest: ... To create projects, you must enable a managed identity on your resource` (and a generic "A resource with this name already exists or is in a conflicting state" message) | The `openAi` account (`kind: AIServices`) **and** the `foundryProject` sub-project (`Microsoft.CognitiveServices/accounts/projects`) must each have their own managed identity for `allowProjectManagement: true` (DECISIONS.md #26, #27) — on a fresh environment, the account can succeed (with its identity) while the project fails right after for lack of its own | Already fixed in `infra/resources.bicep` (`identity: { type: 'SystemAssigned' }` on `openAi` **and** on `foundryProject`); check that the checkout includes both fixes (`git log` → commits "managed identity on the AIServices account" and "managed identity on the Foundry project") then rerun `azd provision`/`azd up`. If the "already exists" error persists with an up-to-date checkout, check in the portal (account `aoai-${resourceToken}` → *Projects* tab) that there isn't a `proj-${resourceToken}` stuck in `Failed` state, and delete it before rerunning |
| `azd up` fails on `Azure AI Services: aoai-${resourceToken}` or on the `proj-${resourceToken}` project with `FailedIdentityOperation: ... Status: 'Conflict'. ... is new, but resource already exists. This may be due to a pending delete operation, try again later` | Transient conflict on the managed identity provider (MSI) side when adding a `SystemAssigned` identity to a resource that already exists (created by an earlier `azd up` before this change, without an identity) | The bicep is correct (identity required by `allowProjectManagement: true`, DECISIONS.md #26, #27) — this is a transient Azure error. Quick fix: portal → the resource in question (`aoai-${resourceToken}` or its project) → **Identity** → **System assigned** → **On** → Save, then rerun `azd provision`/`azd up` (the bicep will find the identity already matches). Otherwise, wait a few minutes (for the pending operation on the Azure side to finish) then rerun `azd up` |
| `azd provision`/`azd up` fails very quickly (< 2s) on the `aoai-${resourceToken}` account ("Foundry: aoai-...") with `BadRequest: PublicNetworkAccess is required for this resouce` (and the generic "already exists or in a conflicting state" message) | With `allowProjectManagement: true` and a sub-project having its own identity (DECISIONS.md #25, #27), Azure requires the account's `properties.publicNetworkAccess` to be explicitly set — it can no longer stay implicit | Already fixed in `infra/resources.bicep` (`publicNetworkAccess: 'Enabled'` on `openAi`, DECISIONS.md #28); check that the checkout is up to date (`git log` → commit "managed identity on the Foundry project" or later) then rerun `azd provision`/`azd up` |

### 8.12 Observability: tracing the orchestration in Microsoft Foundry

`src/observability.py` (`configure_observability`, called at startup by
`src.main` and `src.api.app`) wires the Agent Framework's OpenTelemetry
instrumentation to Application Insights:

```python
configure_azure_monitor(connection_string=settings.applicationinsights_connection_string)
enable_instrumentation(enable_sensitive_data=settings.enable_sensitive_data)
```

It's a **no-op if `APPLICATIONINSIGHTS_CONNECTION_STRING` is empty** (offline
mode / `StubChatClient`): no network dependency is added to the local demo.

After `azd up`, `APPLICATIONINSIGHTS_CONNECTION_STRING` is already injected
into the Container App (§8.5/§8.6). Each `workflow.run()` (the six agents,
the `RootCause <-> GatherEvidence` reflection loop, the `HumanApproval` HITL
gate) then emits `workflow.run` / `executor.process <id>` spans visible in
Application Insights (Transaction search / Application map).

To see them in the **Microsoft Foundry project** (`proj-${resourceToken}`,
provisioned by `infra/resources.bicep`, output `AZURE_FOUNDRY_PROJECT_NAME`),
connect the Application Insights resource to the project once — a manual
step, not codified in Bicep (DECISIONS.md #25):

1. https://ai.azure.com → open the `proj-${resourceToken}` project.
2. **Agents** (or **Observability**) → **Traces** → **Connect**.
3. Select the existing Application Insights resource (`appi-${resourceToken}`).

The traces then appear in the project's **Observability > Traces**, with a
per-run timeline showing each agent, the reflection loop, and the HITL gate.

> `ENABLE_SENSITIVE_DATA=true` (`.env`, dev only) includes the agents'
> prompts/responses in the traces — never enable it in production
> (potentially sensitive data).

### 8.13 Making the agents visible in the Microsoft Foundry project

§8.12 makes the **execution** (the traces) visible in Foundry once
Application Insights is connected. `scripts/register_foundry_agents.py`
complements this by registering the **six agents** as entries in the
Foundry project's **Agents** tab (`proj-${resourceToken}`), so they appear
by name even before any execution.

The agents run **outside of Foundry**, directly against Azure OpenAI
(`AZURE_OPENAI_ENDPOINT`) via the Microsoft Agent Framework — there is no
"native Foundry" execution in this demo. The registration therefore uses
`ExternalAgentDefinition` (`azure-ai-projects`): *"Represents a third-party
agent hosted outside Foundry"*. This is a **metadata-only** registration —
no compute resource is created, only the entry appears in the UI.

> **Preview** feature of `azure-ai-projects` (requires
> `AIProjectClient(..., allow_preview=True)`): the API may change before GA.

**Prerequisites:**

1. `pip install -e ".[foundry]"` (optional group, separate from `[dev]` —
   unrelated to running/testing the demo itself).
2. `AZURE_FOUNDRY_PROJECT_ENDPOINT` set in `.env` — already injected after
   `azd up` via `azd env get-values >> .env` (§8.7), or retrievable from the
   Foundry portal (project URL).
3. Azure authentication: `az login` (`AZURE_AUTH_MODE=cli`, local default) or
   managed identity (`AZURE_AUTH_MODE=managed_identity`, deployed).

**Execution (once, after every agent name/description change):**

```bash
python -m scripts.register_foundry_agents
```

The script registers each agent under its exact name (`LogAnalyzer`,
`IncidentExtractor`, `KBSearch`, `RootCause`, `Remediation`, `Summary`) —
identical to the now-stable `id` passed to `as_agent()`
(`src/agents/clients.py`), which guarantees that the traces (§8.12, span
attribute `gen_ai.agent.id`) attach to the right agent registered in
Foundry.

In **https://ai.azure.com** → project `proj-${resourceToken}` → **Agents**,
the six agents appear with their description; **Observability > Traces**
(§8.12) then shows their executions once Application Insights is connected.

> §8.12 already makes the full execution (reflection loop, HITL gate)
> visible as a timeline in **Observability > Traces**. §8.14 below
> additionally registers a second, purely visual artifact to make the
> graph's **topology** navigable in the Agents tab.

### 8.14 Making the orchestration graph visible in the Microsoft Foundry project

`scripts/register_foundry_workflow.py` registers the orchestration as a
**Workflow**-type agent (`WorkflowAgentDefinition`), in addition to the six
agents (§8.13). Unlike those, this script registers a second, distinct
artifact: `scripts/foundry_workflow.yaml`, a **hand-written CSDL**
definition that reproduces the topology of `src/orchestrator/graph.py`
(sequence, bounded reflection loop, HITL gate) so that it is
visible/navigable in the Foundry project's visual canvas.

> **What this YAML is not:** it does not actually execute — there is no
> exporter from the Python `WorkflowBuilder` to CSDL — and it is not
> automatically resynced if `src/orchestrator/graph.py` changes (confidence
> threshold, max number of loops, etc.). The orchestration that actually
> runs remains 100% `src/orchestrator/graph.py` + `executors.py`. The six
> `InvokeAzureAgent` nodes it contains reference the agents registered as
> `ExternalAgentDefinition` (§8.13) — metadata-only entries, with no
> model/instructions on the Foundry side — so clicking **"Run Workflow"** in
> the portal will probably fail on the very first agent call. Only the
> **display** of the graph (nodes/edges/conditions) is guaranteed to be
> useful; see DECISIONS.md #30 and the header of `foundry_workflow.yaml` for
> details.

**Prerequisites:** same as §8.13, plus having already run
`python -m scripts.register_foundry_agents` at least once (the six agents
referenced by `foundry_workflow.yaml` must already exist in the project).

**Execution (once, after every change to `foundry_workflow.yaml`):**

```bash
python -m scripts.register_foundry_workflow
```

In **https://ai.azure.com** → project `proj-${resourceToken}` → **Agents**,
a Workflow-type agent `IncidentRCAWorkflow` appears, with the graph visible
in the canvas. As with the agents (§8.13), rerunning the script creates a
new version (history is kept by Foundry).

## 9. Tests

```bash
pip install -e ".[dev]"
pytest
```

| Suite | Coverage |
|-------|------------|
| `tests/agents/` | one isolated test per agent (input/output contract via `StubChatClient`) |
| `tests/orchestrator/test_workflow.py` | end-to-end on `data/payment-incident.log`, checks the **8 acceptance criteria** from `SPEC.md` §8 |
| `tests/api/test_runs.py` | the two SSE phases of `/api/runs` (`run_started`/`step`/`approval_required`/`done`), approval and rejection |
| `tests/tools/test_persistence.py` | `LocalPersistenceStore` |

Frontend:

```bash
cd frontend && npm run build   # tsc -b then Vite build to frontend/dist/
```
