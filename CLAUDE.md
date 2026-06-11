# CLAUDE.md — Démo : système multi-agents d'analyse d'incidents (paiement)

> Ce fichier est lu automatiquement par Claude Code. Il décrit le projet, la stack,
> les conventions et les contraintes. La spécification fonctionnelle détaillée est
> dans `SPEC.md`. Le déroulé de démo est dans `scenario-demo-incident-paiement.md`.

## Objectif

Construire une **démo** d'un système multi-agents **orchestré** qui diagnostique un
incident sur un système de paiement : il ingère des logs, extrait l'incident, consulte
une base de connaissances, cherche la cause racine, propose une remédiation et rédige
un rapport. Le système doit être **déployable sur Azure** et s'appuyer sur le
**Microsoft Agent Framework**.

Ce qui doit transparaître dans la démo (priorité absolue) :
1. Des agents spécialisés, chacun avec une responsabilité unique et un contrat I/O clair.
2. Un **orchestrateur** qui pilote, garde l'état, et **décide** (reboucle si doute).
3. Une **boucle de réflexion** : si la confiance de la cause racine est sous le seuil,
   l'orchestrateur reboucle pour chercher plus de preuves au lieu de conclure.
4. Un **human-in-the-loop** : aucune remédiation n'est proposée/exécutée sans validation.

## Stack technique

- **Langage** : Python 3.11+.
- **Orchestration** : Microsoft Agent Framework (`pip install agent-framework` — préversion).
  - Agents : `ChatAgent` via `agent_framework.azure.AzureOpenAIChatClient`.
  - Workflow : `WorkflowBuilder` (graphe) pour gérer la boucle conditionnelle + le HITL.
- **Modèle** : Azure OpenAI / Microsoft Foundry (déploiement GPT-4o ou GPT-4.1).
- **Base de connaissances (RAG)** : Azure AI Search (vecteur + mots-clés). En local,
  démarrer avec `data/knowledge_base.json` puis basculer sur Azure AI Search.
- **Persistance (optionnelle pour la démo)** : Azure Cosmos DB.
- **Hébergement cible** : Azure Container Apps (API d'orchestration) ; UI minimale facultative.
- **Auth** : `AzureCliCredential` en local, `DefaultAzureCredential` / Managed Identity en déployé.
- **Observabilité** : télémétrie OpenTelemetry du framework → Application Insights.

## Arborescence attendue

```
.
├── CLAUDE.md                 # ce fichier
├── SPEC.md                   # spécification détaillée + contrats d'agents
├── scenario-demo-incident-paiement.md
├── .env.example
├── pyproject.toml
├── README.md
├── data/
│   ├── payment-incident.log  # logs d'exemple à injecter
│   └── knowledge_base.json   # incidents passés + runbooks
└── src/
    ├── agents/               # un module par agent (instructions + contrat)
    ├── orchestrator/         # graphe WorkflowBuilder, seuil, boucle, HITL
    ├── tools/                # outil de recherche KB (Azure AI Search)
    ├── models.py             # dataclasses / pydantic des contrats I/O
    └── main.py               # point d'entrée CLI de la démo
```

## Commandes

```bash
# Installation
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Connexion Azure (dev local)
az login

# Lancer la démo sur l'incident d'exemple
python -m src.main --logs data/payment-incident.log
```

## Conventions

- Chaque agent renvoie un **contrat JSON strict** (voir `SPEC.md` §4). Les agents ne
  se parlent jamais directement : tout passe par l'orchestrateur et le contexte partagé.
- Les sorties structurées sont validées (pydantic). Prompter les agents pour qu'ils
  renvoient **uniquement** du JSON, sans texte ni balises Markdown autour.
- Modèle « léger » pour l'extraction (tâche mécanique), modèle « fort » pour la cause racine.
- Code et identifiants en anglais ; commentaires en français acceptés.

## Contraintes à NE PAS contourner

- **Boucle bornée** : `MAX_REFLECTION_LOOPS` (défaut 2). Jamais de boucle infinie.
- **Seuil de confiance** : `CONFIDENCE_THRESHOLD` (défaut 0.75). Sous le seuil → reboucle.
- **HITL obligatoire** : l'étape de remédiation est derrière une approbation humaine
  (`@tool(approval_mode="always_require")` ou `ctx.request_info()`), même en démo.
- **Pas d'exécution réelle** d'action correctrice : la remédiation est *proposée*, pas
  appliquée sur un vrai système. La démo se contente d'afficher le plan après approbation.
- **Pas de secrets en clair** : tout via `.env` / variables d'environnement / Key Vault.

## Références (à consulter via la doc, ne pas deviner les API)

- Agent Framework — vue d'ensemble : https://learn.microsoft.com/agent-framework/overview/
- Orchestrations de workflows : https://learn.microsoft.com/agent-framework/workflows/orchestrations/
- Human-in-the-loop : https://learn.microsoft.com/agent-framework/workflows/human-in-the-loop
- Orchestration séquentielle + HITL : https://learn.microsoft.com/agent-framework/workflows/orchestrations/sequential
- Archi de référence Azure (multi-agents) : https://learn.microsoft.com/azure/architecture/ai-ml/idea/multiple-agent-workflow-automation
- Patterns d'orchestration d'agents : https://learn.microsoft.com/azure/architecture/ai-ml/guide/ai-agent-design-patterns
