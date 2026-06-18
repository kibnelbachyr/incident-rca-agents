# CLAUDE.md — Demo: multi-agent incident analysis system (payments)

> This file is read automatically by Claude Code. It describes the project, the
> stack, the conventions and the constraints. The detailed functional specification
> is in `SPEC.md`. The demo script is in `scenario-demo-incident-paiement.md`.

## Goal

Build a **demo** of an **orchestrated** multi-agent system that diagnoses an
incident on a payment system: it ingests logs, extracts the incident, queries
a knowledge base, looks for the root cause, proposes a remediation and writes
a report. The system must be **deployable on Azure** and built on the
**Microsoft Agent Framework**.

What must come across in the demo (top priority):
1. Specialized agents, each with a single responsibility and a clear I/O contract.
2. An **orchestrator** that drives, keeps state, and **decides** (loops back if in doubt).
3. A **reflection loop**: if root-cause confidence is below the threshold,
   the orchestrator loops back to gather more evidence instead of concluding.
4. A **human-in-the-loop**: no remediation is proposed/executed without validation.

## Tech stack

- **Language**: Python 3.11+.
- **Orchestration**: Microsoft Agent Framework (`pip install agent-framework` — pre-release).
  - Agents: `ChatAgent` via `agent_framework.azure.AzureOpenAIChatClient`.
  - Workflow: `WorkflowBuilder` (graph) to manage the conditional loop + HITL.
- **Model**: Azure OpenAI / Microsoft Foundry (GPT-4o or GPT-4.1 deployment).
- **Knowledge base (RAG)**: Azure AI Search (vector + keyword). Locally,
  start with `data/knowledge_base.json` then switch to Azure AI Search.
- **Persistence (optional for the demo)**: Azure Cosmos DB.
- **Target hosting**: Azure Container Apps (orchestration API); optional minimal UI.
- **Auth**: `AzureCliCredential` locally, `DefaultAzureCredential` / Managed Identity when deployed.
- **Observability**: framework OpenTelemetry telemetry → Application Insights.

## Expected layout

```
.
├── CLAUDE.md                 # this file
├── SPEC.md                   # detailed specification + agent contracts
├── scenario-demo-incident-paiement.md
├── .env.example
├── pyproject.toml
├── README.md
├── data/
│   ├── payment-incident.log  # sample logs to inject
│   └── knowledge_base.json   # past incidents + runbooks
└── src/
    ├── agents/               # one module per agent (instructions + contract)
    ├── orchestrator/         # WorkflowBuilder graph, threshold, loop, HITL
    ├── tools/                # KB search tool (Azure AI Search)
    ├── models.py             # pydantic/dataclass I/O contracts
    └── main.py               # demo CLI entry point
```

## Commands

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Azure login (local dev)
az login

# Run the demo on the sample incident
python -m src.main --logs data/payment-incident.log
```

## Conventions

- Each agent returns a **strict JSON contract** (see `SPEC.md` §4). Agents never
  talk to each other directly: everything goes through the orchestrator and the shared context.
- Structured outputs are validated (pydantic). Prompt agents to return
  **only** JSON, with no surrounding text or Markdown tags.
- "Light" model for extraction (mechanical task), "strong" model for root cause.
- Code, identifiers, and comments in English.

## Constraints NOT to bypass

- **Bounded loop**: `MAX_REFLECTION_LOOPS` (default 2). Never an infinite loop.
- **Confidence threshold**: `CONFIDENCE_THRESHOLD` (default 0.75). Below threshold → loop back.
- **Mandatory HITL**: the remediation step is behind human approval
  (`@tool(approval_mode="always_require")` or `ctx.request_info()`), even in the demo.
- **No real execution** of corrective action: the remediation is *proposed*, not
  applied to a real system. The demo only displays the plan after approval.
- **No secrets in plaintext**: everything via `.env` / environment variables / Key Vault.

## References (consult via the docs, don't guess the APIs)

- Agent Framework — overview: https://learn.microsoft.com/agent-framework/overview/
- Workflow orchestrations: https://learn.microsoft.com/agent-framework/workflows/orchestrations/
- Human-in-the-loop: https://learn.microsoft.com/agent-framework/workflows/human-in-the-loop
- Sequential orchestration + HITL: https://learn.microsoft.com/agent-framework/workflows/orchestrations/sequential
- Azure reference architecture (multi-agent): https://learn.microsoft.com/azure/architecture/ai-ml/idea/multiple-agent-workflow-automation
- Agent orchestration patterns: https://learn.microsoft.com/azure/architecture/ai-ml/guide/ai-agent-design-patterns
