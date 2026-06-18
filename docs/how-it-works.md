# Internal mechanics

> How the orchestration graph actually executes: `SharedContext`
> propagation, topology, reflection loop, human-in-the-loop (HITL), and
> the SSE flow. Best read with `src/orchestrator/graph.py` and
> `src/orchestrator/executors.py` open. For the list of components, see
> [`architecture.md`](architecture.md).

## 1. `SharedContext`: the backbone

The entire execution state lives in **a single pydantic object**,
`SharedContext` (`src/models.py`), which flows between executors via
`ctx.send_message(context)`. Agents are stateless and never see each other
directly: each executor reads what it needs from `context`, calls its
agent, **mutates `context` in place**, then forwards it.

### Reassignment vs accumulation

- **"Point-in-time" fields** (`log_analysis`, `incident`, `kb_matches`,
  `root_cause`, `remediation_plan`, `report`, `approved`) are **reassigned**
  on every pass: they only reflect the last value written.
- **"Cumulative" fields** (`root_cause_history`, `evidence_log`) are
  **extended** (`.append`/`.extend`): they keep the full history,
  notably both `RootCause` passes when a reflection loop occurs.
  `loop_count` is a counter incremented by `GatherEvidenceExecutor`.

### `yield_output` vs `send_message`

Each executor (except for the special cases detailed in §4) calls:

```python
await ctx.yield_output(context)   # observability: one "output" event per step
await ctx.send_message(context)   # advances the graph to the successor(s)
```

`yield_output` passes **a direct reference** to the mutable `SharedContext`,
not a copy. Consequence: at the end of a complete (non-streamed) `run()`,
all `type="output"` events in the result share the **same final object** —
a reassigned field (e.g. `root_cause`) only shows its last value when
inspected afterward, whereas the accumulated fields (`root_cause_history`,
`evidence_log`) keep the full history. This is why the orchestration tests
read `root_cause_history` to distinguish the 1st and 2nd `RootCause` pass.
**In streaming mode (`stream=True`)**, on the other hand, each `event.data`
received as it arrives is a snapshot relevant at the moment it was emitted —
this is what the CLI and the SSE API consume.

## 2. Graph topology (`build_workflow`, `src/orchestrator/graph.py`)

```python
workflow = (
    WorkflowBuilder(start_executor=log_analyzer, output_from="all")
    .add_edge(log_analyzer, incident_extractor)
    .add_edge(incident_extractor, kb_search)
    .add_edge(kb_search, root_cause)
    .add_switch_case_edge_group(
        root_cause,
        [
            Case(condition=needs_more_evidence, target=gather_evidence),
            Default(target=human_approval),
        ],
    )
    .add_edge(gather_evidence, root_cause)
    .add_edge(human_approval, remediation)
    .add_edge(remediation, summary)
    .build()
)
```

`output_from="all"`: **every** executor emits an `output` event (not just
the last one), which makes it possible to observe each agent's output
while streaming — including both `RootCause`/`GatherEvidence` passes.

### Construction (`build_workflow(settings)`)

1. **Chat clients**: `light_client = get_chat_client(settings,
   light=True)`, `strong_client = get_chat_client(settings, light=False)`
   (§5.2 of `architecture.md`).
2. **Knowledge base**: `knowledge_base = get_knowledge_base(settings)`.
3. **Shared agents**: `log_analyzer_agent = LogAnalyzerAgent(light_client)`
   and `kb_search_agent = KBSearchAgent(light_client, knowledge_base)` are
   instantiated **once** and injected both into
   `LogAnalyzerExecutor`/`KBSearchExecutor` (main pipeline) and into
   `GatherEvidenceExecutor` (reflection loop) — no agent duplication,
   consistent with the "six specialized agents" from `SPEC.md` §2.
4. **`needs_more_evidence`** is a **closure** that captures `settings`:

   ```python
   def needs_more_evidence(context: SharedContext) -> bool:
       return (
           context.root_cause.confiance < settings.confidence_threshold
           and context.loop_count < settings.max_reflection_loops
       )
   ```

   `Case(condition: Callable[[Any], bool], target=...)` only accepts a
   single argument (the `SharedContext` routed along the edge):
   `CONFIDENCE_THRESHOLD` and `MAX_REFLECTION_LOOPS` are therefore not part
   of a data contract — they're injected through the closure scope of
   `build_workflow`.

## 3. The reflection loop

This is **highlight #1** of the demo (`scenario-demo-incident-paiement.md`
§4): the orchestrator refuses to conclude on an insufficient confidence
score and goes to gather targeted evidence before trying again.

### Trigger

After `RootCauseExecutor`, the conditional edge evaluates
`needs_more_evidence(context)`:

- **True** (`confiance < CONFIDENCE_THRESHOLD` **AND** `loop_count <
  MAX_REFLECTION_LOOPS`) → routes to `GatherEvidenceExecutor`.
- **False** (confidence sufficient, or loop budget exhausted) → routes to
  `HumanApprovalExecutor` (`Default`).

### `GatherEvidenceExecutor`

1. Increments `context.loop_count`.
2. Rebuilds a **targeted** `LogAnalyzer` prompt:
   `build_log_prompt(context.raw_logs, focus=context.root_cause.preuves_manquantes)`
   — the `preuves_manquantes` from the last `RootCauseHypothesis` become the
   points to investigate as a priority.
3. Extends `context.evidence_log` with the new
   `log_analysis.correlated_events`.
4. Re-runs `KBSearchAgent.run(context.incident)` to re-confront past
   incidents in light of the new evidence.
5. `ctx.yield_output(context)` then `ctx.send_message(context)` →
   **back to `RootCauseExecutor`** (`add_edge(gather_evidence,
   root_cause)`), which this time receives a non-empty `evidence_log`
   (`build_prompt(..., evidence_log=context.evidence_log)`).

### Termination guarantee

The loop is **bounded by construction**: `needs_more_evidence` is
**impossible to satisfy indefinitely**, because `loop_count` is strictly
increasing and capped by `MAX_REFLECTION_LOOPS` (default **2**). Even if
confidence remains low after the maximum number of rounds, the `Default`
routes to `HumanApprovalExecutor` — the orchestrator always moves forward,
never an infinite loop (acceptance criterion 8 of `SPEC.md`).

### Walkthrough with the demo data (`StubChatClient`)

| Round | `loop_count` | `RootCause.confiance` | Decision |
|------|---------------|------------------------|----------|
| 1 | 0 | **0.55** (two competing hypotheses: DB pool vs Stripe latency) | `0.55 < 0.75` and `0 < 2` → **loops back** to `GatherEvidence` |
| 2 (after `GatherEvidence`, `loop_count=1`) | 1 | **0.92** (cause = `max_pool_size` 40→20, Stripe ruled out) | `0.92 >= 0.75` → **continues** to `HumanApproval` |

## 4. Human-in-the-loop (HITL)

This is **highlight #2**: on a payment system, no remediation is proposed
without explicit human validation.

### Mechanism: `ctx.request_info()` + `@response_handler`

`HumanApprovalExecutor` is a **pure** gate (it wraps no agent) that
carries instance state between two invocations:

```python
class HumanApprovalExecutor(Executor):
    def __init__(self, ...):
        self._context: SharedContext | None = None

    @handler
    async def handle(self, context: SharedContext, ctx: WorkflowContext) -> None:
        self._context = context
        request = RemediationApprovalRequest(
            incident=context.incident,
            root_cause=context.root_cause,
            kb_matches=context.kb_matches,
            message="...",
        )
        await ctx.request_info(request, response_type=bool)

    @response_handler
    async def handle_response(
        self,
        original_request: RemediationApprovalRequest,
        response: bool,
        ctx: WorkflowContext[SharedContext, SharedContext],
    ) -> None:
        context = self._context
        context.approved = response
        if response:
            await ctx.send_message(context)   # -> Remediation
        else:
            await ctx.yield_output(context)    # stop: no send_message
```

- `handle()` emits a `RequestInfoEvent` (`event.type == "request_info"`,
  `event.request_id`) containing a `RemediationApprovalRequest` — a
  **subset** of the context (incident, root cause, precedents) meant to be
  presented to the human.
- The `Workflow` and its executors **persist in memory** between two
  `workflow.run(...)` calls: `self._context` (the **full** `SharedContext`)
  therefore survives until `workflow.run(stream=True, responses={request_id:
  bool})` is called to resume execution.
- **Approval** (`response=True`): `context.approved = True`,
  `ctx.send_message(context)` → the graph continues to `RemediationExecutor`
  then `SummaryExecutor`.
- **Rejection** (`response=False`): `context.approved = False`,
  **only** `ctx.yield_output(context)` — no edge leaves `human_approval`
  toward an alternative terminal node; it's the **absence** of
  `send_message` that stops the graph (no more executors to invoke). The
  only observable output carries `approved=False`, `remediation_plan=None`,
  `report=None`: consistent with `CLAUDE.md` ("no remediation without
  validation").

> ⚠️ Why does `RemediationApprovalRequest` only carry a subset of the
> context? Because that subset is what needs to be **serialized** in the
> `request_info` event and presented to the human (CLI or `ApprovalCard` on
> the UI side). The full context doesn't need to cross the HITL boundary:
> it stays on `self._context` and resumes its path via `ctx.send_message`
> once the decision is known.

## 5. End-to-end execution flow

### 5.1 CLI (`src/main.py`)

```python
result = workflow.run(SharedContext(raw_logs=raw_logs), stream=True)
async for event in result:
    if event.type == "output":
        _print_step_output(event.executor_id, event.data, settings)
    elif event.type == "request_info":
        approved = _ask_approval(event.data)   # blocking input()
        break
await result.get_final_response()

if approved is not None:
    result = workflow.run(stream=True, responses={event.request_id: approved})
    async for event in result:
        if event.type == "output":
            _print_step_output(event.executor_id, event.data, settings)
    await result.get_final_response()
```

- **Phase 1**: streams `log_analyzer → incident_extractor → kb_search →
  root_cause → (gather_evidence → root_cause)* → human_approval`, up to the
  `RequestInfoEvent`. `_print_step_output` formats each output type
  (timeline, incident, KB precedents, root cause + loop verdict,
  evidence gathering).
- `_ask_approval` displays the incident / chosen cause / confidence /
  precedents and prompts `input("Approve proceeding to remediation?
  [y/N]: ")`. `EOFError` (non-interactive input) → rejection.
- **Phase 2** (if approved): resumes the **same** `workflow` with
  `responses={request_id: True}` → streams `remediation → summary`.
- If rejected: the workflow stops after phase 1, nothing further is
  displayed (no plan, no report).

### 5.2 Web UI (FastAPI SSE + React)

The **same** `build_workflow(settings)` is exposed via two SSE endpoints
(`src/api/runs.py`), with an in-memory registry `app.state.runs: dict[str,
RunState]` that keeps the `Workflow` alive between the two HTTP calls
(required since `HumanApprovalExecutor` carries state on `self._context`,
§4).

**`POST /api/runs`** — phase 1:

```python
run_id = uuid.uuid4().hex
workflow = build_workflow(settings)
runs[run_id] = RunState(workflow=workflow)

yield sse_event("run_started", {"run_id": run_id})

result = workflow.run(SharedContext(raw_logs=raw_logs), stream=True)
async for event in result:
    if event.type == "output":
        yield sse_event("step", {"executor_id": event.executor_id,
                                   "context": event.data.model_dump(mode="json")})
    elif event.type == "request_info":
        state.pending_request_id = event.request_id
        yield sse_event("approval_required", {"request": event.data.model_dump(mode="json")})
await result.get_final_response()
```

**`POST /api/runs/{run_id}/approval`** — phase 2 (`body: {"approved": bool}`):

```python
result = state.workflow.run(stream=True, responses={request_id: body.approved})
async for event in result:
    if event.type == "output":
        final_context = event.data
        yield sse_event("step", {...})
await result.get_final_response()

runs.pop(run_id, None)
if final_context is not None:
    await store.save(IncidentRecord(id=run_id, ..., approved=body.approved, context=final_context))
yield sse_event("done", {"approved": body.approved})
```

### SSE events

| Event | Payload | Emitted by |
|-----------|---------|----------|
| `run_started` | `{"run_id": str}` | `POST /api/runs`, immediately |
| `step` | `{"executor_id": str, "context": SharedContext}` | on each `event.type == "output"`, in both phases |
| `approval_required` | `{"request": RemediationApprovalRequest}` | `POST /api/runs`, on `event.type == "request_info"` |
| `done` | `{"approved": bool \| null}` | end of either phase |
| `error` | `{"message": str}` | any exception (the `run_id` is then removed from the registry) |

### 5.3 Frontend side (`frontend/src/`)

- `api.ts`: `EventSource` doesn't support POST, so `startRun`/
  `submitApproval` parse the `text/event-stream` stream themselves via
  `fetch` + `ReadableStream`, splitting on `\n\n` and dispatching based on
  the `event: ...` line.
- `App.tsx`: `phase` state machine (`idle → running → awaiting_approval →
  running → done`/`error`); each `step` is pushed into `steps`, rendered by
  `DetailPanel` (with internal per-executor views such as
  `LogAnalysisView`, `IncidentView`, `KBMatchesView`, `RootCauseView`,
  `GatherEvidenceView`, `RemediationPlanView`, `SummaryView`, and
  `RejectionView`); `approval_required` displays `ApprovalCard`, embedded
  inside `DetailPanel`.
- `PipelineHUD.tsx` animates the SVG pipeline (8 nodes: 6 agents plus the
  `GatherEvidence` loop node and the `HumanApproval` diamond), the
  "Pipeline Status" readout, and the RUN id badge, based on the
  `executor_id` values already seen in `steps`. `ActivityFeed.tsx` renders
  the scrolling "Orchestration Log" feed alongside it. Since
  `HumanApprovalExecutor` only emits a `step` **on rejection** (§4),
  passage through the HITL gate on **approval** is inferred from the
  presence of a `remediation` `step` in the stream (the node and the
  `root_cause -> human_approval -> remediation` edges are then marked as
  traversed).
- `History.tsx` queries `/api/history` (`IncidentRecordSummary[]`) and
  `/api/history/{run_id}` (full `IncidentRecord`, including the final
  `SharedContext`) to review a past run — including a rejected run
  (`context.approved === false`, no `remediation_plan`/`report`).

## 6. Observability

- **Streaming**: each agent output is emitted as it happens
  (`output_from="all"`), including the `RootCause <-> GatherEvidence` loop
  (acceptance criterion 7 of `SPEC.md`).
- **Application Insights**: `APPLICATIONINSIGHTS_CONNECTION_STRING` is
  provisioned by `infra/` and injected into the Container App. When set,
  `src/observability.py` wires it up via `configure_azure_monitor` and
  `enable_instrumentation`, exporting the Agent Framework's OpenTelemetry
  traces.
