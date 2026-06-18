# Documentation

Detailed project documentation, complementing `SPEC.md` (JSON contracts
and acceptance criteria), `DECISIONS.md` (architecture decision log)
and `scenario-demo-incident-paiement.md` (presentation script).

| Document | Content |
|----------|---------|
| [`architecture.md`](architecture.md) | All system components, their role, their data contracts; design principles and non-negotiable constraints. |
| [`how-it-works.md`](how-it-works.md) | Internal mechanics: orchestration graph topology, reflection loop, human-in-the-loop, SSE flow, `SharedContext` propagation. |
| [`deployment.md`](deployment.md) | Deployment guide: local dev (CLI/UI), configuration, Docker, Azure via `azd`. |
| [`demo-guide.md`](demo-guide.md) | Step-by-step demo guide (CLI and web UI), with concrete values from the bundled scenario, variants (human decline, real Azure OpenAI). |

## Where to start?

- **Discover the project**: `README.md` (root) for the quick start,
  then `architecture.md` for the component overview.
- **Understand the orchestration**: `how-it-works.md`, alongside
  `src/orchestrator/graph.py` and `src/orchestrator/executors.py`.
- **Deploy**: `deployment.md`.
- **Present the demo**: `demo-guide.md` (practical walkthrough) and
  `scenario-demo-incident-paiement.md` (presentation script, message to
  convey).
