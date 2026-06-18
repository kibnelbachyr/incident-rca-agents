# DECISIONS.md — Architecture decision log

Decisions made autonomously during development of the demo. One line of
context + rationale per decision, chronological order.

1. **`agent-framework` 1.8.x broke the names cited in the brief.**
   `ChatAgent` / `agent_framework.azure.AzureOpenAIChatClient` / `create_agent`
   no longer exist (verified by introspecting the installed package + the
   Microsoft Learn "Significant Changes" doc). Replaced by `Agent` (created via
   `BaseChatClient.as_agent(...)`) and
   `agent_framework.openai.OpenAIChatCompletionClient`, which routes to Azure
   OpenAI via `azure_endpoint=` / `credential=` / the `AZURE_OPENAI_*` variables.
   Complies with the instruction "if an API has changed, follow the docs, not
   the brief".

2. **Shared context = a single pydantic object (`SharedContext`) that travels
   as a message between `Executor`s** (`ctx.send_message`), rather than
   `ctx.set_state`/`get_state`. Simpler to inspect/log at every streaming
   step, and avoids any mutable global state shared across concurrent
   workflow runs.

3. **`StructuredChatClient` abstraction (Protocol) with two implementations**:
   `StubChatClient` (fixed, deterministic responses, zero network calls) and
   `AzureOpenAIStructuredChatClient` (real agents via `as_agent` +
   `default_options={"response_format": <PydanticModel>}`).
   `get_chat_client(settings, light=...)` automatically picks based on
   `Settings.use_real_azure_openai` (whether a real Azure OpenAI endpoint is
   configured or not). Lets the whole demo and the 8 acceptance criteria run
   offline, without Azure credentials.

4. **`StubChatClient` faithfully reproduces the demo scenario**, including the
   reflection loop: for the `RootCause` agent, the 1st call returns
   confidence 0.55 (two competing hypotheses + non-empty
   `preuves_manquantes`), the 2nd call (after `GatherEvidence`) returns
   confidence 0.92 and points to the `max_pool_size` change (Stripe ruled
   out). The other agents return a canonical response matching SPEC.md
   section 4 / section 6.

5. **`GatherEvidence` is NOT a 7th agent.** It's an orchestrator step (see
   SPEC.md section 5) that re-queries the `LogAnalyzer` agent (focused on the
   `preuves_manquantes`) and `KBSearch`, and merges the result into
   `SharedContext` before passing back into `RootCause`. Keeps exactly the
   "six specialized agents" from section 2.

6. **Reflection loop implemented with `add_switch_case_edge_group`** after the
   `RootCause` executor: `Case(needs_more_evidence -> GatherEvidence)`,
   `Default(-> HumanApproval)`, and `add_edge(GatherEvidence, RootCause)`
   closes the cycle. `needs_more_evidence` = `confiance < CONFIDENCE_THRESHOLD
   and loop_count < MAX_REFLECTION_LOOPS`: the loop is therefore bounded by
   construction (acceptance criterion 8).

7. **HITL gate implemented with `ctx.request_info(RemediationApprovalRequest,
   response_type=bool)` + `@response_handler`** rather than
   `@tool(approval_mode="always_require")`: remediation is a dedicated
   executor (not an isolated tool call), so pausing the executor itself via
   `request_info` is more direct and produces an observable `RequestInfoEvent`
   in the stream (acceptance criterion 5).

8. **`LocalKnowledgeBase` computes a real Jaccard similarity** between the
   vocabulary (services + symptomes) of the incident and that (services +
   symptomes + tags) of each precedent in `knowledge_base.json`.
   `knowledge_base.json` now holds four past incidents; with `top_k=2`, only
   the two highest-scoring matches are returned: acceptance criterion 2 is
   satisfied independently of the LLM/stub. `KnowledgeBase` interface shared
   with `AzureAISearchKnowledgeBase`
   (`azure.search.documents.aio.SearchClient`) for `KB_MODE=azure_search`.

9. **`Incident.severite` is validated with regex `^SEV-[1-5]$`** (not a
   `Literal` fixed to "SEV-1"): keeps the contract reusable for other
   incidents while still validating the format expected by acceptance
   criterion 1.

10. **No hardcoded secrets**: `Settings` (pydantic-settings) only reads
    `.env` / environment variables; `.env` stays out of git, only
    `.env.example` is versioned.

11. **Remediation stays strictly a displayed plan.** `RemediationPlan`
    is a data object; no executor calls any real infrastructure API.
    "Executing" = displaying the plan in the CLI report after human
    approval.

12. **No `from __future__ import annotations` in `executors.py`.**
    `@response_handler` (on `HumanApprovalExecutor.handle_response`)
    introspects the signature via `inspect.signature(...).annotation`
    WITHOUT resolving PEP 563 strings; with the `__future__` import,
    `WorkflowContext[SharedContext, SharedContext]` becomes a string and
    `_validate_response_handler_signature` fails (`ValueError: ... must be
    annotated as WorkflowContext...`). All types used are imported at the
    top of the file, so removing the future import is safe under Python
    3.11+.

13. **`ctx.yield_output(context)` passes a direct reference (not a copy)
    to the mutable `SharedContext`.** After a complete `run()`, every
    `type="output"` event in the result therefore shares the SAME final
    object: reassigned fields (e.g. `root_cause`, `log_analysis`) only
    reflect the last value if inspected after the fact, whereas fields
    accumulated via `.append()`/`.extend()` (`root_cause_history`,
    `evidence_log`) keep the full history. Orchestration tests therefore
    read `root_cause_history` to distinguish the two `RootCause` passes.
    In streaming mode (`stream=True`), each `event.data` remains a
    relevant snapshot at the moment it was emitted.

14. **`HumanApprovalExecutor` keeps the full `SharedContext` on
    `self._context`** (instance attribute) between `handle()` (which emits
    `request_info`) and `@response_handler handle_response()` (which
    receives the response). `RemediationApprovalRequest` only carries a
    subset (incident, root_cause, kb_matches) because that's the subset
    that needs to be shown to the human / serialized in the `request_info`
    event; the full context, on the other hand, needs to continue its path
    through the graph via `ctx.send_message`. This pattern works because
    the `Workflow` and its executors persist between the two
    `workflow.run()` calls (the first run that pauses, then
    `run(responses={...})`).

15. **Human rejection = `ctx.yield_output(context)` instead of
    `ctx.send_message(context)`** in `handle_response`. No edge leaves
    `human_approval` toward an alternative terminal node: it's the ABSENCE
    of `send_message` that stops the graph (no more executor to invoke),
    while `yield_output` produces the only observable output
    (`approved=False`, `remediation_plan=None`, `report=None`). Complies
    with SPEC.md/CLAUDE.md: no plan is generated or displayed without
    approval.

16. **`needs_more_evidence` is a closure that captures `settings`**
    (rather than a pure function `(context, settings)`), because
    `Case(condition: Callable[[Any], bool], target=...)` only accepts a
    single argument (the `SharedContext` carried on the edge).
    `CONFIDENCE_THRESHOLD` / `MAX_REFLECTION_LOOPS` are not part of the
    data contract; they're injected through the closure scope of
    `build_workflow(settings)`, which is also the natural place where
    `light_client`/`strong_client` and the shared agents
    (`log_analyzer_agent`, `kb_search_agent`, reused by
    `GatherEvidenceExecutor`) are built.

17. **Persistence via a `PersistenceStore` `Protocol`** (src/tools/persistence.py),
    on the same model as `KnowledgeBase` (DECISIONS.md #8):
    `LocalPersistenceStore` (JSON files under `output/runs/`, default/
    offline mode) and `CosmosPersistenceStore`
    (`azure.cosmos.aio.CosmosClient`, partition key `/id`).
    `get_persistence_store(settings)` picks based on
    `settings.cosmos_endpoint`. The Cosmos container is assumed already
    provisioned by Bicep (azd): the application code only does data-plane
    operations (`upsert_item`/`read_item`/`query_items`), never database/
    container creation, and uses `AzureCliCredential`/
    `DefaultAzureCredential` depending on `AZURE_AUTH_MODE` (async variants,
    consistent with `src/agents/clients.py`).

18. **Two-phase SSE FastAPI API** (`src/api/runs.py`) instead of a
    websocket or `agent_framework_devui`/`ag_ui` (generic, not suited to
    the domain UI): `POST /api/runs` creates a `Workflow`
    (`build_workflow`), keeps it in `app.state.runs` (in-memory registry
    `{run_id: RunState}`) and streams one `step` event per agent output
    (including the `RootCause <-> GatherEvidence` loop) until
    `request_info` (`approval_required`). `POST /api/runs/{id}/approval`
    resumes the SAME `Workflow` object via
    `workflow.run(responses={request_id: bool})`: keeping the instance is
    necessary because `HumanApprovalExecutor` carries state on
    `self._context` between the two calls (DECISIONS.md
    #14). Rejection (DECISIONS.md #15) only produces a `human_approval`
    `step` then `done`; approval produces `remediation` + `summary` then
    persists the final `SharedContext` via `PersistenceStore` before
    `done`. Since `EventSource` doesn't support POST, the stream is
    consumed client-side via `fetch` + `ReadableStream`
    (`frontend/src/api.ts`).

19. **Minimal React + Vite frontend scaffolding** (`frontend/`): in dev,
    `vite.config.ts` proxies `/api` to `127.0.0.1:8000` (no CORS to
    manage); in production, `frontend/dist/` is served by FastAPI via
    `StaticFiles` mounted at `/` (`src/api/app.py`). `frontend/src/types.ts`
    mirrors 1:1 the contracts from `src/models.py` + the responses from
    `src/api/*.py` (a single set of contracts on the backend side, this
    file reflects the JSON shape — kept up to date by hand, no schema
    generation to keep the demo simple). `TopologyGraph` animated the
    8-node graph from `src/orchestrator/graph.py` (this component was
    later superseded by `PipelineHUD` + `ActivityFeed`, see
    `frontend/src/components/PipelineHUD.tsx` / `ActivityFeed.tsx` — no
    later decision entry records the rename); as `HumanApprovalExecutor`
    only emits a `step` on rejection (DECISIONS.md #15), passage through
    the HITL gate on approval is inferred (node + edges `root_cause ->
    human_approval -> remediation` marked visited/traversed) from the
    presence of a `remediation` step in the stream, rather than from an
    explicit consecutive transition.

20. **`Dockerfile` rebuilt to serve the API + the UI (in addition to the
    CLI)**: `ENTRYPOINT` changes from `python -m src.main` to
    `uvicorn src.api.app:app --host 0.0.0.0 --port 8000`
    (`src/api/app.py`, DECISIONS.md #18, mounts `frontend/dist/` via
    `StaticFiles` if present). Stage 1 (`node:20-slim`, alias
    `frontend-build`) runs `npm ci` + `npm run build` on `frontend/` and
    produces `frontend/dist/`; stage 2 (`python:3.11-slim`) installs the
    package (`pip install -e .`, keeps `src.config.REPO_ROOT` aligned with
    `/app` for the default `data/*.json|log` and `frontend/dist/` paths)
    then copies `frontend/dist/` from stage 1. `.dockerignore` now
    excludes `frontend/node_modules/`, `frontend/dist/`,
    `frontend/*.tsbuildinfo` (the host tree is never embedded, only
    stage 1's reproducible build is) as well as `infra/`, `.azure/`,
    `azure.yaml` (azd/Bicep artifacts unrelated to the application image).
    `EXPOSE 8000` (Container Apps ingress port) and
    `ENV AZURE_AUTH_MODE=managed_identity` remain unchanged.

21. **Azure provisioning via Bicep + Azure Developer CLI (azd)**:
    `azure.yaml` declares a single `api` service (`language: docker`,
    `host: containerapp`, `docker.path: ./Dockerfile`); `infra/main.bicep`
    (`subscription` scope) creates the resource group then delegates to
    `infra/resources.bicep` (resource-group scope, parameterized via
    `infra/main.parameters.json` -> `${AZURE_ENV_NAME}` / `${AZURE_LOCATION}`
    / `${AZURE_PRINCIPAL_ID}`). Complies with CLAUDE.md "Technical stack"/
    "Target hosting": `resources.bicep` provisions Log Analytics +
    Application Insights, a user-assigned managed identity (attached to
    the Container App), a Container Registry (+ `AcrPull` role), an Azure
    OpenAI account with two deployments (`gpt-4o` and `gpt-4o-mini`,
    `GlobalStandard` sku, versions `2024-08-06` / `2024-07-18` verified via
    Microsoft Learn), Azure AI Search (`basic` sku, for RAG), serverless
    Cosmos DB (`incidents` database / `records` container, partition key
    `/id`, aligned with `src/tools/persistence.py`), a Container Apps
    Environment, and the Container App (`tags: {'azd-service-name':
    'api'}`, external ingress on port 8000, placeholder image
    `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest` replaced
    by `azd deploy`). Two Bicep files (rather than per-service
    modularization) to stay readable for a demo; both compile without
    errors via the standalone Bicep CLI (`bicep build`, v0.44.1).

22. **No plaintext secrets on deployed resources**: `disableLocalAuth:
    true` on the Azure OpenAI account and on the Cosmos DB account
    disables API/master keys — all data-plane authentication goes through
    Microsoft Entra ID role assignments (`Cognitive Services OpenAI User`,
    `Search Index Data Reader`, the built-in Cosmos DB role "Built-in Data
    Contributor" `00000000-0000-0000-0000-000000000002` referenced
    directly by GUID without a custom `sqlRoleDefinitions`, and
    `AcrPull`), all granted to the Container App's managed identity
    `principalId`/`clientId`. It also receives
    `AZURE_AUTH_MODE=managed_identity` and
    `AZURE_CLIENT_ID=<identity.clientId>` (needed so
    `DefaultAzureCredential` picks this user-assigned identity rather than
    another one). An optional `principalId` parameter (filled in by azd
    via `AZURE_PRINCIPAL_ID`, empty by default) grants the same
    data-plane roles to the developer's account, to point
    `AZURE_AUTH_MODE=cli` (`az login`) at the real deployed resources —
    the `AZURE_OPENAI_ENDPOINT` / `AZURE_AI_SEARCH_ENDPOINT` /
    `COSMOS_ENDPOINT` / ... outputs from `main.bicep` map 1:1 to
    `Settings` aliases (`src/config.py`) and can be fetched via
    `azd env get-values` to fill in a local `.env`.
    `openAiChatDeploymentLight` carries an explicit `dependsOn` on
    `openAiChatDeployment`: Azure OpenAI rejects concurrent deployment
    operations on the same account, so without this dependency ARM may
    parallelize the two and one of them fails. The Container App keeps
    `scale: {minReplicas: 1, maxReplicas: 1}`: `app.state.runs`
    (src/api/runs.py, DECISIONS.md #18) is a per-process in-memory
    registry, so multiple replicas would break HITL resumption. `KB_MODE`
    is deliberately NOT set on the Container App (stays `"local"`,
    `Settings`'s default value): Azure AI Search is provisioned (RAG,
    CLAUDE.md) and `AZURE_AI_SEARCH_ENDPOINT`/`_INDEX` are injected with
    the `Search Index Data Reader` role, but without an indexing pipeline
    for `data/knowledge_base.json`, a `KB_MODE=azure_search` with an empty
    index would break acceptance criterion 2 (DECISIONS.md #8); a user can
    switch manually after indexing.

23. **Detailed documentation in `docs/`, complementing (not replacing)
    `SPEC.md`/`DECISIONS.md`/`scenario-demo-incident-paiement.md`**: four
    files with distinct reading scopes -
    `architecture.md` (components, `src/models.py` contracts, design
    principles/non-negotiable constraints), `how-it-works.md` (internal
    mechanics - `SharedContext` propagation, `build_workflow` topology,
    reflection loop, HITL via `request_info`/`response_handler`, the
    two-phase SSE protocol of `src/api/runs.py`), `deployment.md`
    (configuration reference, Docker, `azd`/Bicep, resource and RBAC role
    table) and `demo-guide.md` (practical CLI/UI walkthrough with the real
    `StubChatClient` values - confidence 0.55 -> 0.92 -, human-rejection /
    real-Azure-OpenAI variants). `SPEC.md` remains the reference for JSON
    contracts and acceptance criteria, `DECISIONS.md` the technical-decision
    log, and `scenario-demo-incident-paiement.md` the presentation script
    (talking points, timing): `docs/` links to them rather than duplicating
    them. Linked from `README.md` ("Learn more") via `docs/README.md`
    (index).

24. **`gpt-4o` `2024-08-06` retired from `infra/resources.bicep` -> `2024-11-20`.**
    A real `azd up` failed provisioning `openAiChatDeployment` with
    `ServiceModelDeprecating: The model 'Format:OpenAI,Name:gpt-4o,Version:2024-08-06'
    is in deprecating state and cannot be used for new deployments`. Verified
    via the Microsoft Learn [Model Retirement Schedule](https://learn.microsoft.com/azure/ai-foundry/openai/concepts/model-retirement-schedule):
    `gpt-4o` `2024-05-13` and `2024-08-06` are "Deprecated" (retirement
    2026-10-01, no longer available for new deployments), `2024-11-20` is
    "GA" (retirement 2026-10-01 as well, replacement `gpt-5.1`).
    `gpt-4o-mini` `2024-07-18` stays "GA", unaffected by this error, left
    unchanged. `docs/deployment.md` §8.11 documents this failure mode (and
    the fact that Azure OpenAI model versions get deprecated over time
    independently of the code) as well as the `package-api: building image:
    signal: killed` failure observed in parallel (likely an OOM from the
    Docker build running at the same time as `azd up`'s provisioning).

25. **Microsoft Foundry project (`accounts/projects`) + Agent Framework OTel
    instrumentation toward Application Insights: the `WorkflowBuilder`
    orchestration is traced in Observability > Traces (ai.azure.com).**
    On the infra side (`infra/resources.bicep`), `openAi` moves from
    `Microsoft.CognitiveServices/accounts@2024-10-01` (`kind: 'OpenAI'`) to
    `@2025-06-01` (`kind: 'AIServices'`, `properties.allowProjectManagement:
    true`): a non-destructive GA upgrade documented by
    [Upgrade Azure OpenAI to Microsoft Foundry](https://learn.microsoft.com/azure/foundry/how-to/upgrade-azure-openai)
    (endpoint, keys, role assignments and `gpt-4o`/`gpt-4o-mini` deployments
    unchanged; rollback = revert to `kind: 'OpenAI'`). A new resource
    `foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01'`
    (`proj-${resourceToken}`, schema verified via
    [accounts/projects](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2025-06-01/accounts/projects))
    exposes the Foundry "project"; its `AZURE_FOUNDRY_PROJECT_NAME` /
    `AZURE_FOUNDRY_PROJECT_ID` outputs are propagated by `main.bicep`.

    On the code side, a new `src/observability.py` module
    (`configure_observability(settings)`, called at startup by
    `src.main.run_demo` and `src.api.app.create_app`) wires
    `configure_azure_monitor(connection_string=...)` (package
    `azure-monitor-opentelemetry`, added to `pyproject.toml`) then
    `enable_instrumentation(enable_sensitive_data=...)`, a pattern documented
    at [agent_framework.observability](https://learn.microsoft.com/agent-framework/agents/observability).
    No-op if `APPLICATIONINSIGHTS_CONNECTION_STRING` is absent (offline mode
    / `StubChatClient`, no network dependency added). Once active,
    `workflow.run()` (`src.orchestrator.build_workflow`) emits
    `workflow.run` / `executor.process <id>` spans covering the six agents,
    the `RootCause <-> GatherEvidence` reflection loop, and the
    `HumanApproval` HITL gate. New `Settings.enable_sensitive_data` field
    (alias `ENABLE_SENSITIVE_DATA`, default `false`, documented in
    `.env.example`): optional capture of agent prompts/responses in traces,
    reserved for dev use (potentially sensitive data).

    The Application Insights <-> Foundry project connection (the
    `AppInsights` category of
    `Microsoft.CognitiveServices/accounts/projects/connections`) was NOT
    codified in Bicep: this resource type only exposes `AppInsights` in
    `category` at the unversioned "latest" alias, absent from the verified
    GA versions `2025-06-01`/`2025-09-01` — per CLAUDE.md's "don't guess
    APIs" rule. This connection is documented as a one-time manual step in
    `docs/deployment.md` §8.12 (ai.azure.com portal, Foundry project > Agents
    > Traces > Connect -> select `appi-${resourceToken}`), matching the
    official [Trace agent runs](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-agent-setup#connect-application-insights-to-your-foundry-project)
    walkthrough.

26. **`azd up` fails on `foundryProject` (`BadRequest: ... To create
    projects, you must enable a managed identity on your resource`) ->
    `identity: SystemAssigned` added to `openAi`.** A real `azd up` after
    DECISIONS.md #25 failed provisioning
    `aoai-${resourceToken}/proj-${resourceToken}` with
    `BadRequest: Unsupported configuration. To create projects, you must
    enable a managed identity on your resource.` (the generic "A resource
    with this name already exists or is in a conflicting state" message is
    just the standard ARM wrapper for a nested sub-resource failure, not a
    distinct naming conflict). Fix: `identity: { type: 'SystemAssigned' }`
    added to the `openAi` account (`Microsoft.CognitiveServices/accounts`) -
    `accounts/projects` (#25) doesn't require its own identity, only the
    parent account needs one to manage its projects. Non-destructive addition
    (new system identity on an existing resource, no impact on the existing
    endpoint/keys/role assignments). If `azd up` still fails with "already
    exists or is in a conflicting state" after this fix, check in the Azure
    portal whether `proj-${resourceToken}` already exists under
    `aoai-${resourceToken}` (the "Projects" tab) in a `Failed` state and
    delete it before retrying (a plain `azd up`/`azd provision` retry is
    normally enough, since ARM PUT is idempotent).

27. **`azd up` still fails on `foundryProject` after #26 (same
    `BadRequest: ... must enable a managed identity on your resource`, on a
    fresh environment) -> `identity: SystemAssigned` also added on the
    PROJECT, not just on the account.** On a fresh environment,
    `aoai-${resourceToken}` is created successfully in ~17s (identity
    included, #26), but `aoai-${resourceToken}/proj-${resourceToken}` fails
    805ms later with the same `BadRequest: Unsupported configuration. To
    create projects, you must enable a managed identity on your resource.` -
    which invalidates #26's assumption that "`accounts/projects` doesn't
    require its own identity, only the parent account needs one".
    Confirmed via the Microsoft reference module
    [`avm/ptn/ai-ml/ai-foundry`](https://github.com/Azure/bicep-registry-modules/blob/main/avm/ptn/ai-ml/ai-foundry/modules/project/main.bicep):
    the `Microsoft.CognitiveServices/accounts/projects` resource there
    itself declares `identity: { type: 'SystemAssigned' }`, in addition to
    `managedIdentities: { systemAssigned: true }` on the parent account
    (module `avm/res/cognitive-services/account`). Fix: `identity: { type:
    'SystemAssigned' }` added to `foundryProject` (in addition to the one on
    `openAi`, #26) - a valid `Identity` type for
    `accounts/projects@2025-06-01` (`'None' | 'SystemAssigned' |
    'SystemAssigned, UserAssigned' | 'UserAssigned'`, schema already verified
    in #25). Non-destructive addition (new system identity on a child
    resource, no impact on the `AZURE_FOUNDRY_PROJECT_NAME`/
    `AZURE_FOUNDRY_PROJECT_ID` outputs or on the existing role assignments,
    which only reference the Container App's identity).

28. **`azd provision` then fails on the `openAi` account
    (`aoai-${resourceToken}`, very quickly) with `BadRequest:
    PublicNetworkAccess is required for this resouce` [sic] ->
    `publicNetworkAccess: 'Enabled'` explicitly added to `openAi`'s
    `properties`.** After #27, a retry on the Failure #3 environment failed
    in 1.665s on the account itself (which had nonetheless succeeded in 17s
    on the previous attempt) with this `BadRequest` (still under the same
    generic "already exists or in a conflicting state" wrapper). With
    `allowProjectManagement: true` (#25) and an `accounts/projects`
    sub-project with its own identity (#27), Azure now requires the parent
    account's `properties.publicNetworkAccess` to be explicitly set - it can
    no longer stay implicit/omitted. Confirmation: the reference module
    [`avm/res/cognitive-services/account`](https://github.com/Azure/bicep-registry-modules/blob/main/avm/res/cognitive-services/account/main.bicep)
    (used by `avm/ptn/ai-ml/ai-foundry`, #27) NEVER leaves this property
    implicit:
    `publicNetworkAccess: publicNetworkAccess != null ? publicNetworkAccess
    : (!empty(networkAcls) ? 'Enabled' : 'Disabled')`. Fix:
    `publicNetworkAccess: 'Enabled'` added to `openAi`'s `properties`
    (`Microsoft.CognitiveServices/accounts`, enum `'Disabled' | 'Enabled'`
    valid for `@2025-06-01`). `'Enabled'` because this bicep provisions no
    VNet/private endpoint: the Container App and the dev identity
    (`principalId`) access `aoai-${resourceToken}` via its public endpoint,
    as was implicitly the case before this change (the account had
    succeeded without this property during Failure #3). Non-destructive
    addition, doesn't restrict any existing access.

29. **Make the six agents visible in the Microsoft Foundry project's UI ->
    `scripts/register_foundry_agents.py` script using
    `ExternalAgentDefinition`, not `PromptAgentDefinition`.** This demo's
    agents run outside Foundry, directly against Azure OpenAI via the
    Microsoft Agent Framework (`AzureOpenAIStructuredChatClient`,
    `src/agents/clients.py`) - there's no "native Foundry" orchestration in
    its place. `PromptAgentDefinition` assumes Foundry hosts and runs the
    agent (prompt + model managed Foundry-side): unsuited here, and would
    have introduced a second source of truth for each agent's
    instructions/model. `ExternalAgentDefinition` (`azure-ai-projects`,
    `discriminator="external"`) matches the case exactly: "Represents a
    third-party agent hosted outside Foundry (...) Registration is
    metadata-only" - confirmed by introspecting the installed SDK
    (`inspect.getsource`), per the "don't guess APIs" rule. No compute
    resource is created; only the entry appears in the project's Agents
    tab.

    A precondition fixed along the way: `AgentTelemetryLayer` (package
    `agent_framework`, OTel instrumentation) sources the `gen_ai.agent.id`
    span attribute from `Agent.id`, not `Agent.name` - confirmed by reading
    the installed source. Without an explicit `id`,
    `BaseChatClient.as_agent(...)` generates a random `uuid4()` on every
    process restart, which would then never match the static `id` registered
    in Foundry (the agent's name, e.g. `RootCause`) - the traces (#25,
    docs/deployment.md §8.12) would never have attached to the External
    Agent registration. Fix: `id=agent_name` added to the `as_agent(...)`
    call in `AzureOpenAIStructuredChatClient.get_structured_response`
    (`src/agents/clients.py`) - same value as the `agent_name` already used
    as `name=`, so no visible behavior change elsewhere.

    Registration (`AIProjectClient(..., allow_preview=True)`,
    `agents.create_version(agent_name=..., definition=ExternalAgentDefinition())`)
    is a **preview** feature of `azure-ai-projects` >=2.2.0 - documented as
    such (docs/deployment.md §8.13), since the API may change before GA.
    Dependency added in a separate optional group `[foundry]`
    (`pyproject.toml`), apart from `[dev]`: unrelated to running or testing
    the demo itself, only to this one-off registration script.

    The project endpoint (`AZURE_FOUNDRY_PROJECT_ENDPOINT`, new) is built by
    string concatenation in `infra/resources.bicep`
    (`'https://${openAi.name}.services.ai.azure.com/api/projects/${foundryProject.name}'`,
    a form documented by `AIProjectClient`) rather than read from a resource
    property: confirmed via Microsoft Learn docs that
    `Microsoft.CognitiveServices/accounts/projects`
    (`ProjectProperties`) only exposes `description`/`displayName`, no
    endpoint property. `openAi.name` == `properties.customSubDomainName`
    (both already fixed on the existing `aoai-${resourceToken}` resource,
    #21): no manual lookup needed, fetched like the other Bicep outputs via
    `azd env get-values >> .env` (already the documented local-dev flow,
    §8.7).

    No separate registration for the "workflow" (`WorkflowBuilder`, the
    reflection loop, the HITL gate): Foundry has no "workflow" resource to
    register independently of the agents that make it up, and the full
    execution timeline (executors, loop, HITL) is already entirely visible
    via the existing OTel traces (#25, docs/deployment.md §8.12) once
    Application Insights is connected - no gap to fill here.

30. **Fix to #29: Foundry does have a registerable "workflow" resource
    (`WorkflowAgentDefinition`) -> `scripts/register_foundry_workflow.py`
    script + hand-written CSDL `scripts/foundry_workflow.yaml`.** The last
    paragraph of #29 claimed that no distinct "workflow" resource existed on
    the Foundry side; re-reading the official "Declarative Workflows" docs
    (Microsoft Agent Framework) and introspecting the installed SDK
    (`azure-ai-projects==2.2.0`, `_models.py`) show the opposite:
    `WorkflowAgentDefinition` does exist (`discriminator="workflow"`, field
    `workflow: str` = "The CSDL YAML definition of the workflow"),
    registerable via the same `agents.create_version(agent_name=...,
    definition=...)` as the six agents. #29 is kept as-is (historical
    record) rather than corrected in place.

    No exporter exists to generate this CSDL from the Python
    `WorkflowBuilder` (neither in `agent-framework` nor on the Foundry side):
    the YAML is therefore hand-written, mirroring the actual topology of
    `src/orchestrator/graph.py` (the six-agent sequence, the
    `RootCause <-> GatherEvidence` loop bounded by
    `loopCount`/`maxReflectionLoops`, the `Question`/`approved` HITL gate) -
    threshold/loop values are hardcoded (`confidenceThreshold: 0.75`,
    `maxReflectionLoops: 2`) because this standalone Foundry-side workflow
    has no access to `src/config.py`/`.env`. Pydantic fields (`confiance`,
    `preuves_manquantes`, `texte`, etc.) are taken verbatim from
    `src/models.py` into the YAML's Power Fx expressions. The CSDL schema
    (action kinds, loops via `GotoAction`+`If`, the HITL gate via
    `Question`) was confirmed by reading the official docs rather than
    guessed, per the "don't guess APIs" rule - see the header of
    `foundry_workflow.yaml` for details on the choices made (trigger-based
    CSDL shape, `Local.*` namespace, Power Fx functions used).

    `Foundry-Features: WorkflowAgents=V1Preview` header (preview feature):
    confirmed by reading the installed source
    (`azure/ai/projects/operations/_patch_agents.py`) that the SDK adds it
    automatically in `create_version` when
    `AIProjectClient(..., allow_preview=True)` is used - the same
    `allow_preview=True` flag already in place for #29, no extra code
    needed.

    An accepted limitation, documented in `foundry_workflow.yaml`'s header
    and docs/deployment.md §8.14: this CSDL doesn't actually execute (the
    six `InvokeAzureAgent` actions reference `ExternalAgentDefinition`
    entries - metadata-only, with no model/instructions on the Foundry side,
    cf. #29), so clicking "Run Workflow" in the portal will likely fail on
    the very first agent invocation. Its value is displaying the topology
    (nodes/edges/conditions) in the visual canvas, not execution; the actual
    execution remains 100% `src/orchestrator/graph.py` + `executors.py`,
    observable via the OTel traces (#25, docs/deployment.md §8.12). Must be
    resynced by hand if `graph.py` changes.

    Addendum (first real run of the script against a Foundry project): the
    `SetMultipleVariables` action (used to initialize the loop state) does
    follow the documented shape exactly (`variables:` = a path->value map,
    the only required property), yet the (preview) Foundry API rejects it
    at registration anyway with `invalid_payload: Missing required
    properties for element ... (SetMultipleVariables)`. The official docs
    are therefore not 100% reliable for this preview feature. Fix: replaced
    with three separate `SetVariable` actions (one per variable), the
    simplest shape, already proven to work elsewhere in the same file,
    rather than guessing another shape for `SetMultipleVariables`. This
    implies some residual risk remains on the other action kinds used here
    (`If`, `GotoAction`, `Question`, `InvokeAzureAgent`, `SendActivity`,
    `EndWorkflow`): their shape follows the docs and hasn't (yet) triggered
    a registration error, but only a real call against a Foundry project is
    authoritative for a preview feature - to be fixed case by case if a new
    `invalid_payload` error appears.

    Addendum 2 (second real run, after fixing addendum 1): the announced
    risk was confirmed - the `Question` action (`human_approval_gate`, the
    HITL gate itself) is in turn rejected with `invalid_payload: Missing
    required properties for element: human_approval_gate (Question)`, even
    though its shape (`question.text` / `variable` / `default`) already
    matched the official "Declarative Workflows" docs' property table
    exactly. The Microsoft Learn docs (tutorial page) are therefore not
    reliable for this action kind either. A more reliable source was found:
    the real, executable examples from the `microsoft/agent-framework`
    repository itself
    (`dotnet/samples/03-workflows/Declarative/ConfirmInput/ConfirmInput.yaml`),
    under the same `kind: Workflow` / `trigger: OnConversationStart`
    envelope as this file, show a structurally different shape for
    `Question`: `property` (not `variable`) for the output variable,
    `prompt.kind: Message` + `prompt.text` (a list, not a scalar
    `question.text`) for the message, and `entity` (required, absent from
    the tutorial docs) to type the expected answer. Fix: shape aligned with
    this confirmed example, using `entity.kind: StringPrebuiltEntity` rather
    than a boolean variant (`BooleanPrebuiltEntity` or other) that couldn't
    be confirmed in any source - a choice that also preserves the
    `=Local.approved = "yes"` (string) comparison already used downstream by
    `check_approval`, without making it depend on an unverified boolean
    type. `displayName` is kept despite its absence from the official
    examples: already confirmed accepted by the live API for the other
    action kinds in this file (`SetVariable`, `If`, `InvokeAzureAgent`,
    `SendActivity`, `GotoAction`).

    General lesson: for this preview feature, the prose docs (Agent
    Framework tutorial) can diverge from what the Foundry API actually
    validates, but the executable YAML samples from the
    `microsoft/agent-framework` repository (the
    `dotnet/samples/*/Declarative/` folder) have proven a more reliable
    source so far. Residual risk is now limited to the actions located
    after `human_approval_gate` that haven't yet been exercised by a real
    registration attempt: the `InvokeAzureAgent` (Remediation, Summary) and
    `SendActivity` actions nested inside `check_approval`, and
    `EndWorkflow` - to be fixed case by case if a new `invalid_payload`
    error appears.
