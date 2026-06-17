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
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Chaîne de connexion App Insights — active l'instrumentation OTel (`src/observability.py`, §8.12). Absent → no-op (mode hors-ligne) | _(aucun)_ |
| `CONFIDENCE_THRESHOLD` | Seuil de confiance de `RootCause` | `0.75` |
| `MAX_REFLECTION_LOOPS` | Nombre max de reboucles `RootCause ↔ GatherEvidence` | `2` |
| `AZURE_FOUNDRY_PROJECT_ENDPOINT` | Endpoint du projet Microsoft Foundry (`scripts/register_foundry_agents.py` uniquement, §8.13 — sans rapport avec l'exécution des agents) | _(aucun)_ |

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

## 8. Déploiement sur Azure (`azd`) — guide pas à pas

`infra/` (Bicep) + `azure.yaml` provisionnent l'architecture cible décrite
par `CLAUDE.md` et déploient l'image Docker (§7) sur **Azure Container
Apps**, en une seule commande (`azd up`). Cette section est un guide pas à
pas, du compte Azure vierge jusqu'à l'URL publique.

### 8.1 Avant de commencer (prérequis)

| Prérequis | Détail |
|---|---|
| Abonnement Azure | Droits suffisants pour créer un resource group et des role assignments (rôle *Owner*, ou *Contributor* + *User Access Administrator*, sur l'abonnement ou le resource group cible) |
| **Accès et quota Azure OpenAI** | L'abonnement doit avoir l'accès Azure OpenAI activé, avec du quota **GlobalStandard** disponible pour `gpt-4o` *et* `gpt-4o-mini` (capacité 10 chacun — `infra/resources.bicep`). Sans ce quota, `azd up` échoue à l'étape de création des déploiements de modèles. Demande/vérification : Azure OpenAI Studio → *Quotas*, ou https://aka.ms/oai/access |
| Région cible | Une région où ces déploiements **GlobalStandard** GPT-4o / GPT-4o-mini sont disponibles (ex. `swedencentral`, `eastus2`, `francecentral`) — vérifier la disponibilité courante dans la doc « Azure OpenAI Models » |
| Outils locaux | [Azure Developer CLI (`azd`)](https://aka.ms/azd), Azure CLI (`az`), Docker (utilisé par `azd` pour builder l'image — sinon ACR Tasks en repli), Git |

> Ces prérequis sont **au niveau de l'abonnement Azure**, indépendants du code
> de ce repo : aucune quantité de Bicep ne peut provisionner un quota qui n'a
> pas été accordé à l'abonnement.

### 8.2 Étape 1 — Authentification

```bash
azd auth login
```

Ouvre un navigateur pour l'authentification Microsoft Entra ID. Si le compte a
accès à plusieurs abonnements, vérifier/sélectionner le bon (`az account
show`, `az account set --subscription <id>`) avant l'étape suivante.

### 8.3 Étape 2 — Provisionner et déployer (`azd up`)

```bash
azd up
```

`azd up` = `azd provision` (infra) + `azd deploy` (application), en une seule
commande. Au premier lancement, `azd` pose deux questions :

| Invite | Exemple | Remarque |
|---|---|---|
| `Enter a new environment name` | `incident-rca-demo` | Préfixe des noms de ressources (`rg-incident-rca-demo`, etc.) — devient `AZURE_ENV_NAME` |
| `Select an Azure location` | `swedencentral` | **Doit supporter GPT-4o / GPT-4o-mini GlobalStandard** (§8.1) — devient `AZURE_LOCATION` |

(Si l'abonnement compte plusieurs souscriptions, `azd` demande également
laquelle utiliser.)

Déroulement (~10–15 minutes) :

1. **Provisioning** (`infra/main.bicep` → `infra/resources.bicep`, portée
   abonnement) : crée `rg-<environnement>` puis les 20 ressources — Log
   Analytics, Application Insights, identité managée, Container Registry,
   Azure OpenAI + déploiements `gpt-4o`/`gpt-4o-mini`, Azure AI Search, Cosmos
   DB (base `incidents` + conteneur `records`), Container Apps Environment et
   Container App (image placeholder) — ainsi que tous les role assignments
   RBAC (§8.6).
2. **Build** : `docker build` sur le `Dockerfile` multi-étapes (frontend React
   puis API FastAPI), ou build distant via ACR Tasks si Docker n'est pas
   disponible localement.
3. **Push** : l'image est poussée vers le Container Registry provisionné à
   l'étape précédente.
4. **Deploy** : nouvelle révision du Container App avec l'image réelle et les
   variables d'environnement injectées automatiquement (§8.6).

À la fin, `azd up` affiche l'URL publique (`SERVICE_API_URI`), par exemple :

```
https://api-xxxxxxxx.<region>.azurecontainerapps.io
```

### 8.4 Étape 3 — Vérifier le déploiement

1. Ouvrir `SERVICE_API_URI` dans un navigateur → l'UI React (`frontend/dist/`,
   servie par FastAPI) doit s'afficher.
2. `GET /api/health` → `{"status": "ok"}`.
3. `GET /api/meta` → `use_real_azure_openai: true` (les agents appellent
   désormais Azure OpenAI réel via `AzureOpenAIStructuredChatClient`, et non
   plus `StubChatClient`).
4. Dans l'UI, « Lancer le diagnostic » → le graphe d'orchestration s'anime en
   direct (SSE). Avec des modèles réels, les sorties (notamment les scores de
   `confiance`) peuvent différer du scénario figé — voir
   [`demo-guide.md`](demo-guide.md) « Variante : Azure OpenAI réel ».
5. À la porte de validation humaine, approuver/refuser depuis l'UI
   (`ApprovalCard`) comme décrit dans [`demo-guide.md`](demo-guide.md) §4.

### 8.5 Ressources provisionnées (`infra/resources.bicep`)

| Ressource | Type Azure | Rôle |
|-----------|------------|------|
| Log Analytics workspace | `Microsoft.OperationalInsights/workspaces` | logs du Container Apps Environment |
| Application Insights | `Microsoft.Insights/components` | observabilité : connection string injectée, OTel de l'Agent Framework câblé côté code (`src/observability.py`, §8.12) |
| Identité managée (user-assigned) | `Microsoft.ManagedIdentity/userAssignedIdentities` | identité du Container App, porteuse des role assignments |
| Container Registry | `Microsoft.ContainerRegistry/registries` (Basic) | images de l'API |
| Azure OpenAI / Microsoft Foundry | `Microsoft.CognitiveServices/accounts` (kind `AIServices`, sku `S0`, `allowProjectManagement: true`) | + 2 déploiements : `gpt-4o` (`2024-11-20`) et `gpt-4o-mini` (`2024-07-18`), sku `GlobalStandard` |
| Projet Microsoft Foundry | `Microsoft.CognitiveServices/accounts/projects` | sous-ressource du compte ci-dessus ; affiche l'orchestration `WorkflowBuilder` dans Observability > Traces une fois connecté à Application Insights (§8.12) |
| Azure AI Search | `Microsoft.Search/searchServices` (sku `basic`) | base de connaissances RAG (index vide à la création) |
| Azure Cosmos DB | `Microsoft.DocumentDB/databaseAccounts` (serverless) | base `incidents`, conteneur `records` (partition key `/id`) |
| Container Apps Environment | `Microsoft.App/managedEnvironments` | environnement d'exécution |
| Container App | `Microsoft.App/containerApps` | héberge l'API+UI, ingress externe port 8000, `azd-service-name: api` |

### 8.6 Sécurité : aucun secret en clair

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
(`AZURE_AUTH_MODE=cli`) vers les ressources réellement déployées (§8.7).

> `Microsoft.App/containerApps` est configuré avec `scale: {minReplicas: 1,
> maxReplicas: 1}` : `app.state.runs` (`src/api/runs.py`) est un registre en
> mémoire par processus — plusieurs réplicas casseraient la reprise HITL
> entre les deux appels SSE.

### 8.7 Développer en local contre les ressources déployées

```bash
azd env get-values >> .env   # AZURE_OPENAI_ENDPOINT, COSMOS_ENDPOINT, ...
az login                      # AZURE_AUTH_MODE=cli (défaut) -> AzureCliCredential
uvicorn src.api.app:app --reload
```

`KB_MODE` reste `local` par défaut même après `azd up` (§8.9).

### 8.8 Mettre à jour le déploiement après un changement de code

```bash
azd deploy   # rebuild + push + nouvelle révision du Container App (infra inchangée)
# si infra/*.bicep a changé :
azd up
```

### 8.9 (Optionnel) Basculer la base de connaissances vers Azure AI Search

L'index Azure AI Search est provisionné **vide** (§5) : `KB_MODE` reste
`local` après déploiement et l'app utilise `data/knowledge_base.json` embarqué
dans l'image. Pour activer la recherche RAG réelle :

1. Indexer `data/knowledge_base.json` dans l'index `incident-kb`
   (`AZURE_AI_SEARCH_ENDPOINT`, schéma `SPEC.md` §7) — **étape manuelle, aucun
   pipeline d'indexation dans le repo** (DECISIONS.md #22).
2. Basculer le Container App sur `KB_MODE=azure_search` :
   ```bash
   azd env set KB_MODE azure_search
   azd deploy
   ```
3. `get_knowledge_base()` (`src/tools/knowledge_base.py`) bascule
   automatiquement sur `AzureAISearchKnowledgeBase`.

Sans l'étape 1, `KBSearch` ne retournerait aucun précédent — c'est pourquoi
`KB_MODE` reste `local` par défaut après `azd up`.

### 8.10 Nettoyage

```bash
azd down            # supprime toutes les ressources de l'environnement (resource group inclus)
azd down --purge    # + purge définitive des ressources à suppression différée (Azure OpenAI, Cosmos DB)
```

### 8.11 Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `azd up` échoue sur `openAiChatDeployment` / `openAiChatDeploymentLight` (quota dépassé) | Pas de quota GlobalStandard pour GPT-4o/GPT-4o-mini dans la région choisie | Demander le quota dans Azure OpenAI Studio, ou choisir une autre région (§8.1) |
| `azd up` échoue avec `ServiceModelDeprecating: ... is in deprecating state and cannot be used for new deployments` | La version du modèle figée dans `infra/resources.bicep` a été dépréciée par Microsoft entre-temps | Consulter le [Model Retirement Schedule](https://learn.microsoft.com/azure/ai-foundry/openai/concepts/model-retirement-schedule) et mettre à jour `properties.model.version` (ex. `gpt-4o` `2024-08-06`/`2024-05-13` → `2024-11-20`) dans `infra/resources.bicep`, puis relancer `azd up` |
| `azd up` échoue sur `Microsoft.CognitiveServices/accounts` (accès refusé) | Accès Azure OpenAI non activé sur l'abonnement | Demander l'accès via https://aka.ms/oai/access |
| `azd up` échoue sur les role assignments (`AuthorizationFailed`) | Le compte n'a pas le rôle *User Access Administrator* (ou *Owner*) sur l'abonnement/resource group | Demander ce rôle, ou faire provisionner par un admin disposant des droits |
| `package-api` échoue avec `building image: signal: killed` pendant `npm run build` / `pip install` | `azd up` lance le build Docker **en parallèle** du provisioning (« Packaging overlaps with provisioning ») — sur une machine/conteneur avec peu de RAM, les deux ensemble déclenchent un OOM kill du build Docker | Relancer `azd provision` puis `azd deploy` séparément (séquentiel, pas de chevauchement), ou augmenter la mémoire allouée à Docker, ou relancer `azd up` (souvent transitoire / lié à l'état du cache) |
| L'UI se charge mais `POST /api/runs` échoue ou les agents lèvent une erreur | Déploiements Azure OpenAI pas encore complètement propagés | Attendre quelques minutes puis réessayer, vérifier `GET /api/meta` |
| `KBSearch` ne retourne aucun précédent malgré `KB_MODE=azure_search` | Index Azure AI Search vide (provisionné sans pipeline d'indexation) | Indexer `data/knowledge_base.json` (§8.9), ou revenir à `KB_MODE=local` |
| `azd up` échoue sur `foundryProject` avec `BadRequest: ... To create projects, you must enable a managed identity on your resource` (et un message générique "A resource with this name already exists or is in a conflicting state") | Le compte `openAi` (`kind: AIServices`) **et** le sous-projet `foundryProject` (`Microsoft.CognitiveServices/accounts/projects`) doivent chacun avoir leur propre identité managée pour `allowProjectManagement: true` (DECISIONS.md #26, #27) — sur un environnement neuf, le compte peut réussir (avec son identité) pendant que le projet échoue juste après faute de la sienne | Déjà corrigé dans `infra/resources.bicep` (`identity: { type: 'SystemAssigned' }` sur `openAi` **et** sur `foundryProject`) ; vérifier que le checkout inclut ces deux fixes (`git log` → commits "managed identity on the AIServices account" et "managed identity on the Foundry project") puis relancer `azd provision`/`azd up`. Si l'erreur "already exists" persiste avec un checkout à jour, vérifier dans le portail (compte `aoai-${resourceToken}` → onglet *Projects*) qu'il n'y a pas de `proj-${resourceToken}` resté en état `Failed`, et le supprimer avant de relancer |
| `azd up` échoue sur `Azure AI Services: aoai-${resourceToken}` ou sur le projet `proj-${resourceToken}` avec `FailedIdentityOperation: ... Status: 'Conflict'. ... is new, but resource already exists. This may be due to a pending delete operation, try again later` | Conflit transitoire côté fournisseur d'identités managées (MSI) lors de l'ajout d'une identité `SystemAssigned` à une ressource déjà existante (créée par un `azd up` précédent avant ce changement, sans identité) | Le bicep est correct (identité requise par `allowProjectManagement: true`, DECISIONS.md #26, #27) — c'est une erreur Azure transitoire. Solution rapide : portail → ressource concernée (`aoai-${resourceToken}` ou son projet) → **Identité** → **Affectée par le système** → **Activé** → Enregistrer, puis relancer `azd provision`/`azd up` (le bicep constatera que l'identité correspond déjà). Sinon, attendre quelques minutes (le temps que l'opération en attente côté Azure se termine) puis relancer `azd up` |
| `azd provision`/`azd up` échoue très rapidement (< 2s) sur le compte `aoai-${resourceToken}` (« Foundry: aoai-... ») avec `BadRequest: PublicNetworkAccess is required for this resouce` (et le message générique "already exists or in a conflicting state") | Avec `allowProjectManagement: true` et un sous-projet ayant sa propre identité (DECISIONS.md #25, #27), Azure exige que `properties.publicNetworkAccess` du compte soit explicitement renseigné — il ne peut plus rester implicite | Déjà corrigé dans `infra/resources.bicep` (`publicNetworkAccess: 'Enabled'` sur `openAi`, DECISIONS.md #28) ; vérifier que le checkout est à jour (`git log` → commit "managed identity on the Foundry project" ou plus récent) puis relancer `azd provision`/`azd up` |

### 8.12 Observabilité : tracer l'orchestration dans Microsoft Foundry

`src/observability.py` (`configure_observability`, appelée au démarrage de
`src.main` et `src.api.app`) câble l'instrumentation OpenTelemetry de l'Agent
Framework vers Application Insights :

```python
configure_azure_monitor(connection_string=settings.applicationinsights_connection_string)
enable_instrumentation(enable_sensitive_data=settings.enable_sensitive_data)
```

C'est un **no-op si `APPLICATIONINSIGHTS_CONNECTION_STRING` est vide** (mode
hors-ligne / `StubChatClient`) : aucune dépendance réseau n'est ajoutée à la
démo locale.

Après `azd up`, `APPLICATIONINSIGHTS_CONNECTION_STRING` est déjà injectée dans
le Container App (§8.5/§8.6). Chaque `workflow.run()` (les six agents, la
boucle de réflexion `RootCause <-> GatherEvidence`, la porte HITL
`HumanApproval`) émet alors des spans `workflow.run` / `executor.process <id>`
visibles dans Application Insights (Transaction search / Application map).

Pour les voir dans le **projet Microsoft Foundry** (`proj-${resourceToken}`,
provisionné par `infra/resources.bicep`, sortie `AZURE_FOUNDRY_PROJECT_NAME`),
connecter une fois la ressource Application Insights au projet — étape
manuelle, non codifiée en Bicep (DECISIONS.md #25) :

1. https://ai.azure.com → ouvrir le projet `proj-${resourceToken}`.
2. **Agents** (ou **Observability**) → **Traces** → **Connect**.
3. Sélectionner la ressource Application Insights existante (`appi-${resourceToken}`).

Les traces apparaissent ensuite dans **Observability > Traces** du projet,
avec un timeline par exécution montrant chaque agent, la boucle de réflexion
et la porte HITL.

> `ENABLE_SENSITIVE_DATA=true` (`.env`, dev uniquement) inclut les
> prompts/réponses des agents dans les traces — ne jamais l'activer en
> production (données potentiellement sensibles).

### 8.13 Rendre les agents visibles dans le projet Microsoft Foundry

§8.12 rend l'**exécution** (les traces) visible dans Foundry une fois Application
Insights connecté. `scripts/register_foundry_agents.py` complète cela en
enregistrant les **six agents** comme entrées dans l'onglet **Agents** du projet
Foundry (`proj-${resourceToken}`), pour qu'ils apparaissent par leur nom même
avant toute exécution.

Les agents tournent **hors de Foundry**, directement contre Azure OpenAI
(`AZURE_OPENAI_ENDPOINT`) via le Microsoft Agent Framework — il n'existe pas
d'exécution « native Foundry » dans cette démo. L'enregistrement utilise donc
`ExternalAgentDefinition` (`azure-ai-projects`) : *« Represents a third-party
agent hosted outside Foundry »*. C'est un enregistrement **metadata-only** —
aucune ressource de calcul n'est créée, seule l'entrée apparaît dans l'UI.

> Fonctionnalité **preview** d'`azure-ai-projects` (nécessite
> `AIProjectClient(..., allow_preview=True)`) : l'API peut changer avant la GA.

**Prérequis :**

1. `pip install -e ".[foundry]"` (groupe optionnel, séparé de `[dev]` — sans
   rapport avec l'exécution/les tests de la démo elle-même).
2. `AZURE_FOUNDRY_PROJECT_ENDPOINT` renseigné dans `.env` — déjà injecté après
   `azd up` via `azd env get-values >> .env` (§8.7), ou récupérable dans le
   portail Foundry (URL du projet).
3. Authentification Azure : `az login` (`AZURE_AUTH_MODE=cli`, défaut local) ou
   identité managée (`AZURE_AUTH_MODE=managed_identity`, déployé).

**Exécution (une fois, après chaque changement de nom/description d'agent) :**

```bash
python -m scripts.register_foundry_agents
```

Le script enregistre chaque agent sous son nom exact (`LogAnalyzer`,
`IncidentExtractor`, `KBSearch`, `RootCause`, `Remediation`, `Summary`) —
identique à l'`id` désormais stable passé à `as_agent()`
(`src/agents/clients.py`), ce qui garantit que les traces (§8.12, attribut de
span `gen_ai.agent.id`) se rattachent au bon agent enregistré dans Foundry.

Dans **https://ai.azure.com** → projet `proj-${resourceToken}` → **Agents**,
les six agents apparaissent avec leur description ; **Observability > Traces**
(§8.12) montre ensuite leurs exécutions une fois Application Insights connecté.

> Aucun « workflow » séparé n'est enregistré : le graphe d'orchestration
> (`WorkflowBuilder`, boucle de réflexion, porte HITL) est déjà entièrement
> visible comme timeline dans **Observability > Traces** (§8.12) — il n'existe
> pas de ressource « workflow » distincte côté Foundry à enregistrer.

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
