# Architecture & conception

> Vue d'ensemble de tous les composants et des principes de conception. Pour
> les contrats JSON détaillés et les critères d'acceptation, voir `SPEC.md`.
> Pour le détail des choix techniques et leur justification, voir
> `DECISIONS.md`. Pour le fonctionnement interne (boucle de réflexion, HITL,
> flux SSE), voir [`how-it-works.md`](how-it-works.md).

## 1. Vue d'ensemble

Le projet est une démo d'un **système multi-agents orchestré** (Microsoft
Agent Framework) qui diagnostique un incident sur un système de paiement :

```
logs bruts → incident structuré → précédents (RAG) → cause racine
           → [boucle de réflexion si confiance insuffisante]
           → validation humaine → plan de remédiation → rapport final
```

Deux points d'entrée partagent le **même orchestrateur**
(`src/orchestrator/graph.py`) :

- **CLI** (`python -m src.main`) — streaming texte dans le terminal,
  approbation via `input()`.
- **API + UI web** (FastAPI + React, `src/api/` + `frontend/`) — le même
  graphe exposé en SSE, graphe d'orchestration animé, approbation via un
  bouton, historique des exécutions persistées.

Le tout est déployable sur Azure via Bicep + Azure Developer CLI (`azd`,
`infra/`).

### Topologie du graphe d'orchestration

```
LogAnalyzer -> IncidentExtractor -> KBSearch -> RootCause --[switch]--+
                      ^                                               |
                      | confiance < seuil ET loop_count < max         | sinon
                      +------------------ GatherEvidence <------------+
                                                                       v
                                                          HumanApproval (HITL)
                                                                       | approuvé
                                                                       v
                                                      Remediation -> Summary
```

Chaque nœud est un `Executor` du framework qui enveloppe soit un agent
(`StructuredAgent`), soit (pour `HumanApproval`) une porte de validation pure.
Les agents sont **sans état** et ne communiquent jamais directement entre
eux : tout passe par l'**orchestrateur** et le **`SharedContext`**
(`src/models.py`), un objet pydantic unique qui circule de nœud en nœud et
accumule les résultats.

## 2. Principes de conception (contraintes non négociables)

Ces contraintes viennent de `CLAUDE.md` et structurent l'ensemble du code :

| # | Contrainte | Où c'est implémenté |
|---|------------|----------------------|
| 1 | Agents spécialisés, sans état, contrat I/O strict (JSON validé pydantic) | `src/agents/*.py` (`response_model`), `src/models.py` |
| 2 | L'orchestrateur détient **tout** l'état partagé, les agents ne se parlent jamais | `SharedContext` (`src/models.py`) propagé par `ctx.send_message` |
| 3 | Boucle de réflexion **bornée** (`MAX_REFLECTION_LOOPS`, défaut 2) | `needs_more_evidence` (`src/orchestrator/graph.py`) |
| 4 | Sous `CONFIDENCE_THRESHOLD` (défaut 0.75), on reboucle au lieu de conclure | idem, basé sur `RootCauseHypothesis.confiance` |
| 5 | **Aucune remédiation sans validation humaine** | `HumanApprovalExecutor` + `ctx.request_info()` (`src/orchestrator/executors.py`) |
| 6 | La remédiation reste un **plan affiché**, jamais exécuté | `RemediationAgent` ne produit qu'un objet `RemediationPlan` ; aucun appel d'infrastructure réelle |
| 7 | Aucun secret en clair (`.env` / variables d'env / Managed Identity / Key Vault) | `src/config.py` (`Settings`, pydantic-settings) ; `infra/` (`disableLocalAuth: true` + RBAC) |

## 3. Composants — vue d'ensemble

| Composant | Chemin | Rôle |
|-----------|--------|------|
| Agents (6) | `src/agents/` | Un module par agent : instructions (prompt système), contrat pydantic de sortie, fonction `build_prompt`. |
| Base agent | `src/agents/base.py` | Classe générique `StructuredAgent[ResponseT]`. |
| Clients de chat | `src/agents/clients.py` | `StubChatClient` (hors-ligne, déterministe) et `AzureOpenAIStructuredChatClient` (réel), choisis par `get_chat_client`. |
| Contrats de données | `src/models.py` | Tous les modèles pydantic, dont `SharedContext` (état central). |
| Orchestrateur — graphe | `src/orchestrator/graph.py` | `build_workflow(settings)` : assemble le `Workflow` (`WorkflowBuilder`). |
| Orchestrateur — exécuteurs | `src/orchestrator/executors.py` | Un `Executor` par nœud du graphe (8 au total). |
| Base de connaissances (RAG) | `src/tools/knowledge_base.py` | `LocalKnowledgeBase` (JSON local, Jaccard) / `AzureAISearchKnowledgeBase`. |
| Persistance | `src/tools/persistence.py` | `LocalPersistenceStore` (fichiers JSON) / `CosmosPersistenceStore`. |
| Configuration | `src/config.py` | `Settings` (pydantic-settings), seuils, modes, `REPO_ROOT`. |
| CLI | `src/main.py` | Point d'entrée terminal : streaming + approbation `input()`. |
| API | `src/api/` | FastAPI : `/api/runs` (SSE), `/api/history`, `/api/meta`, `/api/health`. |
| Frontend | `frontend/` | React + Vite + TypeScript : graphe animé, cartes par étape, validation humaine, historique. |
| Infrastructure | `infra/`, `azure.yaml` | Bicep + Azure Developer CLI : provisionnement Azure complet. |

## 4. Les 6 agents (`src/agents/`)

Chaque agent est une classe `StructuredAgent[ResponseT]` (voir §5) qui
combine :
- `name` — nom utilisé comme `agent_name` (clé du `StubChatClient`, nom de
  l'`Agent` Azure OpenAI) ;
- `instructions` — prompt système (toujours « réponds uniquement en JSON,
  sans Markdown ») ;
- `response_model` — le modèle pydantic de sortie (`src/models.py`) ;
- `build_prompt(...)` — fonction qui construit le prompt utilisateur à partir
  du `SharedContext`.

### 4.1 `LogAnalyzer` (`src/agents/log_analyzer.py`)

- **Rôle** : normalise les logs bruts en signal exploitable.
- **Modèle suggéré** : léger (`gpt-4o-mini`).
- **Entrée** (`build_prompt(raw_logs, *, focus=None)`) : les logs bruts, et
  optionnellement une liste `focus` de points à investiguer en priorité
  (utilisée par `GatherEvidence`, voir §6 de `how-it-works.md`).
- **Sortie** : `LogAnalysis`
  - `timeline: list[TimelineEvent]` — événements horodatés (`time`, `event`).
  - `anomalies: list[str]` — saturations, pics de latence/erreur.
  - `correlated_events: list[str]` — corrélations temporelles (ex.
    déploiement → dégradation).

### 4.2 `IncidentExtractor` (`src/agents/incident_extractor.py`)

- **Rôle** : transforme l'analyse de logs en objet incident structuré.
- **Modèle suggéré** : léger.
- **Entrée** (`build_prompt(log_analysis)`) : le `LogAnalysis` produit par
  `LogAnalyzer`, sérialisé en JSON.
- **Sortie** : `Incident`
  - `titre: str`, `severite: str` (regex `^SEV-[1-5]$`),
    `services: list[str]`, `fenetre: str`, `symptomes: list[str]`.

### 4.3 `KBSearch` (`src/agents/kb_search.py`)

- **Rôle** : recherche de précédents similaires (RAG) et reformatage de la
  liste finale.
- **Modèle suggéré** : léger.
- **Particularité** : c'est le seul agent qui **surcharge `run()`**. Avant
  d'appeler le LLM, il interroge directement
  `KnowledgeBase.search(incident, top_k=2)` (§7.1) pour obtenir des
  candidats avec un score de similarité brut, puis demande au LLM de
  confirmer/formater la liste finale via `build_prompt(incident, candidates)`.
- **Sortie** : `KBMatches` → `matches: list[KBMatch]`, chaque `KBMatch` ayant
  `id`, `similarite` (0-1), `resolution`.

### 4.4 `RootCause` (`src/agents/root_cause.py`)

- **Rôle** : l'agent **le plus important**. Formule la meilleure hypothèse de
  cause racine, avec un score de confiance qui pilote la boucle de réflexion
  de l'orchestrateur.
- **Modèle suggéré** : fort (`gpt-4o`).
- **Entrée** (`build_prompt(incident, log_analysis, kb_matches, *,
  evidence_log=None)`) : l'incident, l'analyse de logs, les précédents KB, et
  — au 2ᵉ passage — les preuves supplémentaires collectées par
  `GatherEvidence` (`evidence_log`).
- **Sortie** : `RootCauseHypothesis`
  - `cause: str`, `raisonnement: str`, `confiance: float` (0-1),
    `preuves_manquantes: list[str]` — rempli uniquement si `confiance` est
    faible ; c'est cette liste que `GatherEvidence` utilise comme `focus`
    pour `LogAnalyzer` au tour suivant.

### 4.5 `Remediation` (`src/agents/remediation.py`)

- **Rôle** : propose un plan de remédiation priorisé. **Invoqué uniquement
  après validation humaine** (porte HITL, §8.2 et `how-it-works.md` §4).
- **Modèle suggéré** : fort.
- **Entrée** (`build_prompt(incident, root_cause, kb_matches)`).
- **Sortie** : `RemediationPlan` → trois listes `immediat`, `court_terme`,
  `long_terme`. Ce plan est **uniquement affiché** — voir contrainte #6 du
  §2 ; aucun exécuteur n'appelle une API d'infrastructure réelle.

### 4.6 `Summary` (`src/agents/summary.py`)

- **Rôle** : rédige le rapport d'incident final, prêt à coller dans un
  post-mortem.
- **Modèle suggéré** : léger.
- **Entrée** (`build_prompt(incident, log_analysis, root_cause,
  remediation_plan, kb_matches)`) : tout le contexte accumulé.
- **Sortie** : `IncidentReport`
  - Champs structurés : `titre`, `fenetre`, `impact`, `cause_racine`,
    `confiance`, `remediation: list[str]` (fusion immédiat/court/long terme),
    `precedent_lie: str | None`.
  - `texte: str` — le rapport complet en texte brut, avec les sections
    « CAUSE RACINE (confiance X) », « REMÉDIATION » (liste numérotée) et
    « PRÉCÉDENT LIÉ ».

## 5. `StructuredAgent` et clients de chat

### 5.1 `StructuredAgent[ResponseT]` (`src/agents/base.py`)

Classe générique minimaliste dont héritent les 6 agents :

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

Toute la différence entre « mode hors-ligne » et « Azure OpenAI réel » est
encapsulée dans l'objet `client` injecté — les agents eux-mêmes sont
identiques dans les deux modes.

### 5.2 `StructuredChatClient` (`src/agents/clients.py`)

Protocole minimal : `get_structured_response(*, agent_name, instructions,
prompt, response_model) -> ResponseT`. Deux implémentations :

- **`StubChatClient`** — déterministe, **zéro appel réseau**. Pour chaque
  `agent_name`, `_STUB_RESPONSES` contient soit une réponse unique rejouée à
  chaque appel, soit une **liste** indexée par numéro d'appel (utilisée
  uniquement pour `RootCause` et `LogAnalyzer`, afin de simuler la boucle de
  réflexion : 1er appel confiance 0.55, 2e appel — après `GatherEvidence` —
  confiance 0.88). Permet d'exécuter toute la démo et de vérifier les 8
  critères d'acceptation (`SPEC.md` §8) **sans aucun identifiant Azure**.
- **`AzureOpenAIStructuredChatClient`** — agents réels via
  `agent_framework.openai.OpenAIChatCompletionClient.as_agent(...)`, avec
  `default_options={"response_format": response_model}` pour forcer une
  sortie JSON conforme au schéma pydantic. Un `Agent` est mis en cache par
  couple `(agent_name, response_model)`.

`get_chat_client(settings, *, light: bool)` choisit automatiquement entre les
deux selon `Settings.use_real_azure_openai` (vrai si
`AZURE_OPENAI_ENDPOINT` est défini et n'est pas le placeholder de
`.env.example`). `light=True` sélectionne le déploiement
`AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT` (`gpt-4o-mini`), `light=False` le
déploiement `AZURE_OPENAI_CHAT_DEPLOYMENT` (`gpt-4o`).

## 6. Contrats de données (`src/models.py`)

Tous les contrats sont des modèles **pydantic** ; les agents répondent
**uniquement** en JSON validé contre ces schémas (jamais de Markdown autour).

| Modèle | Champs principaux | Produit par |
|--------|---------------------|-------------|
| `TimelineEvent` | `time`, `event` | (sous-objet de `LogAnalysis`) |
| `LogAnalysis` | `timeline`, `anomalies`, `correlated_events` | `LogAnalyzer` |
| `Incident` | `titre`, `severite` (`^SEV-[1-5]$`), `services`, `fenetre`, `symptomes` | `IncidentExtractor` |
| `KBMatch` / `KBMatches` | `id`, `similarite`, `resolution` / `matches: list[KBMatch]` | `KBSearch` |
| `RootCauseHypothesis` | `cause`, `raisonnement`, `confiance` (0-1), `preuves_manquantes` | `RootCause` |
| `RemediationPlan` | `immediat`, `court_terme`, `long_terme` | `Remediation` |
| `IncidentReport` | `titre`, `fenetre`, `impact`, `cause_racine`, `confiance`, `remediation`, `precedent_lie`, `texte` | `Summary` |
| `RemediationApprovalRequest` | `incident`, `root_cause`, `kb_matches`, `message` | `HumanApprovalExecutor` (porte HITL) |

### `SharedContext` — l'état central

`SharedContext` est l'objet unique qui circule entre tous les exécuteurs (via
`ctx.send_message`) et accumule les résultats :

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

- Les champs « ponctuels » (`log_analysis`, `incident`, `root_cause`, …) sont
  **réassignés** à chaque passage — ils ne reflètent que la dernière valeur.
- Les champs « cumulatifs » (`root_cause_history`, `evidence_log`) sont
  **étendus** (`.append`/`.extend`) — ils conservent l'historique complet,
  notamment les deux passages de `RootCause` en cas de boucle de réflexion.
- `loop_count` est incrémenté par `GatherEvidenceExecutor` et c'est lui qui,
  combiné à `confiance`, détermine la sortie de la boucle (voir
  `how-it-works.md` §3).

Pour la propagation exacte (référence partagée vs copies, sémantique en
streaming), voir `how-it-works.md` §1.

## 7. Outils (`src/tools/`)

### 7.1 Base de connaissances RAG (`knowledge_base.py`)

Interface `KnowledgeBase` : `async def search(incident, *, top_k=2) ->
list[KBMatch]`.

- **`LocalKnowledgeBase`** (mode `KB_MODE=local`, par défaut) — lit
  `data/knowledge_base.json` et calcule un **score de similarité de
  Jaccard** entre le vocabulaire de l'incident courant (`services` +
  `symptomes`) et celui de chaque précédent (`services` + `symptomes` +
  `tags`). Avec seulement deux précédents et `top_k=2`, les deux sont
  toujours retournés (critère d'acceptation 2 de `SPEC.md`).
- **`AzureAISearchKnowledgeBase`** (mode `KB_MODE=azure_search`) — interroge
  un index Azure AI Search via `azure.search.documents.aio.SearchClient`,
  même interface.

`get_knowledge_base(settings)` choisit selon `settings.kb_mode`.

### 7.2 Persistance (`persistence.py`)

Interface `PersistenceStore` : `save(record)`, `list_records(*, limit=20)`,
`get_record(run_id)`.

- **`LocalPersistenceStore`** (par défaut, sans `COSMOS_ENDPOINT`) — un
  fichier JSON par exécution sous `output/runs/`.
- **`CosmosPersistenceStore`** (si `COSMOS_ENDPOINT` est défini) — un
  document par exécution dans un conteneur Azure Cosmos DB (partition key
  `/id`), via `azure.cosmos.aio.CosmosClient`. Le compte/base/conteneur sont
  provisionnés par `infra/` ; le code ne fait que du plan de données.

`get_persistence_store(settings)` choisit selon `settings.cosmos_endpoint`.
`IncidentRecord` (enregistrement complet, incl. `SharedContext`) et
`IncidentRecordSummary` (vue résumée pour la liste d'historique) sont définis
dans ce module.

## 8. Orchestrateur (`src/orchestrator/`)

Vue d'ensemble ici ; mécanique détaillée (boucle, HITL, propagation) dans
[`how-it-works.md`](how-it-works.md).

### 8.1 `graph.py` — `build_workflow(settings)`

Construit le `Workflow` (`WorkflowBuilder(start_executor=log_analyzer,
output_from="all")`) :

1. Instancie `light_client`/`strong_client` (`get_chat_client`) et
   `knowledge_base` (`get_knowledge_base`).
2. Instancie les 8 exécuteurs (un par nœud du graphe ; `log_analyzer_agent`
   et `kb_search_agent` sont **partagés** entre le pipeline principal et
   `GatherEvidenceExecutor`).
3. Chaîne `log_analyzer -> incident_extractor -> kb_search -> root_cause`.
4. Ajoute l'arête conditionnelle (`add_switch_case_edge_group`) après
   `root_cause` : `Case(needs_more_evidence -> gather_evidence)`,
   `Default(-> human_approval)`.
5. `add_edge(gather_evidence, root_cause)` ferme la boucle.
6. Chaîne `human_approval -> remediation -> summary`.

### 8.2 `executors.py` — les 8 exécuteurs

| Exécuteur | Agent enveloppé | Particularité |
|-----------|------------------|----------------|
| `LogAnalyzerExecutor` | `LogAnalyzerAgent` | premier nœud |
| `IncidentExtractorExecutor` | `IncidentExtractorAgent` | — |
| `KBSearchExecutor` | `KBSearchAgent` | — |
| `RootCauseExecutor` | `RootCauseAgent` | alimente `root_cause_history` |
| `GatherEvidenceExecutor` | réutilise `LogAnalyzerAgent` + `KBSearchAgent` | incrémente `loop_count`, cible `preuves_manquantes` |
| `HumanApprovalExecutor` | aucun (porte pure) | `ctx.request_info()` + `@response_handler`, état sur `self._context` |
| `RemediationExecutor` | `RemediationAgent` | exécuté seulement si approuvé |
| `SummaryExecutor` | `SummaryAgent` | terminal, `yield_output` seul |

Chaque exécuteur (sauf `SummaryExecutor` et le cas de refus de
`HumanApprovalExecutor`) appelle `ctx.yield_output(context)` (pour
l'observabilité en streaming) **puis** `ctx.send_message(context)` (pour
avancer dans le graphe).

## 9. API (`src/api/`)

FastAPI exposant `build_workflow` sur HTTP, consommée par le frontend React.

| Module | Rôle |
|--------|------|
| `app.py` | `create_app()` : CORS (dev Vite), montage des routers sous `/api`, `GET /api/health`, et — en production — sert `frontend/dist/` via `StaticFiles` (même port, pas de CORS). |
| `runs.py` | `POST /api/runs` et `POST /api/runs/{run_id}/approval` — les deux endpoints SSE qui pilotent le workflow. Registre en mémoire `app.state.runs: dict[str, RunState]`. |
| `history.py` | `GET /api/history` (liste résumée) et `GET /api/history/{run_id}` (détail), via `PersistenceStore`. |
| `meta.py` | `GET /api/meta` — paramètres non sensibles exposés à l'UI (`confidence_threshold`, `max_reflection_loops`, `kb_mode`, `use_real_azure_openai`, `cosmos_enabled`). |
| `dependencies.py` | Indirection `settings_dependency`/`persistence_dependency` pour permettre aux tests de surcharger via `app.dependency_overrides`. |
| `sse.py` | `sse_event(event, data)` — formate un message SSE (`event: ...\ndata: ...\n\n`). |

Le détail du protocole SSE (événements, deux phases, gestion de l'état entre
les deux appels HTTP) est dans `how-it-works.md` §5.

## 10. Frontend (`frontend/`)

React + Vite + TypeScript. En dev, `vite.config.ts` proxy `/api` vers
`127.0.0.1:8000` (pas de CORS) ; en prod, `frontend/dist/` est servi par
FastAPI (same-origin).

| Fichier | Rôle |
|---------|------|
| `src/App.tsx` | État de la page (`phase`, `steps`, `approvalRequest`, …), branche les callbacks SSE sur `api.ts`, assemble les composants. |
| `src/api.ts` | Client HTTP/SSE : `startRun`, `submitApproval` (parsent le flux `text/event-stream` via `fetch` + `ReadableStream`, car `EventSource` ne supporte pas POST), `fetchMeta`, `fetchHistory`, `fetchHistoryRecord`. |
| `src/types.ts` | Types miroir 1:1 de `src/models.py` + réponses de `src/api/*.py`. Tenus à jour manuellement (un seul jeu de contrats côté backend). |
| `src/components/TopologyGraph.tsx` | Anime le graphe à 8 nœuds (mirroir de `graph.py`) au fil des événements `step`. |
| `src/components/StepCard.tsx` | Rendu détaillé de la sortie de chaque agent (timeline, anomalies, incident, précédents KB, cause racine + jauge de confiance, plan de remédiation, rapport). |
| `src/components/ApprovalCard.tsx` | Porte HITL : affiche incident/cause/précédents/jauge de confiance, boutons Approuver/Refuser. |
| `src/components/ConfidenceBar.tsx` | Jauge `confiance` vs `CONFIDENCE_THRESHOLD`. |
| `src/components/Header.tsx` | Titre, onglets Démo/Historique, badges de configuration (`/api/meta`). |
| `src/components/History.tsx` | Liste des exécutions passées + vue détail d'un enregistrement. |

## 11. Infrastructure (`infra/`, `azure.yaml`)

Provisionnement Azure via Bicep + Azure Developer CLI (`azd`). Détails et
guide pas à pas dans [`deployment.md`](deployment.md) §Azure ; liste complète
des ressources et rationale dans `DECISIONS.md` #21-22.

| Fichier | Rôle |
|---------|------|
| `azure.yaml` | Déclare le service `api` (`language: docker`, `host: containerapp`, `docker.path: ./Dockerfile`). |
| `infra/main.bicep` | Portée `subscription` : crée le resource group, calcule `resourceToken`, délègue à `resources.bicep`. |
| `infra/resources.bicep` | Portée resource group : ~13 ressources (Log Analytics, App Insights, identité managée, Container Registry, Azure OpenAI + 2 déploiements, Azure AI Search, Cosmos DB serverless, Container Apps Environment + Container App) + role assignments. |
| `infra/main.parameters.json` | Paramètres `azd` (`${AZURE_ENV_NAME}`, `${AZURE_LOCATION}`, `${AZURE_PRINCIPAL_ID}`). |

## 12. Stack technique

| Domaine | Choix |
|---------|-------|
| Langage backend | Python 3.11+ |
| Orchestration agents | `agent-framework` (`WorkflowBuilder`, `Executor`, `ctx.request_info`) |
| Modèles | Azure OpenAI — `gpt-4o` (fort), `gpt-4o-mini` (léger) ; mode hors-ligne via `StubChatClient` |
| Validation des contrats | `pydantic` v2 |
| Configuration | `pydantic-settings` (`.env`) |
| API | FastAPI + `uvicorn`, SSE (`text/event-stream`) |
| Frontend | React + Vite + TypeScript |
| RAG | `data/knowledge_base.json` (local) ou Azure AI Search |
| Persistance | fichiers JSON locaux (`output/runs/`) ou Azure Cosmos DB |
| Auth Azure | `AzureCliCredential` (local) / `DefaultAzureCredential` (déployé, Managed Identity) |
| Conteneurisation | Dockerfile multi-étapes (build frontend + image Python) |
| IaC / déploiement | Bicep + Azure Developer CLI (`azd`), Azure Container Apps |
| Observabilité | Application Insights provisionné (OTel non encore câblé — voir « Pistes d'évolution » du `README.md`) |
