# Guide de déploiement

> Du poste local (mode hors-ligne, sans identifiants Azure) jusqu'à un
> déploiement complet sur Azure Container Apps via `azd`. Pour la
> configuration de la démo elle-même, voir [`demo-guide.md`](demo-guide.md).

## 1. Prérequis

| Scénario | Prérequis |
|----------|-----------|
| Dev local, mode hors-ligne (`StubChatClient`) | Python 3.11+, Node.js 20+ (pour l'UI web) — **aucun identifiant Azure** |
| Dev local contre Azure OpenAI / AI Search / Cosmos réels | + `az login` (CLI Azure), accès aux ressources |
| Docker | Docker (build multi-étapes : Node 20 puis Python 3.11) |
| Déploiement Azure | [Azure Developer CLI (`azd`)](https://aka.ms/azd), abonnement Azure |

Aucun identifiant Azure n'est requis pour exécuter la démo : tant que
`AZURE_OPENAI_ENDPOINT` n'est pas configuré avec un endpoint réel (ou reste
le placeholder de `.env.example`), `Settings.use_real_azure_openai` est faux
et tous les agents utilisent `StubChatClient` (`src/agents/clients.py`),
déterministe et sans appel réseau.

## 2. Développement local

### 2.1 Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 2.2 CLI

```bash
python -m src.main --logs data/payment-incident.log
```

Streame chaque sortie d'agent, y compris la boucle de réflexion, puis
s'arrête sur la porte HITL :

```
Approuver le passage à la remédiation ? [o/N] :
```

- `o` / `oui` / `y` / `yes` → `RemediationPlan` puis `IncidentReport`
  affichés.
- Toute autre réponse (ou EOF / entrée non interactive) → arrêt immédiat,
  sans plan ni rapport.

### 2.3 Interface web (FastAPI + React)

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

Ouvrir http://localhost:5173 :
- « Lancer le diagnostic » → `POST /api/runs` (SSE), anime
  `TopologyGraph` au fil des événements `step`.
- À la porte HITL, `ApprovalCard` s'affiche → Approuver/Refuser appelle
  `POST /api/runs/{run_id}/approval`.
- Onglet « Historique » → `GET /api/history` / `GET /api/history/{run_id}`
  (`src/tools/persistence.py`).

## 3. Référence de configuration

Toute la configuration passe par l'environnement / `.env` (voir
`.env.example`), chargée par `src/config.py::Settings` (pydantic-settings).
**Rien n'est codé en dur**, et `.env` reste hors du dépôt git
(`.gitignore`) — seul `.env.example` est versionné.

| Variable | Rôle | Défaut |
|----------|------|--------|
| `AZURE_OPENAI_ENDPOINT` | Endpoint Azure OpenAI / Foundry. Absent ou placeholder → `StubChatClient` | _(aucun)_ |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Déploiement « fort » (`RootCause`, `Remediation`) | `gpt-4o` |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT` | Déploiement « léger » (autres agents) | `gpt-4o-mini` |
| `AZURE_OPENAI_API_VERSION` | Version d'API Azure OpenAI | `2024-10-21` |
| `AZURE_AUTH_MODE` | `cli` (local, `az login` → `AzureCliCredential`) ou `managed_identity` (déployé → `DefaultAzureCredential`) | `cli` |
| `AZURE_AI_SEARCH_ENDPOINT` | Endpoint Azure AI Search (mode `azure_search`) | _(aucun)_ |
| `AZURE_AI_SEARCH_INDEX` | Nom de l'index Azure AI Search | `incident-kb` |
| `KB_MODE` | `local` (`data/knowledge_base.json`) ou `azure_search` | `local` |
| `COSMOS_ENDPOINT` | Endpoint Cosmos DB. Absent → persistance locale (`output/runs/`) | _(aucun)_ |
| `COSMOS_DATABASE` | Base Cosmos DB | `incidents` |
| `COSMOS_CONTAINER` | Conteneur Cosmos DB (partition key `/id`) | `records` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Chaîne de connexion App Insights (provisionnée, pas encore exploitée par le code) | _(aucun)_ |
| `CONFIDENCE_THRESHOLD` | Seuil de confiance de `RootCause` | `0.75` |
| `MAX_REFLECTION_LOOPS` | Nombre max de reboucles `RootCause ↔ GatherEvidence` | `2` |

`GET /api/meta` expose à l'UI le sous-ensemble non sensible :
`confidence_threshold`, `max_reflection_loops`, `kb_mode`,
`use_real_azure_openai`, `cosmos_enabled`.

## 4. Basculer vers Azure OpenAI (modèles réels)

1. `az login` (mode `AZURE_AUTH_MODE=cli`, par défaut en local).
2. Renseigner dans `.env` : `AZURE_OPENAI_ENDPOINT` (endpoint réel, ne
   commençant pas par `https://<`) et les noms de déploiement
   (`AZURE_OPENAI_CHAT_DEPLOYMENT`, `AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT`).
3. `python -m src.main` (ou l'API) utilise alors
   `AzureOpenAIStructuredChatClient` (`src/agents/clients.py`) — mêmes
   agents, mêmes contrats pydantic, sorties JSON forcées via
   `response_format`.

> Avec des modèles réels, les sorties (notamment les scores de `confiance`)
> ne sont **plus garanties identiques** au scénario figé du
> `StubChatClient` — voir [`demo-guide.md`](demo-guide.md) « Variante : Azure
> OpenAI réel ».

## 5. Basculer la base de connaissances vers Azure AI Search

1. Créer un index Azure AI Search et y charger `data/knowledge_base.json`
   (voir `SPEC.md` §7 pour le schéma).
2. Définir dans `.env` : `KB_MODE=azure_search`, `AZURE_AI_SEARCH_ENDPOINT`,
   `AZURE_AI_SEARCH_INDEX`.
3. `get_knowledge_base()` (`src/tools/knowledge_base.py`) bascule
   automatiquement sur `AzureAISearchKnowledgeBase`, qui implémente la même
   interface `KnowledgeBase` que `LocalKnowledgeBase`.

> Note : `azd up` provisionne l'index Azure AI Search **vide** (pas de
> pipeline d'indexation). `KB_MODE` reste `local` même après déploiement,
> tant que `data/knowledge_base.json` n'a pas été indexé manuellement —
> sinon `KBSearch` ne retournerait aucun précédent (voir
> `DECISIONS.md` #22).

## 6. Persistance : locale vs Cosmos DB

- **Par défaut** (`COSMOS_ENDPOINT` absent) : `LocalPersistenceStore` écrit
  un fichier JSON par exécution sous `output/runs/`.
- **Si `COSMOS_ENDPOINT` est défini** : `CosmosPersistenceStore` (un
  document par exécution, partition key `/id`). Le compte/la base/le
  conteneur sont provisionnés par `infra/` (azd) — le code applicatif ne
  fait que du plan de données (`upsert_item`/`read_item`/`query_items`).

## 7. Conteneurisation (Docker)

```bash
docker build -t incident-rca-agents .
docker run --rm -it -p 8000:8000 incident-rca-agents
```

Ouvrir http://localhost:8000 — l'image (build multi-étapes, `Dockerfile`)
sert l'API **et** l'UI buildée (`frontend/dist/`) sur le même port via un
seul process `uvicorn src.api.app:app`.

- **Étape 1** (`node:20-slim`) : `npm ci && npm run build` dans
  `frontend/` → produit `frontend/dist/`.
- **Étape 2** (`python:3.11-slim`) : `pip install -e .` (garde
  `src.config.REPO_ROOT` aligné sur `/app`, où `data/` est copié — les
  chemins par défaut `data/payment-incident.log` et
  `data/knowledge_base.json` fonctionnent sans configuration) puis copie
  `frontend/dist/` depuis l'étape 1.

`AZURE_AUTH_MODE=managed_identity` est défini par défaut dans l'image (pour
un déploiement Container Apps avec identité managée). Pour pointer vers de
vraies ressources Azure, passez les variables `AZURE_*` via `docker run -e
...` ou les secrets Container Apps. En local hors-ligne (sans
`AZURE_OPENAI_ENDPOINT`), `StubChatClient` est utilisé et **aucune variable
n'est requise**.

## 8. Déploiement sur Azure (`azd`)

`infra/` (Bicep) + `azure.yaml` provisionnent l'architecture cible décrite
par `CLAUDE.md` et déploient l'image Docker ci-dessus sur **Azure Container
Apps**.

### 8.1 Ressources provisionnées (`infra/resources.bicep`)

| Ressource | Type Azure | Rôle |
|-----------|------------|------|
| Log Analytics workspace | `Microsoft.OperationalInsights/workspaces` | logs du Container Apps Environment |
| Application Insights | `Microsoft.Insights/components` | observabilité (connection string injectée, OTel non câblé côté code) |
| Identité managée (user-assigned) | `Microsoft.ManagedIdentity/userAssignedIdentities` | identité du Container App, porteuse des role assignments |
| Container Registry | `Microsoft.ContainerRegistry/registries` (Basic) | images de l'API |
| Azure OpenAI | `Microsoft.CognitiveServices/accounts` (kind `OpenAI`, sku `S0`) | + 2 déploiements : `gpt-4o` (`2024-08-06`) et `gpt-4o-mini` (`2024-07-18`), sku `GlobalStandard` |
| Azure AI Search | `Microsoft.Search/searchServices` (sku `basic`) | base de connaissances RAG (index vide à la création) |
| Azure Cosmos DB | `Microsoft.DocumentDB/databaseAccounts` (serverless) | base `incidents`, conteneur `records` (partition key `/id`) |
| Container Apps Environment | `Microsoft.App/managedEnvironments` | environnement d'exécution |
| Container App | `Microsoft.App/containerApps` | héberge l'API+UI, ingress externe port 8000, `azd-service-name: api` |

### 8.2 Sécurité : aucun secret en clair

`disableLocalAuth: true` sur Azure OpenAI **et** Cosmos DB désactive les clés
API/maître. Toute l'authentification data-plane passe par des **role
assignments Microsoft Entra ID**, accordés à l'identité managée du Container
App :

| Rôle | Cible | Usage |
|------|-------|-------|
| `Cognitive Services OpenAI User` | Azure OpenAI | appels de complétion |
| `Search Index Data Reader` | Azure AI Search | lecture de l'index RAG |
| Cosmos DB *Built-in Data Contributor* (`00000000-0000-0000-0000-000000000002`) | Cosmos DB | lecture/écriture des enregistrements |
| `AcrPull` | Container Registry | pull de l'image au démarrage |

Le Container App reçoit `AZURE_AUTH_MODE=managed_identity` et
`AZURE_CLIENT_ID=<identity.clientId>` (pour que `DefaultAzureCredential`
sélectionne cette identité). Un paramètre optionnel `principalId` (rempli
par `azd` via `AZURE_PRINCIPAL_ID`) accorde les **mêmes rôles data-plane** au
compte du développeur, pour pouvoir pointer un `.env` local
(`AZURE_AUTH_MODE=cli`) vers les ressources réellement déployées.

> `Microsoft.App/containerApps` est configuré avec `scale: {minReplicas: 1,
> maxReplicas: 1}` : `app.state.runs` (`src/api/runs.py`) est un registre en
> mémoire par processus — plusieurs réplicas casseraient la reprise HITL
> entre les deux appels SSE.

### 8.3 Déployer

```bash
azd auth login
azd up   # provisionne infra/ puis build + push + déploie l'image Docker
```

`azd up` demande un nom d'environnement et une région — choisir une région où
les déploiements GPT-4o / GPT-4o-mini « GlobalStandard » sont disponibles
(ex. `swedencentral`, `eastus2`). L'URL du Container App (`SERVICE_API_URI`)
est affichée à la fin.

### 8.4 Développer en local contre les ressources déployées

```bash
azd env get-values >> .env   # AZURE_OPENAI_ENDPOINT, COSMOS_ENDPOINT, ...
az login                      # AZURE_AUTH_MODE=cli (défaut) -> AzureCliCredential
uvicorn src.api.app:app --reload
```

`KB_MODE` reste `local` par défaut même après `azd up` (l'index Azure AI
Search est créé vide, §5 ci-dessus).

### 8.5 Nettoyage

```bash
azd down   # supprime toutes les ressources de l'environnement
```

## 9. Tests

```bash
pip install -e ".[dev]"
pytest
```

| Suite | Couverture |
|-------|------------|
| `tests/agents/` | un test isolé par agent (contrat d'entrée/sortie via `StubChatClient`) |
| `tests/orchestrator/test_workflow.py` | bout-en-bout sur `data/payment-incident.log`, vérifie les **8 critères d'acceptation** de `SPEC.md` §8 |
| `tests/api/test_runs.py` | les deux phases SSE de `/api/runs` (`run_started`/`step`/`approval_required`/`done`), approbation et refus |
| `tests/tools/test_persistence.py` | `LocalPersistenceStore` |

Frontend :

```bash
cd frontend && npm run build   # tsc -b puis build Vite vers frontend/dist/
```
