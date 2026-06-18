# Architecture & design

> Overview of all components and design principles. For the detailed JSON
> contracts and acceptance criteria, see `SPEC.md`. For the detailed
> technical choices and their rationale, see `DECISIONS.md`. For the inner
> workings (reflection loop, HITL, SSE flow), see
> [`how-it-works.md`](how-it-works.md).

## 1. Overview

The project is a demo of an **orchestrated multi-agent system** (Microsoft
Agent Framework) that diagnoses an incident on a payment system:

```
raw logs → structured incident → precedents (RAG) → root cause
           → [reflection loop if confidence is insufficient]
           → human validation → remediation plan → final report
```

Two entry points share the **same orchestrator**
(`src/orchestrator/graph.py`):

- **CLI** (`python -m src.main`) — text streaming in the terminal,
  approval via `input()`.
- **API + web UI** (FastAPI + React, `src/api/` + `frontend/`) — the same
  graph exposed over SSE, animated orchestration graph, approval via a
  button, persisted run history.

The whole thing is deployable on Azure via Bicep + Azure Developer CLI (`azd`,
`infra/`).

### Orchestration graph topology

```
LogAnalyzer -> IncidentExtractor -> KBSearch -> RootCause --[switch]--+
                      ^                                               |
                      | confidence < threshold AND loop_count < max   | else
                      +------------------ GatherEvidence <------------+
                                                                       v
                                                          HumanApproval (HITL)
                                                                       | approved
                                                                       v
                                                      Remediation -> Summary
```

Each node is a framework `Executor` that wraps either an agent
(`StructuredAgent`), or (for `HumanApproval`) a pure validation gate.
Agents are **stateless** and never communicate directly with each
other: everything goes through the **orchestrator** and the **`SharedContext`**
(`src/models.py`), a single pydantic object that travels from node to node and
accumulates the results.

## 2. Design principles (non-negotiable constraints)

These constraints come from `CLAUDE.md` and structure the entire codebase:

| # | Constraint | Where it's implemented |
|---|------------|----------------------|
| 1 | Specialized, stateless agents, strict I/O contract (pydantic-validated JSON) | `src/agents/*.py` (`response_model`), `src/models.py` |
| 2 | The orchestrator holds **all** shared state, agents never talk to each other | `SharedContext` (`src/models.py`) propagated via `ctx.send_message` |
| 3 | **Bounded** reflection loop (`MAX_REFLECTION_LOOPS`, default 2) | `needs_more_evidence` (`src/orchestrator/graph.py`) |
| 4 | Below `CONFIDENCE_THRESHOLD` (default 0.75), the loop reruns instead of concluding | same, based on `RootCauseHypothesis.confiance` |
| 5 | **No remediation without human validation** | `HumanApprovalExecutor` + `ctx.request_info()` (`src/orchestrator/executors.py`) |
| 6 | Remediation remains a **displayed plan**, never executed | `RemediationAgent` only produces a `RemediationPlan` object; no real infrastructure call |
| 7 | No secrets in plaintext (`.env` / env vars / Managed Identity / Key Vault) | `src/config.py` (`Settings`, pydantic-settings); `infra/` (`disableLocalAuth: true` + RBAC) |

## 3. Components — overview

| Component | Path | Role |
|-----------|--------|------|
| Agents (6) | `src/agents/` | One module per agent: instructions (system prompt), pydantic output contract, `build_prompt` function. |
| Agent base | `src/agents/base.py` | Generic `StructuredAgent[ResponseT]` class. |
| Chat clients | `src/agents/clients.py` | `StubChatClient` (offline, deterministic) and `AzureOpenAIStructuredChatClient` (real), chosen by `get_chat_client`. |
| Data contracts | `src/models.py` | All pydantic models, including `SharedContext` (central state). |
| Orchestrator — graph | `src/orchestrator/graph.py` | `build_workflow(settings)`: assembles the `Workflow` (`WorkflowBuilder`). |
| Orchestrator — executors | `src/orchestrator/executors.py` | One `Executor` per graph node (8 in total). |
| Knowledge base (RAG) | `src/tools/knowledge_base.py` | `LocalKnowledgeBase` (local JSON, Jaccard) / `AzureAISearchKnowledgeBase`. |
| Persistence | `src/tools/persistence.py` | `LocalPersistenceStore` (JSON files) / `CosmosPersistenceStore`. |
| Configuration | `src/config.py` | `Settings` (pydantic-settings), thresholds, modes, `REPO_ROOT`. |
| CLI | `src/main.py` | Terminal entry point: streaming + `input()` approval. |
| API | `src/api/` | FastAPI: `/api/runs` (SSE), `/api/history`, `/api/meta`, `/api/health`. |
| Frontend | `frontend/` | React + Vite + TypeScript: animated graph, per-step cards, human validation, history. |
| Infrastructure | `infra/`, `azure.yaml` | Bicep + Azure Developer CLI: complete Azure provisioning. |

## 4. The 6 agents (`src/agents/`)

Each agent is a `StructuredAgent[ResponseT]` class (see §5) that
combines:
- `name` — name used as `agent_name` (key in the `StubChatClient`, name of
  the Azure OpenAI `Agent`);
- `instructions` — system prompt (always "respond only in JSON,
  without Markdown");
- `response_model` — the pydantic output model (`src/models.py`);
- `build_prompt(...)` — function that builds the user prompt from
  the `SharedContext`.

### 4.1 `LogAnalyzer` (`src/agents/log_analyzer.py`)

- **Role**: normalizes the raw logs into actionable signal.
- **Suggested model**: light (`gpt-4o-mini`).
- **Input** (`build_prompt(raw_logs, *, focus=None)`): the raw logs, and
  optionally a `focus` list of points to investigate as a priority
  (used by `GatherEvidence`, see `how-it-works.md` §6).
- **Output**: `LogAnalysis`
  - `timeline: list[TimelineEvent]` — timestamped events (`time`, `event`).
  - `anomalies: list[str]` — saturations, latency/error spikes.
  - `correlated_events: list[str]` — temporal correlations (e.g.
    deployment → degradation).

### 4.2 `IncidentExtractor` (`src/agents/incident_extractor.py`)

- **Role**: turns the log analysis into a structured incident object.
- **Suggested model**: light.
- **Input** (`build_prompt(log_analysis)`): the `LogAnalysis` produced by
  `LogAnalyzer`, serialized as JSON.
- **Output**: `Incident`
  - `titre: str`, `severite: str` (regex `^SEV-[1-5]$`),
    `services: list[str]`, `fenetre: str`, `symptomes: list[str]`.

### 4.3 `KBSearch` (`src/agents/kb_search.py`)

- **Role**: search for similar precedents (RAG) and reformat the final
  list.
- **Suggested model**: light.
- **Particularity**: it's the only agent that **overrides `run()`**. Before
  calling the LLM, it directly queries
  `KnowledgeBase.search(incident, top_k=2)` (§7.1) to obtain
  candidates with a raw similarity score, then asks the LLM to
  confirm/format the final list via `build_prompt(incident, candidates)`.
- **Output**: `KBMatches` → `matches: list[KBMatch]`, each `KBMatch` having
  `id`, `similarite` (0-1), `resolution`.

### 4.4 `RootCause` (`src/agents/root_cause.py`)

- **Role**: the **most important** agent. Formulates the best root-cause
  hypothesis, with a confidence score that drives the orchestrator's
  reflection loop.
- **Suggested model**: strong (`gpt-4o`).
- **Input** (`build_prompt(incident, log_analysis, kb_matches, *,
  evidence_log=None)`): the incident, the log analysis, the KB precedents, and
  — on the 2nd pass — the additional evidence collected by
  `GatherEvidence` (`evidence_log`).
- **Output**: `RootCauseHypothesis`
  - `cause: str`, `raisonnement: str`, `confiance: float` (0-1),
    `preuves_manquantes: list[str]` — filled in only if `confiance` is
    low; this is the list `GatherEvidence` uses as `focus`
    for `LogAnalyzer` on the next round.

### 4.5 `Remediation` (`src/agents/remediation.py`)

- **Role**: proposes a prioritized remediation plan. **Invoked only
  after human validation** (HITL gate, §8.2 and `how-it-works.md` §4).
- **Suggested model**: strong.
- **Input** (`build_prompt(incident, root_cause, kb_matches)`).
- **Output**: `RemediationPlan` → three lists `immediat`, `court_terme`,
  `long_terme`. This plan is **only displayed** — see constraint #6 of
  §2; no executor calls a real infrastructure API.

### 4.6 `Summary` (`src/agents/summary.py`)

- **Role**: writes the final incident report, ready to paste into a
  post-mortem.
- **Suggested model**: light.
- **Input** (`build_prompt(incident, log_analysis, root_cause,
  remediation_plan, kb_matches)`): the entire accumulated context.
- **Output**: `IncidentReport`
  - Structured fields: `titre`, `fenetre`, `impact`, `cause_racine`,
    `confiance`, `remediation: list[str]` (merged immediate/short/long term),
    `precedent_lie: str | None`.
  - `texte: str` — the full report in plain text, with the sections
    "ROOT CAUSE (confidence X)", "REMEDIATION" (numbered list) and
    "RELATED PRECEDENT".

## 5. `StructuredAgent` and chat clients

### 5.1 `StructuredAgent[ResponseT]` (`src/agents/base.py`)

Minimal generic class inherited by all 6 agents:

```python
class StructuredAgent(Generic[ResponseT]):
    name: ClassVar[str]
    instructions: ClassVar[str]
    response_model: ClassVar[type[ResponseT]]

    def __init__(self, client: StructuredChatClient) -> None: ...

    async def run(self, prompt: str) -> ResponseT:
        return await self._client.get_structured_response(
            agent_name=self.name,
            instructions=self.instructions,
            prompt=prompt,
            response_model=self.response_model,
        )
```

All the difference between "offline mode" and "real Azure OpenAI" is
encapsulated in the injected `client` object — the agents themselves are
identical in both modes.

### 5.2 `StructuredChatClient` (`src/agents/clients.py`)

Minimal protocol: `get_structured_response(*, agent_name, instructions,
prompt, response_model) -> ResponseT`. Two implementations:

- **`StubChatClient`** — deterministic, **zero network calls**. For each
  `agent_name`, `_STUB_RESPONSES` contains either a single response replayed on
  every call, or a **list** indexed by call number (used only for
  `RootCause` and `LogAnalyzer`, to simulate the reflection
  loop: 1st call confidence 0.55, 2nd call — after `GatherEvidence` —
  confidence 0.92). Lets the entire demo run and the 8
  acceptance criteria (`SPEC.md` §8) be verified **with no Azure credentials at
  all**.
- **`AzureOpenAIStructuredChatClient`** — real agents via
  `agent_framework.openai.OpenAIChatCompletionClient.as_agent(...)`, with
  `default_options={"response_format": response_model}` to force a JSON
  output conforming to the pydantic schema. An `Agent` is cached per
  `(agent_name, response_model)` pair.

`get_chat_client(settings, *, light: bool)` automatically picks between the
two based on `Settings.use_real_azure_openai` (true if
`AZURE_OPENAI_ENDPOINT` is set and is not the placeholder from
`.env.example`). `light=True` selects the
`AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT` deployment (`gpt-4o-mini`), `light=False`
selects the `AZURE_OPENAI_CHAT_DEPLOYMENT` deployment (`gpt-4o`).

## 6. Data contracts (`src/models.py`)

All contracts are **pydantic** models; agents respond
**only** with JSON validated against these schemas (never any Markdown around it).

| Model | Main fields | Produced by |
|--------|---------------------|-------------|
| `TimelineEvent` | `time`, `event` | (sub-object of `LogAnalysis`) |
| `LogAnalysis` | `timeline`, `anomalies`, `correlated_events` | `LogAnalyzer` |
| `Incident` | `titre`, `severite` (`^SEV-[1-5]$`), `services`, `fenetre`, `symptomes` | `IncidentExtractor` |
| `KBMatch` / `KBMatches` | `id`, `similarite`, `resolution` / `matches: list[KBMatch]` | `KBSearch` |
| `RootCauseHypothesis` | `cause`, `raisonnement`, `confiance` (0-1), `preuves_manquantes` | `RootCause` |
| `RemediationPlan` | `immediat`, `court_terme`, `long_terme` | `Remediation` |
| `IncidentReport` | `titre`, `fenetre`, `impact`, `cause_racine`, `confiance`, `remediation`, `precedent_lie`, `texte` | `Summary` |
| `RemediationApprovalRequest` | `incident`, `root_cause`, `kb_matches`, `message` | `HumanApprovalExecutor` (HITL gate) |

### `SharedContext` — the central state

`SharedContext` is the single object that travels between all executors (via
`ctx.send_message`) and accumulates the results:

```python
class SharedContext(BaseModel):
    raw_logs: str
    log_analysis: LogAnalysis | None = None
    incident: Incident | None = None
    kb_matches: KBMatches | None = None
    root_cause: RootCauseHypothesis | None = None
    remediation_plan: RemediationPlan | None = None
    report: IncidentReport | None = None
    loop_count: int = 0
    root_cause_history: list[RootCauseHypothesis] = []
    evidence_log: list[str] = []
    approved: bool | None = None
```

- The "point-in-time" fields (`log_analysis`, `incident`, `root_cause`, …) are
  **reassigned** on each pass — they only reflect the latest value.
- The "cumulative" fields (`root_cause_history`, `evidence_log`) are
  **extended** (`.append`/`.extend`) — they keep the complete history,
  in particular the two `RootCause` passes in case of a reflection loop.
- `loop_count` is incremented by `GatherEvidenceExecutor`, and it is this value,
  combined with `confiance`, that determines the loop's exit (see
  `how-it-works.md` §3).

For the exact propagation (shared reference vs copies, streaming
semantics), see `how-it-works.md` §1.

## 7. Tools (`src/tools/`)

### 7.1 RAG knowledge base (`knowledge_base.py`)

`KnowledgeBase` interface: `async def search(incident, *, top_k=2) ->
list[KBMatch]`.

- **`LocalKnowledgeBase`** (mode `KB_MODE=local`, default) — reads
  `data/knowledge_base.json` and computes a **Jaccard similarity
  score** between the vocabulary of the current incident (`services` +
  `symptomes`) and that of each precedent (`services` + `symptomes` +
  `tags`). The knowledge base holds four past incidents; with `top_k=2`,
  only the two highest-scoring matches are returned (acceptance criterion 2 of `SPEC.md`).
- **`AzureAISearchKnowledgeBase`** (mode `KB_MODE=azure_search`) — queries
  an Azure AI Search index via `azure.search.documents.aio.SearchClient`,
  same interface.

`get_knowledge_base(settings)` picks based on `settings.kb_mode`.

### 7.2 Persistence (`persistence.py`)

`PersistenceStore` interface: `save(record)`, `list_records(*, limit=20)`,
`get_record(run_id)`.

- **`LocalPersistenceStore`** (default, without `COSMOS_ENDPOINT`) — a
  JSON file per run under `output/runs/`.
- **`CosmosPersistenceStore`** (if `COSMOS_ENDPOINT` is set) — a
  document per run in an Azure Cosmos DB container (partition key
  `/id`), via `azure.cosmos.aio.CosmosClient`. The account/database/container are
  provisioned by `infra/`; the code only does data-plane operations.

`get_persistence_store(settings)` picks based on `settings.cosmos_endpoint`.
`IncidentRecord` (full record, incl. `SharedContext`) and
`IncidentRecordSummary` (summarized view for the history list) are defined
in this module.

## 8. Orchestrator (`src/orchestrator/`)

Overview here; detailed mechanics (loop, HITL, propagation) in
[`how-it-works.md`](how-it-works.md).

### 8.1 `graph.py` — `build_workflow(settings)`

Builds the `Workflow` (`WorkflowBuilder(start_executor=log_analyzer,
output_from="all")`):

1. Instantiates `light_client`/`strong_client` (`get_chat_client`) and
   `knowledge_base` (`get_knowledge_base`).
2. Instantiates the 8 executors (one per graph node; `log_analyzer_agent`
   and `kb_search_agent` are **shared** between the main pipeline and
   `GatherEvidenceExecutor`).
3. Chains `log_analyzer -> incident_extractor -> kb_search -> root_cause`.
4. Adds the conditional edge (`add_switch_case_edge_group`) after
   `root_cause`: `Case(needs_more_evidence -> gather_evidence)`,
   `Default(-> human_approval)`.
5. `add_edge(gather_evidence, root_cause)` closes the loop.
6. Chains `human_approval -> remediation -> summary`.

### 8.2 `executors.py` — the 8 executors

| Executor | Wrapped agent | Particularity |
|-----------|------------------|----------------|
| `LogAnalyzerExecutor` | `LogAnalyzerAgent` | first node |
| `IncidentExtractorExecutor` | `IncidentExtractorAgent` | — |
| `KBSearchExecutor` | `KBSearchAgent` | — |
| `RootCauseExecutor` | `RootCauseAgent` | feeds `root_cause_history` |
| `GatherEvidenceExecutor` | reuses `LogAnalyzerAgent` + `KBSearchAgent` | increments `loop_count`, targets `preuves_manquantes` |
| `HumanApprovalExecutor` | none (pure gate) | `ctx.request_info()` + `@response_handler`, state on `self._context` |
| `RemediationExecutor` | `RemediationAgent` | runs only if approved |
| `SummaryExecutor` | `SummaryAgent` | terminal, `yield_output` only |

Every executor (except `SummaryExecutor` and the rejection case of
`HumanApprovalExecutor`) calls `ctx.yield_output(context)` (for
streaming observability) **then** `ctx.send_message(context)` (to
advance through the graph).

## 9. API (`src/api/`)

FastAPI exposing `build_workflow` over HTTP, consumed by the React frontend.

| Module | Role |
|--------|------|
| `app.py` | `create_app()`: CORS (Vite dev), mounts the routers under `/api`, `GET /api/health`, and — in production — serves `frontend/dist/` via `StaticFiles` (same port, no CORS). |
| `runs.py` | `POST /api/runs` and `POST /api/runs/{run_id}/approval` — the two SSE endpoints that drive the workflow. In-memory registry `app.state.runs: dict[str, RunState]`. |
| `history.py` | `GET /api/history` (summarized list) and `GET /api/history/{run_id}` (detail), via `PersistenceStore`. |
| `meta.py` | `GET /api/meta` — non-sensitive settings exposed to the UI (`confidence_threshold`, `max_reflection_loops`, `kb_mode`, `use_real_azure_openai`, `cosmos_enabled`). |
| `dependencies.py` | `settings_dependency`/`persistence_dependency` indirection to let tests override via `app.dependency_overrides`. |
| `sse.py` | `sse_event(event, data)` — formats an SSE message (`event: ...\ndata: ...\n\n`). |

The detail of the SSE protocol (events, two phases, state management between
the two HTTP calls) is in `how-it-works.md` §5.

## 10. Frontend (`frontend/`)

React + Vite + TypeScript. In dev, `vite.config.ts` proxies `/api` to
`127.0.0.1:8000` (no CORS); in prod, `frontend/dist/` is served by
FastAPI (same-origin).

| File | Role |
|---------|------|
| `src/App.tsx` | Page state (`phase`, `steps`, `approvalRequest`, …), wires the SSE callbacks to `api.ts`, assembles the components. |
| `src/api.ts` | HTTP/SSE client: `startRun`, `submitApproval` (parse the `text/event-stream` stream via `fetch` + `ReadableStream`, since `EventSource` doesn't support POST), `fetchMeta`, `fetchHistory`, `fetchHistoryRecord`. |
| `src/types.ts` | Types mirroring `src/models.py` 1:1 + responses from `src/api/*.py`. Kept up to date manually (a single set of contracts lives on the backend side). |
| `src/components/PipelineHUD.tsx` | SVG pipeline animation of the 8-node graph (mirrors `graph.py`): 6 agent nodes + the `GatherEvidence` loop node + the `HumanApproval` diamond, with a "Pipeline Status" readout and a RUN id badge, driven by `step` events. |
| `src/components/ActivityFeed.tsx` | Scrolling "Orchestration Log" feed. |
| `src/components/DetailPanel.tsx` | Detailed rendering of each agent's structured output, via internal per-executor views (`LogAnalysisView`, `IncidentView`, `KBMatchesView`, `RootCauseView`, `GatherEvidenceView`, `RemediationPlanView`, `SummaryView`, `RejectionView`). |
| `src/components/ApprovalCard.tsx` | HITL gate: displays incident/cause/precedents/confidence gauge, Approve/Reject buttons. Embedded inside `DetailPanel` (not standalone). |
| `src/components/ConfidenceBar.tsx` | `confiance` gauge vs `CONFIDENCE_THRESHOLD`. |
| `src/components/Header.tsx` | Title, Live Run/History tabs, SoftwareOne/VivaTech branding. (No longer renders configuration badges from `/api/meta`.) |
| `src/components/History.tsx` | List of past runs + detail view of a record. |

## 11. Infrastructure (`infra/`, `azure.yaml`)

Azure provisioning via Bicep + Azure Developer CLI (`azd`). Details and
step-by-step guide in [`deployment.md`](deployment.md) §Azure; full list
of resources and rationale in `DECISIONS.md` #21-22.

| File | Role |
|---------|------|
| `azure.yaml` | Declares the `api` service (`language: docker`, `host: containerapp`, `docker.path: ./Dockerfile`). |
| `infra/main.bicep` | `subscription` scope: creates the resource group, computes `resourceToken`, delegates to `resources.bicep`. |
| `infra/resources.bicep` | Resource group scope: ~13 resources (Log Analytics, App Insights, managed identity, Container Registry, Azure OpenAI + 2 deployments, Azure AI Search, Cosmos DB serverless, Container Apps Environment + Container App) + role assignments. |
| `infra/main.parameters.json` | `azd` parameters (`${AZURE_ENV_NAME}`, `${AZURE_LOCATION}`, `${AZURE_PRINCIPAL_ID}`). |

## 12. Technical stack

| Domain | Choice |
|---------|-------|
| Backend language | Python 3.11+ |
| Agent orchestration | `agent-framework` (`WorkflowBuilder`, `Executor`, `ctx.request_info`) |
| Models | Azure OpenAI — `gpt-4o` (strong), `gpt-4o-mini` (light); offline mode via `StubChatClient` |
| Contract validation | `pydantic` v2 |
| Configuration | `pydantic-settings` (`.env`) |
| API | FastAPI + `uvicorn`, SSE (`text/event-stream`) |
| Frontend | React + Vite + TypeScript |
| RAG | `data/knowledge_base.json` (local) or Azure AI Search |
| Persistence | local JSON files (`output/runs/`) or Azure Cosmos DB |
| Azure auth | `AzureCliCredential` (local) / `DefaultAzureCredential` (deployed, Managed Identity) |
| Containerization | multi-stage Dockerfile (frontend build + Python image) |
| IaC / deployment | Bicep + Azure Developer CLI (`azd`), Azure Container Apps |
| Observability | Application Insights provisioned, with OTel instrumentation wired via `configure_observability` whenever `APPLICATIONINSIGHTS_CONNECTION_STRING` is set (no-op in offline demo mode) |
