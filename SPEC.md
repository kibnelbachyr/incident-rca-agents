# SPEC.md — Detailed specification

Demo: analysis and debugging of payment incidents by orchestrated AI agents, on
Microsoft Agent Framework + Azure. Read `CLAUDE.md` first (stack, conventions,
constraints). The presentation flow is in `scenario-demo-incident-paiement.md`.

---

## 1. Goal & scope

**Goal.** Starting from raw logs of a payment system, automatically produce:
a structured incident, similar past incidents, a root-cause hypothesis with
confidence, a remediation plan (proposed, validated by a human), and a final report.

**Out of scope.** No action is executed on a real system; the remediation
is a displayed plan. No real-time ingestion; a log file is injected.

---

## 2. Architecture

Six specialized agents, an orchestrator, a knowledge base as a resource.

| # | Agent | Role | Suggested model |
|---|-------|------|----------------|
| 1 | `LogAnalyzer` | Normalizes logs, detects anomalies + timeline | light (e.g. GPT-4o-mini) |
| 2 | `IncidentExtractor` | Produces the structured incident object | light |
| 3 | `KBSearch` | Queries the knowledge base (RAG) | light |
| 4 | `RootCause` | Root-cause hypothesis + confidence score | strong (GPT-4o) |
| 5 | `Remediation` | Mitigation plan + fix (behind HITL) | strong |
| 6 | `Summary` | Writes the final incident report | light |

The **orchestrator** holds the shared context (the incident object, which grows),
sequences the agents, applies the reflection loop and the validation gate.
The agents are stateless: they receive the context, perform their task, return
JSON. They never communicate with each other directly.

---

## 3. Stack & dependencies

- `agent-framework` (pre-release) — `WorkflowBuilder`, `ChatAgent`, HITL request/response.
- `agent_framework.azure.AzureOpenAIChatClient` — model client.
- `azure-identity` — `AzureCliCredential` (local) / `DefaultAzureCredential` (deployed).
- `azure-search-documents` — Azure AI Search access (KB agent in deployed mode).
- `pydantic` — I/O contract validation.

Creating an agent (official pattern, to be adapted per agent):

```python
import os
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import AzureCliCredential

client = AzureOpenAIChatClient(
    endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    model=os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"],
    credential=AzureCliCredential(),
)

root_cause_agent = client.create_agent(
    name="RootCause",
    instructions=ROOT_CAUSE_INSTRUCTIONS,  # see §4
    temperature=0.2,
)
```

---

## 4. Data contracts between agents

All agents return **only** valid JSON (no Markdown wrapping it).
Schemas are validated by pydantic in `src/models.py`.

**1 — LogAnalyzer** → `LogAnalysis`
```json
{
  "timeline": [{"time": "14:00:11", "event": "deploy payment-api v2.4.1"}],
  "anomalies": ["pool saturated at 14:23", "error rate 0.2% → 38%"],
  "correlated_events": ["deployment v2.4.1 ~20 min before the saturation"]
}
```

**2 — IncidentExtractor** → `Incident`
```json
{
  "titre": "Spike in payment failures",
  "severite": "SEV-1",
  "services": ["payment-api", "db-pool"],
  "fenetre": "14:23 → ongoing",
  "symptomes": ["transaction persistence failure", "pool saturated", "retry storm"]
}
```

**3 — KBSearch** → `KBMatches`
```json
{
  "matches": [
    {"id": "INC-204", "similarite": 0.98, "resolution": "rollback + pool to 40"},
    {"id": "INC-187", "similarite": 0.52, "resolution": "Stripe circuit breaker"}
  ]
}
```

**4 — RootCause** → `RootCauseHypothesis`
```json
{
  "cause": "The v2.4.1 deployment reduced max_pool_size from 40 to 20",
  "raisonnement": "The saturation follows the deployment; Stripe latency is within normal range",
  "confiance": 0.92,
  "preuves_manquantes": []
}
```
- `confiance` ∈ [0,1]. If `< CONFIDENCE_THRESHOLD`, fill in `preuves_manquantes`
  (what the orchestrator must go gather on the next turn).

**5 — Remediation** → `RemediationPlan` (produced after human approval)
```json
{
  "immediat": ["rollback v2.4.1 or raise max_pool_size back to 40"],
  "court_terme": ["acquisition timeout", "alert at 80% pool usage"],
  "long_terme": ["review gate on infra config changes"]
}
```

**6 — Summary** → `IncidentReport` (formatted text + key fields; see scenario §5).

---

## 5. Orchestration behavior

Implement with `WorkflowBuilder` (executor graph). Each executor wraps
an agent and updates the shared context.

Topology:

```
logs → LogAnalyzer → IncidentExtractor → KBSearch → RootCause → [confidence decision]
                                                          ▲                │
                              (targeted missing evidence) │                │ confidence ≥ threshold
                                          GatherEvidence ──┘                ▼
                                                              [HITL: human validation]
                                                                           │ approved
                                                                           ▼
                                                              Remediation → Summary → report
```

**Reflection loop (conditional edge after `RootCause`)**
- If `confiance < CONFIDENCE_THRESHOLD` AND `loop_count < MAX_REFLECTION_LOOPS`:
  route to `GatherEvidence` (re-invokes `LogAnalyzer` on the `preuves_manquantes`
  and/or `KBSearch`), increment `loop_count`, go back into `RootCause`.
- Otherwise: continue to the validation gate.
- The loop is **bounded** by `MAX_REFLECTION_LOOPS` (never infinite).

**Validation gate (HITL before remediation)**
- The tool that triggers the remediation is marked `@tool(approval_mode="always_require")`,
  or else a `ctx.request_info()` node emits a `RequestInfoEvent` that the caller
  must approve before continuing.
- As long as the human has not approved, the workflow stays paused.

Streaming execution to see each step (and the HITL pause):

```python
async for event in workflow.run_stream(message=raw_logs):
    # display progress: each agent's output, loop decision, approval request
    handle(event)  # handles RequestInfoEvent → asks the user for approval
```

---

## 6. Demo data (provided)

- `data/payment-incident.log` — deliberately **ambiguous** incident: DB pool
  saturation after the v2.4.1 deployment, plus a slightly elevated Stripe
  latency (a red herring). This is what triggers the reflection loop: the 1st
  `RootCause` pass has low confidence, the 2nd pass is decisive after additional
  evidence.
- `data/knowledge_base.json` — four past incidents: `INC-204` (pool config),
  `INC-187` (Stripe latency), `INC-241` (webhook signature/header casing), and
  `INC-223` (PayPal outage). `KBSearch` queries with `top_k=2` (`src/agents/kb_search.py`),
  so it returns only the two highest-scoring matches for a given incident, not
  the whole knowledge base.

Expected tuning for the demo to "play out":
- 1st `RootCause` pass: confidence ≈ 0.55 (two plausible hypotheses) → loops back.
- 2nd pass: confidence ≈ 0.92, cause = `max_pool_size` change.

---

## 7. Azure deployment

Reference architecture (aligned with Microsoft docs):

| Component | Azure service | Role |
|-----------|---------------|------|
| LLM model | Azure OpenAI / Microsoft Foundry (GPT-4o) | agent reasoning |
| Knowledge base | Azure AI Search | RAG over past incidents + runbooks |
| Orchestration API | Azure Container Apps | hosts the orchestrator |
| Persistence (optional) | Azure Cosmos DB | incidents, decisions, history |
| Images | Azure Container Registry | versioned images |
| Observability | Application Insights | OpenTelemetry traces from the framework |
| Secrets | Azure Key Vault | keys, endpoints |

Steps (high level):
1. Provision Azure OpenAI + deploy a model (note the deployment name).
2. Create an Azure AI Search index and load `knowledge_base.json` into it (vectorized).
3. Containerize the orchestration API → push to Container Registry.
4. Deploy to Container Apps with Managed Identity (`DefaultAzureCredential`).
5. Connect Application Insights for telemetry.

Environment variables: see `.env.example`.

---

## 8. Acceptance criteria

The demo is validated if, on `data/payment-incident.log`:

1. `IncidentExtractor` produces a SEV-1 incident targeting `payment-api` / `db-pool`.
2. `KBSearch` returns **two** matches (`INC-204` and `INC-187`) out of the four
   incidents in the knowledge base.
3. The **1st pass** of `RootCause` comes out with a confidence **< 0.75** → the
   orchestrator **loops back** (the event is visible in the stream/traces).
4. The **2nd pass** comes out with a confidence **≥ 0.75** and identifies the
   `max_pool_size` change as the cause (the Stripe latency is ruled out).
5. The workflow **pauses** for human validation before the remediation
   (`RequestInfoEvent` / tool approval).
6. After approval, a `RemediationPlan` and then a final report are produced.
7. Each agent output is observable (event streaming).
8. The loop never exceeds `MAX_REFLECTION_LOOPS`.

---

## 9. Suggested implementation steps (for Claude Code)

1. Repo skeleton + `pyproject.toml` + `models.py` (pydantic contracts).
2. The 6 agents with their instructions (strict JSON outputs), tested in isolation
   on dummy inputs.
3. KB tool in local mode (`knowledge_base.json`); interface ready for Azure AI Search.
4. `WorkflowBuilder` graph: sequence + conditional edge (loop) + HITL node.
5. CLI `src/main.py` that injects the log, streams events, handles approval.
6. Verify the 8 acceptance criteria on the example incident.
7. Containerization + switch the KB to Azure AI Search + Azure environment variables.

---

## 10. References

- Agent Framework: https://learn.microsoft.com/agent-framework/overview/
- Workflows / orchestrations: https://learn.microsoft.com/agent-framework/workflows/orchestrations/
- Human-in-the-loop: https://learn.microsoft.com/agent-framework/workflows/human-in-the-loop
- Sequential + HITL: https://learn.microsoft.com/agent-framework/workflows/orchestrations/sequential
- Azure multi-agent architecture: https://learn.microsoft.com/azure/architecture/ai-ml/idea/multiple-agent-workflow-automation
- Orchestration patterns: https://learn.microsoft.com/azure/architecture/ai-ml/guide/ai-agent-design-patterns
- Azure AI Search (RAG): https://learn.microsoft.com/azure/search/
