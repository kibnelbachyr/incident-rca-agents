# Fonctionnement interne

> Comment le graphe d'orchestration s'exécute réellement : propagation du
> `SharedContext`, topologie, boucle de réflexion, human-in-the-loop (HITL) et
> flux SSE. À lire avec `src/orchestrator/graph.py` et
> `src/orchestrator/executors.py` ouverts. Pour la liste des composants, voir
> [`architecture.md`](architecture.md).

## 1. `SharedContext` : la colonne vertébrale

Tout l'état de l'exécution vit dans **un seul objet pydantic**,
`SharedContext` (`src/models.py`), qui circule entre les exécuteurs via
`ctx.send_message(context)`. Les agents n'ont pas d'état et ne se voient
jamais entre eux : chaque exécuteur lit ce qu'il lui faut dans `context`,
appelle son agent, **mute `context` en place**, puis le relaie.

### Réassignation vs accumulation

- **Champs « ponctuels »** (`log_analysis`, `incident`, `kb_matches`,
  `root_cause`, `remediation_plan`, `report`, `approved`) sont **réassignés**
  à chaque passage : ils ne reflètent que la dernière valeur écrite.
- **Champs « cumulatifs »** (`root_cause_history`, `evidence_log`) sont
  **étendus** (`.append`/`.extend`) : ils conservent tout l'historique,
  notamment les deux passages de `RootCause` en cas de boucle de réflexion.
  `loop_count` est un compteur incrémenté par `GatherEvidenceExecutor`.

### `yield_output` vs `send_message`

Chaque exécuteur (sauf cas particuliers détaillés en §4) appelle :

```python
await ctx.yield_output(context)   # observabilité : un événement "output" par étape
await ctx.send_message(context)   # avance dans le graphe vers le(s) successeur(s)
```

`yield_output` transmet **une référence directe** au `SharedContext`
mutable, pas une copie. Conséquence : à la fin d'un `run()` complet (non
streamé), tous les événements `type="output"` du résultat partagent le
**même objet final** — un champ réassigné (ex. `root_cause`) ne montre que sa
dernière valeur si on l'inspecte après coup, alors que les champs
accumulés (`root_cause_history`, `evidence_log`) gardent tout l'historique.
C'est pourquoi les tests d'orchestration lisent `root_cause_history` pour
distinguer le 1er et le 2e passage de `RootCause`. **En streaming
(`stream=True`)**, en revanche, chaque `event.data` reçu au fil de l'eau est
un instantané pertinent au moment de son émission — c'est ce que consomment
le CLI et l'API SSE.

## 2. Topologie du graphe (`build_workflow`, `src/orchestrator/graph.py`)

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

`output_from="all"` : **chaque** exécuteur émet un événement `output` (pas
seulement le dernier), ce qui permet d'observer la sortie de chaque agent en
streaming — y compris les deux passages de `RootCause`/`GatherEvidence`.

### Construction (`build_workflow(settings)`)

1. **Clients de chat** : `light_client = get_chat_client(settings,
   light=True)`, `strong_client = get_chat_client(settings, light=False)`
   (§5.2 de `architecture.md`).
2. **Base de connaissances** : `knowledge_base = get_knowledge_base(settings)`.
3. **Agents partagés** : `log_analyzer_agent = LogAnalyzerAgent(light_client)`
   et `kb_search_agent = KBSearchAgent(light_client, knowledge_base)` sont
   instanciés **une seule fois** et injectés à la fois dans
   `LogAnalyzerExecutor`/`KBSearchExecutor` (pipeline principal) et dans
   `GatherEvidenceExecutor` (boucle de réflexion) — pas de duplication
   d'agent, conforme aux « six agents spécialisés » de `SPEC.md` §2.
4. **`needs_more_evidence`** est une **closure** qui capture `settings` :

   ```python
   def needs_more_evidence(context: SharedContext) -> bool:
       return (
           context.root_cause.confiance < settings.confidence_threshold
           and context.loop_count < settings.max_reflection_loops
       )
   ```

   `Case(condition: Callable[[Any], bool], target=...)` n'accepte qu'un seul
   argument (le `SharedContext` acheminé sur l'arête) : `CONFIDENCE_THRESHOLD`
   et `MAX_REFLECTION_LOOPS` ne font donc pas partie d'un contrat de données,
   ils sont injectés via la portée de `build_workflow`.

## 3. La boucle de réflexion

C'est le **moment fort n°1** de la démo (`scenario-demo-incident-paiement.md`
§4) : l'orchestrateur refuse de conclure sur un score de confiance
insuffisant et va chercher des preuves ciblées avant de retenter.

### Déclenchement

Après `RootCauseExecutor`, l'arête conditionnelle évalue
`needs_more_evidence(context)` :

- **Vrai** (`confiance < CONFIDENCE_THRESHOLD` **ET** `loop_count <
  MAX_REFLECTION_LOOPS`) → routage vers `GatherEvidenceExecutor`.
- **Faux** (confiance suffisante, ou budget de boucle épuisé) → routage vers
  `HumanApprovalExecutor` (`Default`).

### `GatherEvidenceExecutor`

1. Incrémente `context.loop_count`.
2. Reconstruit un prompt `LogAnalyzer` **ciblé** :
   `build_log_prompt(context.raw_logs, focus=context.root_cause.preuves_manquantes)`
   — les `preuves_manquantes` du dernier `RootCauseHypothesis` deviennent les
   points à investiguer en priorité.
3. Étend `context.evidence_log` avec les nouveaux
   `log_analysis.correlated_events`.
4. Relance `KBSearchAgent.run(context.incident)` pour reconfronter les
   précédents à la lumière des nouvelles preuves.
5. `ctx.yield_output(context)` puis `ctx.send_message(context)` →
   **retour vers `RootCauseExecutor`** (`add_edge(gather_evidence,
   root_cause)`), qui reçoit cette fois `evidence_log` non vide
   (`build_prompt(..., evidence_log=context.evidence_log)`).

### Garantie de terminaison

La boucle est **bornée par construction** : `needs_more_evidence` est
**impossible à satisfaire indéfiniment**, car `loop_count` est strictement
croissant et plafonné par `MAX_REFLECTION_LOOPS` (défaut **2**). Même si la
confiance reste basse après le nombre maximal de tours, le `Default` route
vers `HumanApprovalExecutor` — l'orchestrateur avance toujours, jamais de
boucle infinie (critère d'acceptation 8 de `SPEC.md`).

### Déroulé avec les données de démo (`StubChatClient`)

| Tour | `loop_count` | `RootCause.confiance` | Décision |
|------|---------------|------------------------|----------|
| 1 | 0 | **0.55** (deux hypothèses concurrentes : pool DB vs latence Stripe) | `0.55 < 0.75` et `0 < 2` → **reboucle** vers `GatherEvidence` |
| 2 (après `GatherEvidence`, `loop_count=1`) | 1 | **0.88** (cause = `max_pool_size` 40→20, Stripe écarté) | `0.88 ≥ 0.75` → **continue** vers `HumanApproval` |

## 4. Human-in-the-loop (HITL)

C'est le **moment fort n°2** : sur un système de paiement, aucune
remédiation n'est proposée sans validation humaine explicite.

### Mécanisme : `ctx.request_info()` + `@response_handler`

`HumanApprovalExecutor` est une porte **pure** (n'enveloppe aucun agent) qui
porte un état d'instance entre deux invocations :

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
            await ctx.yield_output(context)    # arrêt : pas de send_message
```

- `handle()` émet un `RequestInfoEvent` (`event.type == "request_info"`,
  `event.request_id`) contenant un `RemediationApprovalRequest` — un
  **sous-ensemble** du contexte (incident, cause racine, précédents) destiné
  à être présenté à l'humain.
- Le `Workflow` et ses exécuteurs **persistent en mémoire** entre deux appels
  `workflow.run(...)` : `self._context` (le `SharedContext` **complet**)
  survit donc jusqu'à ce que `workflow.run(stream=True, responses={request_id:
  bool})` soit appelé pour reprendre l'exécution.
- **Approbation** (`response=True`) : `context.approved = True`,
  `ctx.send_message(context)` → le graphe continue vers `RemediationExecutor`
  puis `SummaryExecutor`.
- **Refus** (`response=False`) : `context.approved = False`,
  **uniquement** `ctx.yield_output(context)` — aucune arête ne part de
  `human_approval` vers un nœud terminal alternatif, c'est l'**absence** de
  `send_message` qui arrête le graphe (plus aucun exécuteur à invoquer). La
  seule sortie observable porte `approved=False`, `remediation_plan=None`,
  `report=None` : conforme à `CLAUDE.md` (« aucune remédiation sans
  validation »).

> ⚠️ Pourquoi `RemediationApprovalRequest` ne porte-t-il qu'un sous-ensemble
> du contexte ? Parce que c'est ce sous-ensemble qui doit être **sérialisé**
> dans l'événement `request_info` et présenté à l'humain (CLI ou
> `ApprovalCard` côté UI). Le contexte complet, lui, n'a pas besoin de
> traverser la frontière HITL : il reste sur `self._context` et reprend son
> chemin via `ctx.send_message` une fois la décision connue.

## 5. Flux d'exécution de bout en bout

### 5.1 CLI (`src/main.py`)

```python
result = workflow.run(SharedContext(raw_logs=raw_logs), stream=True)
async for event in result:
    if event.type == "output":
        _print_step_output(event.executor_id, event.data, settings)
    elif event.type == "request_info":
        approved = _ask_approval(event.data)   # input() bloquant
        break
await result.get_final_response()

if approved is not None:
    result = workflow.run(stream=True, responses={event.request_id: approved})
    async for event in result:
        if event.type == "output":
            _print_step_output(event.executor_id, event.data, settings)
    await result.get_final_response()
```

- **Phase 1** : streame `log_analyzer → incident_extractor → kb_search →
  root_cause → (gather_evidence → root_cause)* → human_approval`, jusqu'au
  `RequestInfoEvent`. `_print_step_output` formate chaque type de sortie
  (timeline, incident, précédents KB, cause racine + verdict de boucle,
  collecte de preuves).
- `_ask_approval` affiche incident / cause retenue / confiance / précédents
  et demande `input("Approuver le passage a la remediation ? [o/N] : ")`.
  `EOFError` (entrée non interactive) → refus.
- **Phase 2** (si approuvé) : reprend le **même** `workflow` avec
  `responses={request_id: True}` → streame `remediation → summary`.
- Si refusé : le workflow s'arrête après la phase 1, rien n'est affiché de
  plus (pas de plan, pas de rapport).

### 5.2 Web UI (FastAPI SSE + React)

Le **même** `build_workflow(settings)` est exposé en deux endpoints SSE
(`src/api/runs.py`), avec un registre en mémoire `app.state.runs: dict[str,
RunState]` qui garde le `Workflow` vivant entre les deux appels HTTP (requis
car `HumanApprovalExecutor` porte l'état sur `self._context`, §4).

**`POST /api/runs`** — phase 1 :

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

**`POST /api/runs/{run_id}/approval`** — phase 2 (`body: {"approved": bool}`) :

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

### Événements SSE

| Événement | Payload | Émis par |
|-----------|---------|----------|
| `run_started` | `{"run_id": str}` | `POST /api/runs`, immédiatement |
| `step` | `{"executor_id": str, "context": SharedContext}` | à chaque `event.type == "output"`, dans les deux phases |
| `approval_required` | `{"request": RemediationApprovalRequest}` | `POST /api/runs`, sur `event.type == "request_info"` |
| `done` | `{"approved": bool \| null}` | fin de l'une ou l'autre phase |
| `error` | `{"message": str}` | toute exception (le `run_id` est alors retiré du registre) |

### 5.3 Côté frontend (`frontend/src/`)

- `api.ts` : `EventSource` ne supporte pas POST, donc `startRun`/
  `submitApproval` parsent eux-mêmes le flux `text/event-stream` via `fetch`
  + `ReadableStream`, en découpant sur `\n\n` et dispatchant selon la ligne
  `event: ...`.
- `App.tsx` : machine à états `phase` (`idle → running → awaiting_approval →
  running → done`/`error`) ; chaque `step` est poussé dans `steps` (rendu par
  `StepCard`), `approval_required` affiche `ApprovalCard`.
- `TopologyGraph.tsx` anime le graphe à 8 nœuds en fonction des
  `executor_id` déjà vus dans `steps`. Comme `HumanApprovalExecutor` n'émet
  un `step` qu'**en cas de refus** (§4), le passage par la porte HITL en cas
  d'**approbation** est déduit de la présence d'un `step` `remediation` dans
  le flux (le nœud et les arêtes `root_cause -> human_approval ->
  remediation` sont alors marqués comme traversés).
- `History.tsx` consulte `/api/history` (`IncidentRecordSummary[]`) et
  `/api/history/{run_id}` (`IncidentRecord` complet, incl. `SharedContext`
  final) pour revoir une exécution passée — y compris une exécution refusée
  (`context.approved === false`, pas de `remediation_plan`/`report`).

## 6. Observabilité

- **Streaming** : chaque sortie d'agent est émise au fil de l'eau
  (`output_from="all"`), y compris la boucle `RootCause ↔ GatherEvidence`
  (critère d'acceptation 7 de `SPEC.md`).
- **Application Insights** : `APPLICATIONINSIGHTS_CONNECTION_STRING` est
  provisionné par `infra/` et injecté dans le Container App, mais
  l'application **ne l'exploite pas encore** (pas d'exporteur OpenTelemetry
  câblé côté code) — c'est une piste d'évolution listée dans le `README.md`
  racine.
