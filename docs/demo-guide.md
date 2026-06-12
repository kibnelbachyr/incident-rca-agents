# Guide de démo

> Déroulé pratique — commandes et sorties attendues, pour le CLI et l'UI web,
> avec les valeurs concrètes du scénario fourni (`data/payment-incident.log`
> + `data/knowledge_base.json`). Pour le **script de présentation** (message
> à faire passer, minutage, phrases d'accroche), voir
> `scenario-demo-incident-paiement.md`. Pour l'architecture, voir
> [`architecture.md`](architecture.md) / [`how-it-works.md`](how-it-works.md).

## 1. Le message à faire passer

Trois choses, dans l'ordre :

1. **Décomposition** — chaque agent a une responsabilité unique ; on inspecte
   l'artefact produit à chaque étape (pas « un gros prompt »).
2. **Orchestration vivante** — face à un doute (confiance < seuil),
   l'orchestrateur **reboucle** pour chercher plus de preuves au lieu de
   conclure.
3. **Sécurité par conception** — sur un système de paiement, aucune action
   corrective n'est exécutée sans **validation humaine**.

## 2. Préparation

Mode hors-ligne (par défaut, sans identifiants Azure — voir
[`deployment.md`](deployment.md) §1) :

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

L'incident de démo (`data/payment-incident.log`) est **volontairement
ambigu** : un déploiement (`payment-api v2.4.1`, 14:00) réduit
`db.max_pool_size` de 40 à 20, ce qui sature le pool de connexions à partir
de 14:22 et fait passer le taux d'échec de paiement de 0,18 % à 38 % à
14:24. En parallèle, la latence de l'appel Stripe est légèrement élevée
(780-820ms vs 600ms p95) — une fausse piste plausible. La base de
connaissances (`data/knowledge_base.json`) contient deux précédents :
`INC-204` (épuisement de pool après changement de config) et `INC-187` (pic
de latence Stripe).

Avec `StubChatClient` (mode hors-ligne), les réponses sont **déterministes**
et reproduisent exactement ce scénario, y compris la boucle de réflexion
(`RootCause` : confiance 0.55 puis 0.88).

## 3. Déroulé — CLI

```bash
python -m src.main --logs data/payment-incident.log
```

### En-tête

```
==============================================================================
DEMO - Diagnostic multi-agents d'un incident de paiement
==============================================================================
Logs source           : data/payment-incident.log
Seuil de confiance    : 0.75
Boucles de reflexion max : 2
Base de connaissances : local
Modeles               : StubChatClient (hors ligne)
```

### Agent 1/6 — LogAnalyzer

```
Timeline reconstituee :
  - 14:00:11  Deploiement de payment-api v2.4.1 en production (rolling, 6 pods)
  - 14:00:12  Application de la config db.max_pool_size=20 (precedemment 40)
  - 14:22:47  Pool de connexions DB sature a 100% (20/20), aucune connexion libre
  - 14:23:15  Premiers connection acquisition timeout apres 5000ms
  - 14:24:50  Taux d'erreur a 38% sur 60s - candidat SEV
  - 14:26:30  Tempete de retries clients : trafic entrant x3.4 vs normal
Anomalies detectees :
  - Utilisation du pool de connexions DB passe de 70% a 100% en 6 minutes (14:16-14:22)
  - Taux d'erreur de paiement passe de 0,18% a 38% en moins de 25 minutes
  - Tempete de retries cote client qui amplifie la charge sur un pool deja sature
Evenements correles :
  - Le deploiement v2.4.1 (14:00:11) precede la saturation du pool (14:22:47) d'environ 22 minutes
  - La modification de db.max_pool_size a ete appliquee au moment exact du deploiement
```

> *« Premier agent : il transforme du bruit en signal — il a déjà repéré le
> déploiement à 14h00 et la saturation du pool. »*

### Agent 2/6 — IncidentExtractor

```
Titre     : Pic d'echecs de paiement
Severite  : SEV-1
Services  : payment-api, db-pool
Fenetre   : 14:23 -> en cours
Symptomes :
  - echec de persistance des transactions (no DB connection)
  - pool de connexions DB sature a 100%
  - tempete de retries cote client amplifiant la charge
```

> *« Le contrat JSON que les agents suivants vont consommer — pas du texte
> libre. »*

### Agent 3/6 — KBSearch

```
Precedents trouves :
  - INC-204  (similarite=0.82)
    -> resolution : Rollback du deploiement et restauration de db.max_pool_size a 40 ; ajout d'une alerte sur l'utilisation du pool de connexions.
  - INC-187  (similarite=0.61)
    -> resolution : Mise en place d'un circuit breaker et de retries avec backoff sur les appels au processeur de paiement externe (Stripe).
```

> *« Deux précédents qui collent tous les deux. Ambiguïté. »*

### Agent 4/6 — RootCause (1er passage)

```
Cause retenue : Deux hypotheses concurrentes : (a) la reduction de db.max_pool_size par le deploiement v2.4.1, (b) une degradation de la latence du processeur de paiement Stripe
Raisonnement  : La saturation du pool de connexions DB et la hausse de la latence Stripe sont toutes deux correlees temporellement avec le pic du taux d'erreur a 14:24. Les precedents INC-204 (config pool) et INC-187 (latence Stripe) collent tous les deux au profil de symptomes observe. Aucune preuve definitive ne permet encore de departager ces deux pistes.
Confiance     : 0.55  (seuil = 0.75)
-> Confiance sous le seuil : l'orchestrateur reboucle pour chercher des preuves (passage 1/2).
Preuves manquantes a collecter :
  - Diff de configuration du deploiement v2.4.1 : valeur de db.max_pool_size avant/apres
  - Evolution de la latence Stripe apres 14:26 (retour a la normale ou degradation persistante)
```

### ⭐ Moment fort n°1 — la boucle de réflexion

> *« Regardez : l'orchestrateur refuse d'aller plus loin avec un doute (0.55
> < 0.75). Il décide de chercher plus de preuves. »*

### Boucle de réflexion — GatherEvidence

```
Reboucle 1/2 : LogAnalyzer et KBSearch re-sollicites.
Nouveaux evenements correles :
  - Le retour a la normale de la latence Stripe (14:29) ne coincide pas avec la fin de l'incident : Stripe n'explique pas la duree de la saturation
  - La reduction de db.max_pool_size coincide exactement avec l'horodatage du deploiement v2.4.1 (14:00:11-12)
Base de connaissances reconfrontee : INC-204, INC-187
```

### Agent 4/6 — RootCause (2e passage)

```
Cause retenue : Le deploiement payment-api v2.4.1 a reduit db.max_pool_size de 40 a 20, saturant le pool de connexions DB sous la charge nominale
Raisonnement  : Le diff de deploiement confirme la reduction de db.max_pool_size de 40 a 20, appliquee exactement au moment du deploiement (14:00:11-12). Le pool atteint 100% d'utilisation 22 minutes plus tard et les echecs de persistance demarrent immediatement apres. La latence Stripe, elevee un court instant (780-820ms), est revenue a la normale (640ms) des 14:29 alors que la saturation du pool persistait : elle n'explique donc pas la duree ni la severite de l'incident. Cette piste est ecartee.
Confiance     : 0.88  (seuil = 0.75)
-> Confiance suffisante : l'orchestrateur passe a la validation humaine.
```

> *« Cette fois c'est tranché : Stripe était une fausse piste. La vraie
> cause, c'est le déploiement. Confiance 0,88, on avance. »*

### ⭐ Moment fort n°2 — validation humaine

```
==============================================================================
Validation humaine requise avant remediation
==============================================================================
Incident       : Pic d'echecs de paiement (SEV-1)
Services       : payment-api, db-pool
Cause retenue  : Le deploiement payment-api v2.4.1 a reduit db.max_pool_size de 40 a 20, saturant le pool de connexions DB sous la charge nominale
Confiance      : 0.88
Precedents lies : INC-204, INC-187

<message de l'orchestrateur decrivant la demande de validation>
Rappel : la remediation reste un plan affiche, aucune action n'est executee (CLAUDE.md).
Approuver le passage a la remediation ? [o/N] :
```

> *« On est sur du paiement : rien ne s'exécute sans qu'un humain valide.
> L'orchestrateur attend mon feu vert. »*

Taper `o` (ou `oui`/`y`/`yes`) pour approuver.

### Agent 5/6 — Remediation (affiché seulement si approuvé)

```
Immediat :
  - Rollback de payment-api vers v2.4.0 (ou remonter db.max_pool_size a 40 sans rollback complet)
Court terme :
  - Ajouter un timeout d'acquisition de connexion explicite et le journaliser
  - Ajouter une alerte a 80% d'utilisation du pool de connexions DB
Long terme :
  - Mettre en place une porte de revue (gate) obligatoire sur les changements de configuration infra avant deploiement
```

### Agent 6/6 — Summary

```
INCIDENT SEV-1 — Pic d'échecs de paiement
Fenêtre : 14:23 → 14:41 (résolu)   Impact : 38% des transactions en échec

CAUSE RACINE (confiance 0,88)
Le déploiement payment-api v2.4.1 a réduit max_pool_size de 40 à 20.
Le pool s'est saturé à 14:23, empêchant la persistance des transactions.
La latence Stripe observée était dans la normale (fausse piste écartée).

REMÉDIATION
1. Rollback v2.4.1 (appliqué après validation)
2. Timeout d'acquisition + alerte à 80% du pool
3. Gate de revue sur les changements de config infra

PRÉCÉDENT LIÉ : INC-204 (même schéma, même résolution)
```

```
==============================================================================
FIN
==============================================================================
Demo terminee : rapport final affiche ci-dessus.
```

> *« Et voilà le livrable : un rapport qu'on peut coller tel quel dans le
> post-mortem. »*

## 4. Déroulé — UI web (FastAPI + React)

```bash
# Terminal 1
uvicorn src.api.app:app --reload
# Terminal 2
cd frontend && npm run dev
```

Ouvrir http://localhost:5173.

1. **En-tête** (`Header`) : badges de configuration tirés de `/api/meta` —
   « seuil confiance 0.75 », « boucles max 2 », « KB local », « mode
   hors-ligne (stub) », « persistance locale ».
2. Cliquer **« Lancer le diagnostic »** → `POST /api/runs` (SSE).
   `TopologyGraph` commence à animer le graphe à 8 nœuds.
3. Au fil des événements `step`, une `StepCard` apparaît pour chaque agent,
   avec le **même contenu** que le CLI mais en composants visuels :
   - `LogAnalyzer` → timeline + anomalies + corrélations (3 colonnes).
   - `IncidentExtractor` → fiche incident (titre, sévérité `SEV-1` avec
     badge coloré, services, symptômes).
   - `KBSearch` → cartes `INC-204` (similarité 0.82) / `INC-187` (0.61) avec
     leur résolution.
   - `RootCause` (1er passage) → cause, raisonnement, **`ConfidenceBar`**
     (0.55 < seuil 0.75, barre rouge), message « confiance sous le seuil :
     l'orchestrateur reboucle (passage 1/2) » + liste des preuves
     manquantes.
   - `GatherEvidence` → « Reboucle 1/2 : Log Analyzer et KB Search
     re-sollicités », nouveaux événements corrélés, précédents
     reconfrontés.
   - `RootCause` (2e passage) → `ConfidenceBar` à 0.88 (verte, ≥ seuil),
     « confiance suffisante : passage à la validation humaine ».
4. **`ApprovalCard`** s'affiche (porte HITL) : incident, services, cause
   retenue, précédents liés, `ConfidenceBar`, rappel « la remédiation reste
   un plan affiché ; aucune action n'est exécutée sur un système réel », et
   deux boutons **Refuser** / **Approuver la remédiation**.
5. Cliquer **« Approuver la remédiation »** → `POST
   /api/runs/{run_id}/approval` (`{"approved": true}`). Deux nouvelles
   `StepCard` apparaissent :
   - `Remediation` → grille 3 colonnes (Immédiat / Court terme / Long terme).
   - `Summary` → le rapport final (`texte`) dans un bloc `<pre>`.
6. Statut final : « Terminé — remédiation approuvée, rapport ci-dessus. »
7. Onglet **« Historique »** : la table liste l'exécution qui vient de se
   terminer (date, titre, sévérité `SEV-1`, cause, confiance 0.88, badge
   « approuvée »). Cliquer une ligne ouvre le détail
   (`GET /api/history/{run_id}`) : incident, cause racine + jauge, plan de
   remédiation, rapport final.

## 5. Variante : refus de la remédiation

À l'étape HITL :

- **CLI** : répondre autre chose que `o`/`oui`/`y`/`yes` (ou EOF) à
  `Approuver le passage a la remediation ? [o/N] :`.
- **UI** : cliquer **« Refuser »**.

Dans les deux cas :

- Aucun `RemediationPlan` ni `IncidentReport` n'est généré ni affiché.
- **CLI** : message final « Demo terminee : remediation non executee (refus
  humain). »
- **UI** : une `StepCard` « Validation humaine : remédiation refusée »
  s'affiche (« L'humain a refusé la remédiation : le workflow s'arrête ici.
  Aucun plan de remédiation n'est généré ni affiché. »), puis statut «
  Terminé — remédiation refusée par l'humain. » L'historique enregistre
  l'exécution avec le badge « refusée » et `context.approved === false` ;
  sa vue détail n'affiche ni plan ni rapport.

## 6. Variante : Azure OpenAI réel

Après avoir suivi [`deployment.md`](deployment.md) §4 (`az login` +
`AZURE_OPENAI_ENDPOINT` réel dans `.env`), relancer le CLI ou l'UI : le
badge « mode hors-ligne (stub) » devient « Azure OpenAI ».

Le déroulé reste **structurellement identique** (mêmes 6 agents, mêmes
contrats JSON, même topologie), mais avec des modèles réels :

- Les **valeurs exactes** (texte du raisonnement, scores de `confiance`,
  libellés de remédiation) ne sont **plus garanties identiques** au scénario
  figé ci-dessus.
- Il est possible que le **1er passage de `RootCause` dépasse déjà
  0.75** — dans ce cas, la boucle `GatherEvidence` **ne se déclenche pas** :
  c'est un comportement correct de l'orchestrateur (la condition
  `needs_more_evidence` n'est qu'une fonction du score retourné), mais cela
  change le déroulé de la démo (pas de « moment fort n°1 »).
- À l'inverse, si la confiance reste basse après
  `MAX_REFLECTION_LOOPS` tours, l'orchestrateur passe quand même à la
  validation humaine (`Default`) — la boucle ne bloque jamais
  indéfiniment.

> Pour une démo **reproductible** (présentation, atelier), privilégier le
> mode hors-ligne (`StubChatClient`) qui garantit le scénario 0.55 → 0.88
> décrit ci-dessus.

## 7. Dépannage

| Symptôme | Cause probable | Solution |
|----------|------------------|----------|
| `AZURE_OPENAI_ENDPOINT` défini mais le stub est quand même utilisé | l'endpoint est encore le placeholder `https://<...>` de `.env.example` | renseigner un endpoint réel (`Settings.use_real_azure_openai` vérifie le préfixe `https://<`) |
| L'UI affiche « Aucune exécution enregistrée » dans l'historique | pas encore d'exécution **terminée** (approuvée ou refusée) | terminer au moins une exécution jusqu'à `done` |
| `npm run dev` ne trouve pas `/api/*` | l'API (`uvicorn`) n'est pas démarrée sur le port 8000 | démarrer `uvicorn src.api.app:app --reload` (le proxy Vite cible `127.0.0.1:8000`) |
| Le graphe `TopologyGraph` ne montre pas le passage par `human_approval` après approbation | comportement attendu (`DECISIONS.md` #19) : ce nœud n'émet un `step` qu'en cas de **refus** ; en cas d'approbation, le passage est déduit de la présence d'un `step` `remediation` | aucune action requise |
| `KB_MODE=azure_search` mais `KBSearch` ne retourne aucun précédent | l'index Azure AI Search provisionné par `azd up` est **vide** (pas de pipeline d'indexation) | indexer `data/knowledge_base.json` (voir [`deployment.md`](deployment.md) §5) ou repasser `KB_MODE=local` |
