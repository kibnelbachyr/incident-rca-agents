# SPEC.md — Spécification détaillée

Démo : analyse et debug d'incidents de paiement par agents IA orchestrés, sur
Microsoft Agent Framework + Azure. Lire `CLAUDE.md` d'abord (stack, conventions,
contraintes). Le déroulé de présentation est dans `scenario-demo-incident-paiement.md`.

---

## 1. Objectif & périmètre

**But.** À partir de logs bruts d'un système de paiement, produire automatiquement :
un incident structuré, des précédents similaires, une hypothèse de cause racine avec
confiance, un plan de remédiation (proposé, validé par un humain), et un rapport final.

**Hors périmètre.** Aucune action n'est exécutée sur un vrai système ; la remédiation
est un plan affiché. Pas d'ingestion temps réel ; on injecte un fichier de logs.

---

## 2. Architecture

Six agents spécialisés, un orchestrateur, une base de connaissances comme ressource.

| # | Agent | Rôle | Modèle suggéré |
|---|-------|------|----------------|
| 1 | `LogAnalyzer` | Normalise les logs, détecte anomalies + timeline | léger (ex. GPT-4o-mini) |
| 2 | `IncidentExtractor` | Produit l'objet incident structuré | léger |
| 3 | `KBSearch` | Interroge la base de connaissances (RAG) | léger |
| 4 | `RootCause` | Hypothèse de cause racine + score de confiance | fort (GPT-4o) |
| 5 | `Remediation` | Plan de mitigation + correctif (derrière HITL) | fort |
| 6 | `Summary` | Rédige le rapport d'incident final | léger |

L'**orchestrateur** détient le contexte partagé (l'objet incident qui grossit),
séquence les agents, applique la boucle de réflexion et la porte de validation.
Les agents sont sans état : ils reçoivent le contexte, font leur tâche, renvoient
un JSON. Ils ne communiquent jamais entre eux.

---

## 3. Stack & dépendances

- `agent-framework` (préversion) — `WorkflowBuilder`, `ChatAgent`, HITL request/response.
- `agent_framework.azure.AzureOpenAIChatClient` — client modèle.
- `azure-identity` — `AzureCliCredential` (local) / `DefaultAzureCredential` (déployé).
- `azure-search-documents` — accès Azure AI Search (agent KB en mode déployé).
- `pydantic` — validation des contrats I/O.

Création d'un agent (pattern officiel, à adapter par agent) :

```python
import os
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import AzureCliCredential

client = AzureOpenAIChatClient(
    endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    model=os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"],
    credential=AzureCliCredential(),
)

root_cause_agent = client.create_agent(
    name="RootCause",
    instructions=ROOT_CAUSE_INSTRUCTIONS,  # voir §4
    temperature=0.2,
)
```

---

## 4. Contrats de données entre agents

Tous les agents renvoient **uniquement** du JSON valide (pas de Markdown autour).
Les schémas sont validés par pydantic dans `src/models.py`.

**1 — LogAnalyzer** → `LogAnalysis`
```json
{
  "timeline": [{"time": "14:00:11", "event": "deploy payment-api v2.4.1"}],
  "anomalies": ["pool saturé à 14:23", "taux d'erreur 0,2% → 38%"],
  "correlated_events": ["déploiement v2.4.1 ~20 min avant la saturation"]
}
```

**2 — IncidentExtractor** → `Incident`
```json
{
  "titre": "Pic d'échecs de paiement",
  "severite": "SEV-1",
  "services": ["payment-api", "db-pool"],
  "fenetre": "14:23 → en cours",
  "symptomes": ["échec de persistance des transactions", "pool saturé", "retry storm"]
}
```

**3 — KBSearch** → `KBMatches`
```json
{
  "matches": [
    {"id": "INC-204", "similarite": 0.82, "resolution": "rollback + pool à 40"},
    {"id": "INC-187", "similarite": 0.61, "resolution": "circuit breaker Stripe"}
  ]
}
```

**4 — RootCause** → `RootCauseHypothesis`
```json
{
  "cause": "Le déploiement v2.4.1 a réduit max_pool_size de 40 à 20",
  "raisonnement": "La saturation suit le déploiement ; latence Stripe dans la normale",
  "confiance": 0.88,
  "preuves_manquantes": []
}
```
- `confiance` ∈ [0,1]. Si `< CONFIDENCE_THRESHOLD`, remplir `preuves_manquantes`
  (ce que l'orchestrateur doit aller chercher au prochain tour).

**5 — Remediation** → `RemediationPlan` (produit après approbation humaine)
```json
{
  "immediat": ["rollback v2.4.1 ou remonter max_pool_size à 40"],
  "court_terme": ["timeout d'acquisition", "alerte à 80% du pool"],
  "long_terme": ["gate de revue sur les changements de config infra"]
}
```

**6 — Summary** → `IncidentReport` (texte formaté + champs clés ; voir scénario §5).

---

## 5. Comportement d'orchestration

Implémenter avec `WorkflowBuilder` (graphe d'exécuteurs). Chaque exécuteur enveloppe
un agent et met à jour le contexte partagé.

Topologie :

```
logs → LogAnalyzer → IncidentExtractor → KBSearch → RootCause → [décision confiance]
                                                          ▲                │
                              (preuves manquantes ciblées)│                │ confiance ≥ seuil
                                          GatherEvidence ──┘                ▼
                                                              [HITL: validation humaine]
                                                                           │ approuvé
                                                                           ▼
                                                              Remediation → Summary → rapport
```

**Boucle de réflexion (arête conditionnelle après `RootCause`)**
- Si `confiance < CONFIDENCE_THRESHOLD` ET `loop_count < MAX_REFLECTION_LOOPS` :
  router vers `GatherEvidence` (re-sollicite `LogAnalyzer` sur les `preuves_manquantes`
  et/ou `KBSearch`), incrémenter `loop_count`, repasser dans `RootCause`.
- Sinon : continuer vers la porte de validation.
- La boucle est **bornée** par `MAX_REFLECTION_LOOPS` (jamais infinie).

**Porte de validation (HITL avant remédiation)**
- L'outil qui déclenche la remédiation est marqué `@tool(approval_mode="always_require")`,
  ou bien un nœud `ctx.request_info()` émet un `RequestInfoEvent` que l'appelant
  doit approuver avant de continuer.
- Tant que l'humain n'a pas approuvé, le workflow reste en pause.

Exécution en streaming pour voir chaque étape (et la pause HITL) :

```python
async for event in workflow.run_stream(message=raw_logs):
    # afficher la progression : sortie de chaque agent, décision de boucle, demande d'appro
    handle(event)  # gère RequestInfoEvent → demande l'approbation à l'utilisateur
```

---

## 6. Données de démo (fournies)

- `data/payment-incident.log` — incident volontairement **ambigu** : saturation du
  pool DB après le déploiement v2.4.1, plus une latence Stripe légèrement élevée
  (fausse piste). C'est ce qui déclenche la boucle de réflexion : 1er passage de
  `RootCause` en confiance basse, 2e passage tranché après preuves supplémentaires.
- `data/knowledge_base.json` — deux précédents : `INC-204` (config pool) et
  `INC-187` (latence Stripe).

Tuning attendu pour que la démo « joue » :
- 1er passage `RootCause` : confiance ≈ 0,55 (deux hypothèses plausibles) → reboucle.
- 2e passage : confiance ≈ 0,88, cause = changement de `max_pool_size`.

---

## 7. Déploiement Azure

Architecture de référence (alignée sur la doc Microsoft) :

| Composant | Service Azure | Rôle |
|-----------|---------------|------|
| Modèle LLM | Azure OpenAI / Microsoft Foundry (GPT-4o) | raisonnement des agents |
| Base de connaissances | Azure AI Search | RAG sur incidents passés + runbooks |
| API d'orchestration | Azure Container Apps | héberge l'orchestrateur |
| Persistance (option) | Azure Cosmos DB | incidents, décisions, historique |
| Images | Azure Container Registry | images versionnées |
| Observabilité | Application Insights | traces OpenTelemetry du framework |
| Secrets | Azure Key Vault | clés, endpoints |

Étapes (haut niveau) :
1. Provisionner Azure OpenAI + déployer un modèle (noter le nom du déploiement).
2. Créer un index Azure AI Search et y charger `knowledge_base.json` (vectorisé).
3. Conteneuriser l'API d'orchestration → push vers Container Registry.
4. Déployer sur Container Apps avec Managed Identity (`DefaultAzureCredential`).
5. Connecter Application Insights pour la télémétrie.

Variables d'environnement : voir `.env.example`.

---

## 8. Critères d'acceptation

La démo est validée si, sur `data/payment-incident.log` :

1. `IncidentExtractor` produit un incident SEV-1 ciblant `payment-api` / `db-pool`.
2. `KBSearch` ramène **deux** précédents (`INC-204` et `INC-187`).
3. Le **1er passage** de `RootCause` sort une confiance **< 0,75** → l'orchestrateur
   **reboucle** (l'événement est visible dans le flux/les traces).
4. Le **2e passage** sort une confiance **≥ 0,75** et désigne le changement de
   `max_pool_size` comme cause (la latence Stripe est écartée).
5. Le workflow **se met en pause** pour validation humaine avant la remédiation
   (`RequestInfoEvent` / approbation de tool).
6. Après approbation, un `RemediationPlan` puis un rapport final sont produits.
7. Chaque sortie d'agent est observable (streaming d'événements).
8. La boucle ne dépasse jamais `MAX_REFLECTION_LOOPS`.

---

## 9. Étapes de réalisation suggérées (pour Claude Code)

1. Squelette du repo + `pyproject.toml` + `models.py` (contrats pydantic).
2. Les 6 agents avec leurs instructions (sorties JSON strictes), testés isolément
   sur des entrées factices.
3. Outil KB en mode local (`knowledge_base.json`) ; interface prête pour Azure AI Search.
4. Graphe `WorkflowBuilder` : séquence + arête conditionnelle (boucle) + nœud HITL.
5. CLI `src/main.py` qui injecte le log, streame les événements, gère l'approbation.
6. Vérifier les 8 critères d'acceptation sur l'incident d'exemple.
7. Conteneurisation + bascule KB vers Azure AI Search + variables Azure.

---

## 10. Références

- Agent Framework : https://learn.microsoft.com/agent-framework/overview/
- Workflows / orchestrations : https://learn.microsoft.com/agent-framework/workflows/orchestrations/
- Human-in-the-loop : https://learn.microsoft.com/agent-framework/workflows/human-in-the-loop
- Séquentiel + HITL : https://learn.microsoft.com/agent-framework/workflows/orchestrations/sequential
- Archi multi-agents Azure : https://learn.microsoft.com/azure/architecture/ai-ml/idea/multiple-agent-workflow-automation
- Patterns d'orchestration : https://learn.microsoft.com/azure/architecture/ai-ml/guide/ai-agent-design-patterns
- Azure AI Search (RAG) : https://learn.microsoft.com/azure/search/
