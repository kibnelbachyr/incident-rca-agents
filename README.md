# Incident RCA Agents — démo multi-agents (paiement)

Démo d'un système **multi-agents orchestré** (Microsoft Agent Framework) qui
diagnostique un incident sur un système de paiement : logs bruts → incident
structuré → recherche de précédents → cause racine (avec boucle de
réflexion) → remédiation (validée par un humain) → rapport final.

Deux façons d'exécuter la démo, même orchestrateur :
- **CLI** (`python -m src.main`) — streaming texte dans le terminal.
- **UI web** (FastAPI + React, `src/api/` + `frontend/`) — graphe
  d'orchestration animé, validation humaine et historique des exécutions.

Le tout est **déployable sur Azure** via Bicep + Azure Developer CLI
(`azd up`, voir `infra/`).

Pour aller plus loin : `docs/` (documentation détaillée — composants,
fonctionnement interne, déploiement, démo), `CLAUDE.md` (stack et contraintes
du projet), `SPEC.md` (spécification détaillée et contrats d'agents),
`scenario-demo-incident-paiement.md` (déroulé de présentation pas à pas) et
`DECISIONS.md` (journal des choix d'architecture pris en autonomie).

## En un coup d'œil

| # | Agent | Rôle | Modèle |
|---|-------|------|--------|
| 1 | `LogAnalyzer` | Normalise les logs : timeline + anomalies + corrélations | léger |
| 2 | `IncidentExtractor` | Produit l'objet `Incident` structuré | léger |
| 3 | `KBSearch` | Recherche de précédents dans la base de connaissances (RAG) | léger |
| 4 | `RootCause` | Hypothèse de cause racine + score de confiance | fort |
| 5 | `Remediation` | Plan de remédiation (proposé, derrière une validation humaine) | fort |
| 6 | `Summary` | Rapport d'incident final | léger |

Les agents sont **sans état** et ne se parlent jamais directement : tout passe
par l'orchestrateur et le `SharedContext` (`src/models.py`).

Topologie du graphe d'orchestration (`src/orchestrator/graph.py`) :

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

Contraintes non négociables (`CLAUDE.md`) :
- Boucle de réflexion **bornée** par `MAX_REFLECTION_LOOPS` (défaut `2`).
- Sous `CONFIDENCE_THRESHOLD` (défaut `0.75`), l'orchestrateur reboucle pour
  chercher des preuves au lieu de conclure.
- **Aucune remédiation sans validation humaine** (`ctx.request_info`).
- La remédiation reste un **plan affiché**, jamais exécuté sur un vrai système.
- Aucun secret en clair : tout passe par `.env` / variables d'environnement /
  Key Vault.

## Démarrage rapide (mode hors-ligne, sans Azure)

Aucun identifiant Azure n'est requis pour exécuter la démo : tant que
`AZURE_OPENAI_ENDPOINT` n'est pas configuré avec un endpoint réel, tous les
agents utilisent un `StubChatClient` déterministe qui rejoue le scénario de
`scenario-demo-incident-paiement.md` (`DECISIONS.md` #3-4).

### CLI

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Lance la démo sur l'incident d'exemple
python -m src.main --logs data/payment-incident.log
```

La démo affiche la sortie de chaque agent au fil de l'eau (streaming), y
compris le 1er passage de `RootCause` (confiance 0,55, sous le seuil) et la
boucle `GatherEvidence -> RootCause` (confiance 0,88). Elle s'arrête ensuite
sur la porte de validation humaine :

```
Approuver le passage à la remédiation ? [o/N] :
```

- `o` / `oui` / `y` / `yes` → le `RemediationPlan` puis le rapport final
  (`IncidentReport`) sont affichés.
- toute autre réponse (ou une entrée non interactive / EOF) → le workflow
  s'arrête immédiatement, sans générer ni afficher de plan de remédiation.

### Interface web (FastAPI + React)

Deux process en développement :

```bash
# Terminal 1 : API (port 8000)
pip install -e ".[dev]"
uvicorn src.api.app:app --reload

# Terminal 2 : frontend (port 5173, proxy /api -> :8000 via vite.config.ts)
cd frontend
npm install
npm run dev
```

Ouvrir http://localhost:5173 : « Lancer le diagnostic » démarre une exécution
(`POST /api/runs`, SSE) et anime le graphe d'orchestration (`TopologyGraph`)
au fil des évènements `step`, jusqu'à la carte de validation humaine
(`ApprovalCard`) — approuver/refuser appelle `POST /api/runs/{run_id}/approval`.
L'onglet historique (`History`) liste les exécutions terminées et persistées
(`GET /api/history`, `src/tools/persistence.py`).

En production (image Docker / Azure), un seul process : `frontend/dist/`
(`npm run build`) est servi par FastAPI via `StaticFiles`, sur le même port
que l'API (`src/api/app.py`) — pas de CORS à gérer.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

- `tests/agents/` — un test isolé par agent (contrat d'entrée/sortie via
  `StubChatClient`).
- `tests/orchestrator/test_workflow.py` — test de bout en bout sur
  `data/payment-incident.log`, qui vérifie les **8 critères d'acceptation**
  de `SPEC.md` section 8 : incident SEV-1, deux précédents KB, reboucle sous
  le seuil de confiance, cause racine `max_pool_size` au 2e passage, pause
  HITL, plan + rapport après approbation, sorties observables, boucle bornée.
- `tests/api/test_runs.py` — les deux phases SSE de `/api/runs`
  (`run_started`/`step`/`approval_required`/`done`), approbation et refus.
- `tests/tools/test_persistence.py` — `LocalPersistenceStore`.

Frontend : `cd frontend && npm run build` (vérifie les types via `tsc -b`
puis build Vite vers `frontend/dist/`).

## Configuration

Toute la configuration passe par l'environnement / `.env` (voir
`.env.example`), chargé par `src/config.py` (`Settings`, pydantic-settings).
Rien n'est codé en dur.

| Variable | Rôle | Défaut |
|----------|------|--------|
| `AZURE_OPENAI_ENDPOINT` | Endpoint Azure OpenAI / Foundry. Si absent (ou placeholder de `.env.example`), `StubChatClient` est utilisé | _(aucun)_ |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Déploiement « fort » (`RootCause`, `Remediation`) | `gpt-4o` |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT` | Déploiement « léger » (autres agents) | `gpt-4o-mini` |
| `AZURE_OPENAI_API_VERSION` | Version d'API Azure OpenAI | `2024-10-21` |
| `AZURE_AUTH_MODE` | `cli` (local, `az login`) ou `managed_identity` (déployé) | `cli` |
| `AZURE_AI_SEARCH_ENDPOINT`, `AZURE_AI_SEARCH_INDEX` | Base de connaissances RAG en mode déployé | _(aucun)_ |
| `KB_MODE` | `local` (`data/knowledge_base.json`) ou `azure_search` | `local` |
| `CONFIDENCE_THRESHOLD` | Seuil de confiance de `RootCause` | `0.75` |
| `MAX_REFLECTION_LOOPS` | Nombre max de reboucles `RootCause <-> GatherEvidence` | `2` |
| `COSMOS_*`, `APPLICATIONINSIGHTS_CONNECTION_STRING` | Persistance / observabilité (optionnel pour la démo) | _(aucun)_ |

### Utiliser Azure OpenAI (modèles réels)

1. `az login` (mode `AZURE_AUTH_MODE=cli`, par défaut en local).
2. Renseigner `AZURE_OPENAI_ENDPOINT` et les noms de déploiement dans `.env`.
3. `python -m src.main` utilise alors `AzureOpenAIStructuredChatClient`
   (`src/agents/clients.py`) — mêmes agents, mêmes contrats pydantic, sorties
   JSON forcées via `response_format`.

### Basculer la base de connaissances vers Azure AI Search

1. Créer un index Azure AI Search et y charger `data/knowledge_base.json`
   (voir `SPEC.md` section 7).
2. Définir `KB_MODE=azure_search`, `AZURE_AI_SEARCH_ENDPOINT` et
   `AZURE_AI_SEARCH_INDEX` dans `.env`.
3. `get_knowledge_base()` (`src/tools/knowledge_base.py`) bascule
   automatiquement sur `AzureAISearchKnowledgeBase`, qui implémente la même
   interface `KnowledgeBase` que `LocalKnowledgeBase`.

## Conteneurisation

```bash
docker build -t incident-rca-agents .
docker run --rm -it -p 8000:8000 incident-rca-agents
```

Ouvrir http://localhost:8000 : l'image (build multi-étapes, `Dockerfile`)
sert l'API **et** l'UI buildée (`frontend/dist/`) sur le même port via un
seul process `uvicorn src.api.app:app` (DECISIONS.md #20). `pip install -e .`
garde `src.config.REPO_ROOT` aligné sur `/app` (où `data/` est copié) : les
chemins par défaut (`data/payment-incident.log`, `data/knowledge_base.json`)
fonctionnent sans configuration supplémentaire. `AZURE_AUTH_MODE=managed_identity`
est défini par défaut pour un déploiement Azure Container Apps avec identité
managée (`DefaultAzureCredential`) ; passez vos variables `AZURE_*` via
`docker run -e ...` ou les secrets Container Apps. En local hors-ligne (sans
`AZURE_OPENAI_ENDPOINT`), `StubChatClient` est utilisé et aucune variable
n'est requise.

## Déploiement sur Azure (azd)

`infra/` (Bicep) + `azure.yaml` provisionnent l'architecture cible décrite
par `CLAUDE.md` et déploient l'image Docker ci-dessus sur Azure Container
Apps (DECISIONS.md #21-22) : Azure OpenAI (déploiements `gpt-4o` +
`gpt-4o-mini`), Azure AI Search, Azure Cosmos DB serverless, Container
Registry, Container Apps Environment + Container App, Log Analytics +
Application Insights, et une identité managée avec les role assignments
nécessaires (aucune clé API en clair — `disableLocalAuth: true` sur Azure
OpenAI et Cosmos DB).

```bash
# Installer azd : https://aka.ms/azd
azd auth login
azd up   # provisionne infra/ puis build + push + déploie l'image Docker
```

`azd up` demande un nom d'environnement et une région (choisir une région où
les déploiements GPT-4o / GPT-4o-mini "GlobalStandard" sont disponibles, ex.
`swedencentral`, `eastus2`) ; l'URL du Container App est affichée à la fin.

Pour faire tourner l'API en local contre les ressources réellement déployées
(au lieu de `StubChatClient`) :

```bash
azd env get-values >> .env   # AZURE_OPENAI_ENDPOINT, COSMOS_ENDPOINT, ...
az login                      # AZURE_AUTH_MODE=cli (défaut) -> AzureCliCredential
uvicorn src.api.app:app --reload
```

`KB_MODE` reste `local` par défaut même après `azd up` (l'index Azure AI
Search est créé vide, voir DECISIONS.md #22). `azd down` supprime toutes les
ressources de l'environnement.

## Structure du dépôt

```
src/
├── agents/          # 6 agents (instructions + contrat pydantic) + clients (stub/Azure OpenAI)
├── api/             # FastAPI : /api/runs (SSE, 2 phases + HITL), /api/history, /api/meta
├── orchestrator/    # graphe WorkflowBuilder : executors + topologie + boucle + HITL
├── tools/           # base de connaissances (local / Azure AI Search) + persistance (local / Cosmos DB)
├── config.py        # Settings (pydantic-settings, lit .env)
├── models.py        # contrats pydantic (SPEC.md section 4)
└── main.py          # CLI : streaming des sorties + validation humaine

frontend/            # UI React + Vite : graphe d'orchestration, validation humaine, historique

infra/               # Bicep (azd) : main.bicep (resource group) + resources.bicep
azure.yaml           # config Azure Developer CLI (`azd up`)

data/
├── payment-incident.log   # logs d'exemple (incident SEV-1)
└── knowledge_base.json    # deux précédents (INC-204, INC-187)

tests/
├── agents/          # un test isolé par agent
├── api/             # tests SSE de /api/runs (approbation + refus)
├── orchestrator/    # test de bout en bout (8 critères de SPEC.md section 8)
└── tools/           # persistance locale

docs/                # documentation détaillée (architecture, fonctionnement, déploiement, démo)
```

## Pistes d'évolution (hors périmètre de la démo)

- Peupler un index Azure AI Search à partir de `data/knowledge_base.json`
  (pipeline d'indexation), puis basculer `KB_MODE=azure_search` — l'index et
  le rôle `Search Index Data Reader` sont déjà provisionnés par `azd up`
  (DECISIONS.md #22).
- Connecter automatiquement Application Insights au projet Microsoft Foundry
  via Bicep — aujourd'hui une étape manuelle ponctuelle dans le portail
  (`docs/deployment.md` §8.12, DECISIONS.md #25).

## Aller plus loin

- `docs/` — documentation détaillée : [`docs/architecture.md`](docs/architecture.md)
  (composants, contrats, conception), [`docs/how-it-works.md`](docs/how-it-works.md)
  (boucle de réflexion, HITL, flux SSE), [`docs/deployment.md`](docs/deployment.md)
  (dev local, Docker, Azure/azd, configuration, observabilité §8.12, agents
  visibles dans Microsoft Foundry §8.13) et
  [`docs/demo-guide.md`](docs/demo-guide.md) (déroulé de démo pas à pas, CLI et UI).
- `SPEC.md` — contrats JSON détaillés, topologie d'orchestration, critères
  d'acceptation, architecture de déploiement Azure.
- `DECISIONS.md` — choix d'architecture pris en autonomie et leur
  justification.
- `scenario-demo-incident-paiement.md` — déroulé de présentation pas à pas.
