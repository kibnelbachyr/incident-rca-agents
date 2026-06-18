# Incident RCA Agents — multi-agent demo (payments)

Demo of an **orchestrated multi-agent system** (Microsoft Agent Framework) that
diagnoses an incident on a payment system: raw logs → structured incident →
precedent search → root cause (with a reflection loop) → remediation
(validated by a human) → final report.

Two ways to run the demo, same orchestrator:
- **CLI** (`python -m src.main`) — text streaming in the terminal.
- **Web UI** (FastAPI + React, `src/api/` + `frontend/`) — animated
  orchestration graph, human validation and run history.

The whole thing is **deployable on Azure** via Bicep + Azure Developer CLI
(`azd up`, see `infra/`).

To go further: `docs/` (detailed documentation — components, internals,
deployment, demo), `CLAUDE.md` (project stack and constraints), `SPEC.md`
(detailed specification and agent contracts),
`scenario-demo-incident-paiement.md` (step-by-step presentation script) and
`DECISIONS.md` (log of architecture choices made autonomously).

## At a glance

| # | Agent | Role | Model |
|---|-------|------|--------|
| 1 | `LogAnalyzer` | Normalizes the logs: timeline + anomalies + correlations | light |
| 2 | `IncidentExtractor` | Produces the structured `Incident` object | light |
| 3 | `KBSearch` | Searches for precedents in the knowledge base (RAG) | light |
| 4 | `RootCause` | Root cause hypothesis + confidence score | strong |
| 5 | `Remediation` | Remediation plan (proposed, behind human validation) | strong |
| 6 | `Summary` | Final incident report | light |

Agents are **stateless** and never talk to each other directly: everything
goes through the orchestrator and the `SharedContext` (`src/models.py`).

Orchestration graph topology (`src/orchestrator/graph.py`):

```
LogAnalyzer -> IncidentExtractor -> KBSearch -> RootCause --[switch]--+
                      ^                                               |
                      | confidence < threshold AND loop_count < max   | otherwise
                      +------------------ GatherEvidence <------------+
                                                                       v
                                                          HumanApproval (HITL)
                                                                       | approved
                                                                       v
                                                      Remediation -> Summary
```

Non-negotiable constraints (`CLAUDE.md`):
- Reflection loop **bounded** by `MAX_REFLECTION_LOOPS` (default `2`).
- Below `CONFIDENCE_THRESHOLD` (default `0.75`), the orchestrator loops back
  to gather more evidence instead of concluding.
- **No remediation without human validation** (`ctx.request_info`).
- Remediation stays a **displayed plan**, never executed on a real system.
- No secrets in plaintext: everything goes through `.env` / environment
  variables / Key Vault.

## Quick start (offline mode, no Azure)

No Azure credentials are required to run the demo: as long as
`AZURE_OPENAI_ENDPOINT` is not configured with a real endpoint, all agents
use a deterministic `StubChatClient` that replays the scenario from
`scenario-demo-incident-paiement.md` (`DECISIONS.md` #3-4).

### CLI

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the demo on the sample incident
python -m src.main --logs data/payment-incident.log
```

The demo streams each agent's output as it happens, including `RootCause`'s
1st pass (confidence 0.55, below the threshold) and the
`GatherEvidence -> RootCause` loop (confidence 0.92). It then stops at the
human approval gate:

```
Approve proceeding to remediation? [y/N]:
```

- `y` / `yes` → the `RemediationPlan` and then the final report
  (`IncidentReport`) are displayed.
- any other response (or non-interactive input / EOF) → the workflow stops
  immediately, without generating or displaying a remediation plan.

### Web UI (FastAPI + React)

Two processes in development:

```bash
# Terminal 1: API (port 8000)
pip install -e ".[dev]"
uvicorn src.api.app:app --reload

# Terminal 2: frontend (port 5173, proxies /api -> :8000 via vite.config.ts)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173: pick a scenario (`db_pool` / `paypal_integration`,
from `GET /api/scenarios`) and click "Run Diagnostic" to start a run
(`POST /api/runs`, SSE). The `PipelineHUD` animates the 8-node orchestration
graph live as `step` events arrive, alongside a scrolling `ActivityFeed` log;
the `DetailPanel` shows each agent's structured output as it completes,
including the embedded `ApprovalCard` at the human approval gate —
approving/declining calls `POST /api/runs/{run_id}/approval`. The history tab
(`History`) lists completed, persisted runs (`GET /api/history`,
`src/tools/persistence.py`).

In production (Docker image / Azure), a single process: `frontend/dist/`
(`npm run build`) is served by FastAPI via `StaticFiles`, on the same port as
the API (`src/api/app.py`) — no CORS to manage.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

- `tests/agents/` — one isolated test per agent (input/output contract via
  `StubChatClient`).
- `tests/orchestrator/test_workflow.py` — end-to-end test on
  `data/payment-incident.log`, which checks the **8 acceptance criteria**
  from `SPEC.md` section 8: SEV-1 incident, two KB precedents, loop-back
  below the confidence threshold, `max_pool_size` root cause on the 2nd
  pass, HITL pause, plan + report after approval, observable outputs,
  bounded loop.
- `tests/api/test_runs.py` — the two SSE phases of `/api/runs`
  (`run_started`/`step`/`approval_required`/`done`), approval and decline.
- `tests/tools/test_persistence.py` — `LocalPersistenceStore`.

Frontend: `cd frontend && npm run build` (checks types via `tsc -b` then
builds with Vite into `frontend/dist/`).

## Configuration

All configuration goes through the environment / `.env` (see
`.env.example`), loaded by `src/config.py` (`Settings`, pydantic-settings).
Nothing is hardcoded.

| Variable | Role | Default |
|----------|------|--------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI / Foundry endpoint. If absent (or the `.env.example` placeholder), `StubChatClient` is used | _(none)_ |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | "Strong" deployment (`RootCause`, `Remediation`) | `gpt-4o` |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT` | "Light" deployment (other agents) | `gpt-4o-mini` |
| `AZURE_OPENAI_API_VERSION` | Azure OpenAI API version | `2024-10-21` |
| `AZURE_AUTH_MODE` | `cli` (local, `az login`) or `managed_identity` (deployed) | `cli` |
| `AZURE_AI_SEARCH_ENDPOINT`, `AZURE_AI_SEARCH_INDEX` | RAG knowledge base in deployed mode | _(none)_ |
| `KB_MODE` | `local` (`data/knowledge_base.json`) or `azure_search` | `local` |
| `CONFIDENCE_THRESHOLD` | `RootCause` confidence threshold | `0.75` |
| `MAX_REFLECTION_LOOPS` | Max number of `RootCause <-> GatherEvidence` loops | `2` |
| `COSMOS_*`, `APPLICATIONINSIGHTS_CONNECTION_STRING` | Persistence / observability (optional for the demo) | _(none)_ |

### Using Azure OpenAI (real models)

1. `az login` (`AZURE_AUTH_MODE=cli` mode, default locally).
2. Set `AZURE_OPENAI_ENDPOINT` and the deployment names in `.env`.
3. `python -m src.main` then uses `AzureOpenAIStructuredChatClient`
   (`src/agents/clients.py`) — same agents, same pydantic contracts, JSON
   output enforced via `response_format`.

### Switching the knowledge base to Azure AI Search

1. Create an Azure AI Search index and load `data/knowledge_base.json` into
   it (see `SPEC.md` section 7).
2. Set `KB_MODE=azure_search`, `AZURE_AI_SEARCH_ENDPOINT` and
   `AZURE_AI_SEARCH_INDEX` in `.env`.
3. `get_knowledge_base()` (`src/tools/knowledge_base.py`) automatically
   switches to `AzureAISearchKnowledgeBase`, which implements the same
   `KnowledgeBase` interface as `LocalKnowledgeBase`.

## Containerization

```bash
docker build -t incident-rca-agents .
docker run --rm -it -p 8000:8000 incident-rca-agents
```

Open http://localhost:8000: the image (multi-stage build, `Dockerfile`)
serves the API **and** the built UI (`frontend/dist/`) on the same port via
a single `uvicorn src.api.app:app` process (DECISIONS.md #20).
`pip install -e .` keeps `src.config.REPO_ROOT` aligned with `/app` (where
`data/` is copied): the default paths (`data/payment-incident.log`,
`data/knowledge_base.json`) work with no extra configuration.
`AZURE_AUTH_MODE=managed_identity` is set by default for an Azure Container
Apps deployment with managed identity (`DefaultAzureCredential`); pass your
`AZURE_*` variables via `docker run -e ...` or Container Apps secrets.
Locally, offline (without `AZURE_OPENAI_ENDPOINT`), `StubChatClient` is used
and no variable is required.

## Deploying to Azure (azd)

`infra/` (Bicep) + `azure.yaml` provision the target architecture described
by `CLAUDE.md` and deploy the Docker image above to Azure Container Apps
(DECISIONS.md #21-22): Azure OpenAI (`gpt-4o` + `gpt-4o-mini` deployments),
Azure AI Search, Azure Cosmos DB serverless, Container Registry, Container
Apps Environment + Container App, Log Analytics + Application Insights, and
a managed identity with the necessary role assignments (no plaintext API
keys — `disableLocalAuth: true` on Azure OpenAI and Cosmos DB).

```bash
# Install azd: https://aka.ms/azd
azd auth login
azd up   # provisions infra/ then builds + pushes + deploys the Docker image
```

`azd up` asks for an environment name and a region (choose a region where
GPT-4o / GPT-4o-mini "GlobalStandard" deployments are available, e.g.
`swedencentral`, `eastus2`); the Container App's URL is shown at the end.

To run the API locally against the actually deployed resources (instead of
`StubChatClient`):

```bash
azd env get-values >> .env   # AZURE_OPENAI_ENDPOINT, COSMOS_ENDPOINT, ...
az login                      # AZURE_AUTH_MODE=cli (default) -> AzureCliCredential
uvicorn src.api.app:app --reload
```

`KB_MODE` stays `local` by default even after `azd up` (the Azure AI Search
index is created empty, see DECISIONS.md #22). `azd down` removes all
resources in the environment.

## Repository structure

```
src/
├── agents/          # 6 agents (instructions + pydantic contract) + clients (stub/Azure OpenAI)
├── api/             # FastAPI: /api/runs (SSE, 2 phases + HITL), /api/history, /api/meta
├── orchestrator/    # WorkflowBuilder graph: executors + topology + loop + HITL
├── tools/            # knowledge base (local / Azure AI Search) + persistence (local / Cosmos DB)
├── config.py        # Settings (pydantic-settings, reads .env)
├── models.py        # pydantic contracts (SPEC.md section 4)
└── main.py          # CLI: streams outputs + human validation

frontend/            # React + Vite UI: orchestration graph, human validation, history

infra/               # Bicep (azd): main.bicep (resource group) + resources.bicep
azure.yaml           # Azure Developer CLI config (`azd up`)

data/
├── payment-incident.log   # sample logs (SEV-1 incident)
└── knowledge_base.json    # past incidents (INC-204, INC-187, INC-241, INC-223)

tests/
├── agents/          # one isolated test per agent
├── api/             # SSE tests for /api/runs (approval + decline)
├── orchestrator/    # end-to-end test (8 criteria from SPEC.md section 8)
└── tools/           # local persistence

docs/                # detailed documentation (architecture, internals, deployment, demo)
```

## Possible next steps (out of scope for the demo)

- Populate an Azure AI Search index from `data/knowledge_base.json` (an
  indexing pipeline), then switch `KB_MODE=azure_search` — the index and the
  `Search Index Data Reader` role are already provisioned by `azd up`
  (DECISIONS.md #22).
- Automatically connect Application Insights to the Microsoft Foundry
  project via Bicep — today a one-off manual step in the portal
  (`docs/deployment.md` §8.12, DECISIONS.md #25).

## Learn more

- `docs/` — detailed documentation: [`docs/architecture.md`](docs/architecture.md)
  (components, contracts, design), [`docs/how-it-works.md`](docs/how-it-works.md)
  (reflection loop, HITL, SSE flow), [`docs/deployment.md`](docs/deployment.md)
  (local dev, Docker, Azure/azd, configuration, observability §8.12, agents
  visible in Microsoft Foundry §8.13) and
  [`docs/demo-guide.md`](docs/demo-guide.md) (step-by-step demo script, CLI and UI).
- `SPEC.md` — detailed JSON contracts, orchestration topology, acceptance
  criteria, Azure deployment architecture.
- `DECISIONS.md` — architecture choices made autonomously and their
  rationale.
- `scenario-demo-incident-paiement.md` — step-by-step presentation script.
