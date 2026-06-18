# Demo guide

> Practical walkthrough — commands and expected output, for the CLI and the
> web UI, with concrete values from the bundled scenario
> (`data/payment-incident.log` + `data/knowledge_base.json`). For the
> **presentation script** (talking points, timing, hook lines), see
> `scenario-demo-incident-paiement.md`. For the architecture, see
> [`architecture.md`](architecture.md) / [`how-it-works.md`](how-it-works.md).

## 1. The message to convey

Three things, in order:

1. **Decomposition** — each agent has a single responsibility; you inspect
   the artifact produced at every step (not "one big prompt").
2. **Living orchestration** — faced with doubt (confidence < threshold), the
   orchestrator **loops back** to gather more evidence instead of
   concluding.
3. **Security by design** — on a payment system, no corrective action is
   ever executed without **human validation**.

## 2. Preparation

Offline mode (default, no Azure credentials — see
[`deployment.md`](deployment.md) §1):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

The demo incident (`data/payment-incident.log`) is **deliberately
ambiguous**: a deployment (`payment-api v2.4.1`, 14:00) reduces
`db.max_pool_size` from 40 to 20, which saturates the connection pool
starting at 14:22 and pushes the payment failure rate from 0.18% to 38% by
14:24. In parallel, Stripe call latency is slightly elevated (780-820ms vs.
600ms p95) — a plausible red herring. The knowledge base
(`data/knowledge_base.json`) holds several past incidents; two of them are
directly relevant precedents for this scenario: `INC-204` (pool exhaustion
after a config change) and `INC-187` (Stripe latency spike).

With `StubChatClient` (offline mode), responses are **deterministic** and
reproduce this scenario exactly, including the reflection loop (`RootCause`:
confidence 0.55, then 0.92).

## 3. Walkthrough — CLI

```bash
python -m src.main --logs data/payment-incident.log
```

### Header

```
==============================================================================
DEMO - Multi-agent diagnosis of a payment incident
==============================================================================
Scenario                : db_pool
Source logs             : data/payment-incident.log
Confidence threshold    : 0.75
Max reflection loops    : 2
Knowledge base          : local
Models                  : StubChatClient (offline)
```

### Agent 1/6 — LogAnalyzer

```
Reconstructed timeline:
  - 14:00:11  Deployment payment-api v2.4.1 started (rolling, 6 pods, 90s window)
  - 14:00:12  Config applied - db.max_pool_size set to 20 (previous value: 40) via ConfigMap patch
  - 14:04:33  Rolling deployment complete - all 6 pods on v2.4.1
  - 14:16:02  DB pool utilisation crosses 70% threshold (first alert suppressed - below configured 85% limit)
  - 14:22:47  Pool 100% saturated: 20/20 connections acquired, 0 available
  - 14:23:15  First connection acquisition timeout after 5000ms - payment persistence failing
  - 14:23:31  Stripe API latency: 780ms p95 (baseline 600ms, +30% deviation)
  - 14:24:50  Error rate at 38% over 60s window - SEV-1 threshold exceeded
  - 14:26:30  Client retry storm: inbound traffic 3.4x baseline, amplifying pool backpressure
  - 14:29:18  Stripe API latency returns to 640ms - within normal variance
Detected anomalies:
  - DB connection pool: 70% -> 100% saturation in under 7 minutes (14:16-14:22), followed by immediate cascading persistence failures
  - Payment error rate: 0.18% -> 38% in 25 minutes - catastrophic success rate degradation
  - Client retry storm at 3.4x baseline - positive feedback loop amplifying already saturated pool
  - Stripe gateway latency transient spike +30% (14:23-14:29), self-resolved - temporal overlap with error surge but independent trajectory
  - Connection acquisition timeouts unbounded (no explicit timeout configured) - requests block indefinitely
Correlated events:
  - Deployment v2.4.1 (14:00:11) preceded pool saturation (14:22:47) by 22 min 36s - consistent with load accumulation under halved pool capacity
  - db.max_pool_size change applied at the exact deployment timestamp: the only infrastructure delta between v2.4.0 and v2.4.1 visible in logs
  - Stripe latency spike (14:23-14:29) coincides with error surge but self-resolves: insufficient to explain 18-minute persistence of saturation
```

> *"First agent: it turns noise into signal — it has already spotted the
> 14:00 deployment and the pool saturation."*

### Agent 2/6 — IncidentExtractor

```
Title    : SEV-1: DB pool exhaustion following payment-api v2.4.1 deployment
Severity : SEV-1
Services : payment-api, db-pool, postgres-primary
Window   : 14:23 -> 14:41 UTC (18 minutes, resolved by rollback)
Symptoms :
  - DB connection pool saturated at 100% (20/20) - zero connections available for 18 minutes
  - Payment transaction persistence failures: 38% error rate at peak (vs 0.18% baseline)
  - Client retry storm amplifying inbound load to 3.4x baseline, worsening pool backpressure
  - Connection acquisition timeouts unbounded - no hard limit configured, requests queued indefinitely
  - Stripe API latency transient (+30%) - self-resolved, investigated and ruled out as causal factor
```

> *"The JSON contract that the downstream agents will consume — not free
> text."*

### Agent 3/6 — KBSearch

```
Precedents found:
  - INC-204  (similarity=0.98)
    -> resolution: Rollback deployment to v2.4.0 and restore db.max_pool_size=40 via emergency ConfigMap patch. Root cause was identical: ConfigMap change halved the pool, exhausting connections under nominal load. Prevention applied: mandatory infrastructure config review gate added to CI pipeline.
  - INC-187  (similarity=0.52)
    -> resolution: Deployed circuit breaker with exponential backoff on Stripe payment processor calls. Root cause: external processor degradation causing cascading timeouts and connection hold-time spikes. Pattern mismatch here: Stripe recovered independently; pool saturation persisted - this precedent does not apply.
```

> *"Two precedents that both fit. Ambiguity."*

### Agent 4/6 — RootCause (1st pass)

```
Selected cause : Two competing hypotheses remain unresolved with current evidence: (A) db.max_pool_size halved by v2.4.1 ConfigMap patch, saturating the pool under nominal load; (B) Stripe gateway degradation causing connection hold-time spikes that exhaust the pool via backpressure
Reasoning      : Both hypotheses explain the pool saturation and error surge. The v2.4.1 deployment at 14:00 halved db.max_pool_size from 40 to 20 immediately before the incident window - a strong temporal correlation. Simultaneously, Stripe API latency elevated to 780ms at 14:23 (+30%), which could independently extend transaction hold-times and exhaust connections via a different mechanism. Precedent INC-204 matches hypothesis A (pool config change, same resolution). Precedent INC-187 matches hypothesis B (Stripe degradation, different resolution). The two precedents point to opposite root causes and therefore incompatible remediation strategies. Definitive discrimination requires: the exact pool config diff from the v2.4.1 ConfigMap, and the Stripe latency trajectory after 14:26 - whether it self-resolved while the pool remained saturated is the critical discriminator between the two hypotheses.
Confidence     : 0.55  (threshold = 0.75)
-> Confidence below threshold: the orchestrator loops back to gather more evidence (pass 1/2).
Missing evidence to collect:
  - v2.4.1 ConfigMap diff: confirm db.max_pool_size value before and after deployment
  - Stripe latency trajectory after 14:26 - did it recover while pool remained saturated?
  - DB pool utilisation trend between 14:04 (deploy complete) and 14:16 (70% threshold) to model depletion rate
```

### ⭐ Highlight #1 — the reflection loop

> *"Watch this: the orchestrator refuses to go further while in doubt (0.55
> < 0.75). It decides to gather more evidence instead."*

### Reflection loop — GatherEvidence

```
Loop 1/2: LogAnalyzer and KBSearch re-invoked.
New correlated events:
  - Stripe recovery (14:29) did NOT correlate with incident recovery - Stripe is not the root cause
  - Pool saturation onset ~22 min post-deploy matches expected depletion under halved capacity (~18 TPS nominal load)
Knowledge base re-checked: INC-204, INC-187
```

### Agent 4/6 — RootCause (2nd pass)

```
Selected cause : Deployment payment-api v2.4.1 reduced db.max_pool_size from 40 to 20 via ConfigMap patch, exhausting the DB connection pool under nominal production load within 22 minutes
Reasoning      : Evidence gathered in reflection loop 1 conclusively resolves the ambiguity: (1) v2.4.1 ConfigMap diff confirms db.max_pool_size reduced 40->20 - the only infrastructure change in this deployment. (2) Stripe API latency returned to baseline (640ms) at 14:29, yet pool saturation persisted until rollback at 14:41. The 12-minute gap between Stripe recovery and incident resolution eliminates hypothesis B entirely: if Stripe were the cause, incident recovery would have followed Stripe's normalisation. It did not. (3) The 22-minute depletion window is mechanistically consistent with ~18 TPS nominal payment load exhausting 20 connections, whereas 40 connections would have provided sufficient headroom. Hypothesis B (Stripe degradation) is eliminated. Hypothesis A (pool config change) is confirmed. Precedent INC-204 is a direct match: identical root cause, identical resolution path.
Confidence     : 0.92  (threshold = 0.75)
-> Confidence sufficient: the orchestrator proceeds to human approval.
```

> *"This time it's settled: Stripe was a red herring. The real cause is the
> deployment. Confidence 0.92 — let's move forward."*

### ⭐ Highlight #2 — human validation

```
==============================================================================
Human approval required before remediation
==============================================================================
Incident           : SEV-1: DB pool exhaustion following payment-api v2.4.1 deployment (SEV-1)
Services           : payment-api, db-pool, postgres-primary
Selected cause     : Deployment payment-api v2.4.1 reduced db.max_pool_size from 40 to 20 via ConfigMap patch, exhausting the DB connection pool under nominal production load within 22 minutes
Confidence         : 0.92
Related precedents : INC-204, INC-187

Approve proceeding to remediation?
Reminder: remediation stays a displayed plan, no action is ever executed (CLAUDE.md).
Approve proceeding to remediation? [y/N]:
```

> *"This is a payment system: nothing executes without a human signing off.
> The orchestrator is waiting for my go-ahead."*

Type `y` (or `yes`) to approve.

### Agent 5/6 — Remediation (shown only if approved)

```
Immediate:
  - Rollback payment-api to v2.4.0 OR apply emergency ConfigMap patch restoring db.max_pool_size=40 without full rollback (faster, lower risk)
  - Drain and reset DB connection pool: force-close stale acquired connections to unblock recovery immediately
  - Apply client-side backoff config: exponential backoff, max 3 retries, 2s base delay - suppress retry storm
Short term:
  - Add Prometheus alert: pool utilisation >80% for >60s triggers PagerDuty (currently no alert on this metric - first notification came from users)
  - Set explicit connection acquisition timeout: hard limit 3000ms with structured error log and 503 response (currently unbounded)
  - Update deployment runbook: any ConfigMap change to db.*, worker_count, or queue_depth requires load-test sign-off before prod rollout
  - Add automated canary: 5% traffic to new version for 10 min, automatic rollback if error rate >2%
Long term:
  - Introduce mandatory infrastructure config review gate in CI pipeline: changes to pool, worker, or queue parameters require Platform team approval
  - Evaluate PgBouncer connection pooler to decouple application pool config from database connection limits
  - Implement connection pool headroom trending dashboard: visualise capacity buffer over time to catch erosion before exhaustion
```

### Agent 6/6 — Summary

```
INCIDENT REPORT - SEV-1
===============================================
 Title    DB Pool Exhaustion - payment-api v2.4.1
 Window   14:23 -> 14:41 UTC  (18 min resolved)
 Impact   38% payment failure rate - ~3,400 transactions lost
 Decision Rollback approved and applied
-----------------------------------------------

ROOT CAUSE  (confidence 0.92 / threshold 0.75)
Deployment v2.4.1 halved db.max_pool_size from 40 to 20
via ConfigMap patch - the only infrastructure change in
this release. Under nominal production load (~18 TPS), the
pool exhausted within 22 minutes, blocking all transaction
persistence. A Stripe API latency transient (+30%) was
investigated as hypothesis B and eliminated: Stripe recovered
at 14:29 while pool saturation persisted until 14:41 - a
12-minute gap that rules out Stripe as the causal factor.

AI ORCHESTRATION TRACE
  Loop 1 -> Root Cause confidence: 0.55  (below 0.75)
    Missing: pool diff, Stripe trajectory post-14:26
  Loop 2 -> Root Cause confidence: 0.92  [threshold met]
    Stripe hypothesis eliminated. DB pool config confirmed.

REMEDIATION (proposed - not executed on live systems)
  IMMEDIATE   Rollback to v2.4.0; restore db.max_pool_size=40
              Drain stale connections; apply client retry backoff
  SHORT-TERM  Pool utilisation alert (>80%); timeout 3000ms
              Canary deployment policy; runbook updated
  LONG-TERM   CI infra config review gate; PgBouncer eval
              Capacity headroom trending dashboard

PRECEDENT  INC-204 - identical pattern, same resolution
===============================================
```

```
==============================================================================
END
==============================================================================
Demo finished: final report displayed above.
```

> *"And there's the deliverable: a report you can paste straight into the
> post-mortem."*

## 4. Walkthrough — Web UI (FastAPI + React)

```bash
# Terminal 1
uvicorn src.api.app:app --reload
# Terminal 2
cd frontend && npm run dev
```

Open http://localhost:5173.

1. **Header**: title, "Live Run" / "History" tabs, and the event badge. The
   configuration values (`confidence_threshold`, `max_reflection_loops`,
   `kb_mode`, ...) returned by `GET /api/meta` are consumed elsewhere in the
   UI (the confidence gauges, the history view) rather than shown as header
   badges.
2. Pick a scenario in the **scenario selector** at the bottom (one button
   per entry from `GET /api/scenarios`, e.g. `db_pool` / `paypal_integration`
   — hover a button to see its description), then click **"Run
   Diagnostic"** → `POST /api/runs` (SSE). The **`PipelineHUD`** starts
   animating an 8-node pipeline (the 6 agents, the `GatherEvidence` loop
   node, and the `HumanApproval` diamond), and the **`ActivityFeed`** next
   to it appends one log line per event as they arrive.
3. Clicking any visited node in `PipelineHUD` (or using the prev/next
   controls) shows that step's full output in the **`DetailPanel`** below —
   the same content as the CLI, in dedicated views:
   - `LogAnalyzer` → timeline + anomalies + correlations (3 columns).
   - `IncidentExtractor` → incident card (title, `SEV-1` severity pill,
     services, symptoms).
   - `KBSearch` → `INC-204` (similarity 98%) / `INC-187` (52%) cards with
     their resolution text.
   - `RootCause` (1st pass) → cause, reasoning, **`ConfidenceBar`** (0.55 <
     threshold 0.75, red bar), "confidence below threshold: the
     orchestrator loops back (pass 1/2)" message, plus the list of missing
     evidence.
   - `GatherEvidence` → "Loop 1/2: Log Analyzer and KB Search re-invoked",
     the new correlated events, the re-checked precedents.
   - `RootCause` (2nd pass) → `ConfidenceBar` at 0.92 (green, ≥ threshold),
     "confidence sufficient: proceeding to human approval".
4. The HITL gate appears as an **`ApprovalCard`** inside the `DetailPanel`
   once the run reaches `awaiting_approval`: incident severity pill and
   title, service chips, the selected cause with its confidence percentage,
   `ConfidenceBar`, related precedents (`INC-204 (98%)  ·  INC-187 (52%)`),
   the "no action will be executed on any live system" reminder, and two
   buttons, **Reject** / **Approve remediation**.
5. Click **"Approve remediation"** → `POST /api/runs/{run_id}/approval`
   (`{"approved": true}`). Two more pipeline nodes light up:
   - `Remediation` → three columns (Immediate / Short term / Long term).
   - `Summary` → the final report (`texte`) rendered as preformatted text.
6. Final status line: "Complete" (`PipelineHUD`'s status readout), with the
   approved/rejected outcome reflected below the controls.
7. **"History"** tab: the table lists the run that just finished (date,
   title, severity `SEV-1`, cause, confidence 0.92, "approved" badge).
   Clicking a row opens the detail view (`GET /api/history/{run_id}`):
   incident, root cause + confidence gauge, remediation plan, final report.

## 5. Variant: declining remediation

At the HITL step:

- **CLI**: answer anything other than `y`/`yes` (or EOF) to
  `Approve proceeding to remediation? [y/N]:`.
- **UI**: click **"Reject"**.

In both cases:

- No `RemediationPlan` or `IncidentReport` is generated or displayed.
- **CLI**: final message "Demo finished: remediation not executed (declined
  by human)."
- **UI**: the `DetailPanel` shows a rejection view ("the human declined
  remediation: the workflow stops here, no remediation plan is generated or
  displayed"), the pipeline status reads "Complete", and the activity feed's
  last entry reads "Remediation rejected — pipeline halted". The history
  entry for this run is recorded with a "rejected" badge and
  `context.approved === false`; its detail view shows neither a plan nor a
  report.

## 6. Variant: real Azure OpenAI

After following [`deployment.md`](deployment.md) §4 (`az login` + a real
`AZURE_OPENAI_ENDPOINT` in `.env`), restart the CLI or the UI: the "offline
(stub)" indicator becomes "Azure OpenAI".

The flow stays **structurally identical** (same 6 agents, same JSON
contracts, same topology), but with real models:

- The **exact values** (reasoning text, `confiance` scores, remediation
  wording) are **no longer guaranteed to match** the fixed scenario above.
- It's possible for **`RootCause`'s 1st pass to already exceed 0.75** — in
  that case the `GatherEvidence` loop **does not trigger**: this is correct
  orchestrator behavior (`needs_more_evidence` is just a function of the
  returned score), but it changes the demo flow (no "highlight #1").
- Conversely, if confidence stays low after `MAX_REFLECTION_LOOPS` rounds,
  the orchestrator still proceeds to human approval (`Default`) — the loop
  never blocks indefinitely.

> For a **reproducible** demo (presentation, workshop), prefer offline mode
> (`StubChatClient`), which guarantees the 0.55 → 0.92 scenario described
> above.

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|----------|------------------|----------|
| `AZURE_OPENAI_ENDPOINT` is set but the stub is still used | the endpoint is still the `https://<...>` placeholder from `.env.example` | set a real endpoint (`Settings.use_real_azure_openai` checks for the `https://<` prefix) |
| The UI shows "No runs recorded yet" in history | no run has **finished** yet (approved or rejected) | complete at least one run through to `done` |
| `npm run dev` can't find `/api/*` | the API (`uvicorn`) isn't running on port 8000 | start `uvicorn src.api.app:app --reload` (the Vite proxy targets `127.0.0.1:8000`) |
| `PipelineHUD` doesn't show the pass through `human_approval` after approval | expected behavior (`DECISIONS.md` #19): this node only emits a `step` on **rejection**; on approval, passage through the gate is inferred from the presence of a `remediation` step | no action needed |
| `KB_MODE=azure_search` but `KBSearch` returns no precedent | the Azure AI Search index provisioned by `azd up` is **empty** (no indexing pipeline) | index `data/knowledge_base.json` (see [`deployment.md`](deployment.md) §5) or switch back to `KB_MODE=local` |
