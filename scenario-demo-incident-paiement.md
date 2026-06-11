# Scénario de démo — Système multi-agents d'analyse d'incidents (paiement)

> Durée cible : 6–8 min. Objectif : prouver que ce n'est pas « un gros prompt »,
> mais un **orchestrateur** qui pilote des agents spécialisés, garde l'état,
> et **décide** (reboucler, demander une validation) au lieu d'enchaîner bêtement.

---

## 1. Le message à faire passer

Trois choses, dans l'ordre, que le public doit retenir :

1. **Décomposition** — chaque agent a une responsabilité unique ; on inspecte l'artefact produit à chaque étape.
2. **Orchestration vivante** — l'orchestrateur ne suit pas un tapis roulant : face à un doute, il *reboucle* pour chercher plus de preuves.
3. **Sécurité par conception** — sur un système de paiement, aucune action corrective n'est exécutée sans **validation humaine**.

La phrase d'accroche : *« On va regarder un agent IA diagnostiquer une panne de paiement comme le ferait un ingénieur d'astreinte — sauf qu'il montre son raisonnement à chaque étape. »*

---

## 2. L'incident mis en scène

Un incident volontairement **ambigu au premier coup d'œil** : deux causes plausibles
se chevauchent, ce qui justifie la boucle de réflexion.

**Contexte.** Plateforme de paiement e-commerce. À 14h24, le taux d'échec des
transactions passe de 0,2 % à 38 %. Les clients ne peuvent plus finaliser leur panier.

**Timeline réelle (que l'agent doit reconstituer) :**

| Heure  | Événement |
|--------|-----------|
| 14:00  | Déploiement `payment-api v2.4.1` |
| 14:18  | Pool de connexions DB à 85 % d'utilisation |
| 14:23  | Premiers `connection acquisition timeout` |
| 14:24  | Taux d'échec 0,2 % → 38 % ; transactions marquées `FAILED` |
| 14:26  | Les retries clients amplifient la charge (cascade) |

**Le piège.** En parallèle, la latence du processeur externe (Stripe) est légèrement
élevée. Un humain pressé conclurait « c'est Stripe ». La vraie cause est ailleurs :
le déploiement `v2.4.1` a réduit `max_pool_size` de **40 à 20**, ce qui épuise le pool.

**Extrait de logs injecté (raccourci pour la démo) :**

```
14:00:11 INFO  [deploy]     payment-api v2.4.1 released
14:18:02 WARN  [db-pool]    pool usage 85% (17/20)
14:22:47 WARN  [db-pool]    pool usage 100% (20/20)
14:23:15 ERROR [db-pool]    connection acquisition timeout after 5000ms
14:23:15 ERROR [payment-api] tx_9921 persist failed: no DB connection
14:23:16 ERROR [payment-api] tx_9921 marked FAILED
14:24:01 WARN  [processor]  stripe call latency 820ms (p95 baseline 600ms)
14:26:30 WARN  [payment-api] retry storm detected: 3.4x normal inbound
```

---

## 3. Préparation (avant de lancer)

- Écran partagé sur le schéma d'orchestration (l'orchestrateur au centre, les 6 agents).
- Le fichier de logs ci-dessus prêt à être injecté.
- Le seuil de confiance de l'orchestrateur réglé à **0,75** (au-dessus, on continue ; en-dessous, on reboucle).
- La base de connaissances pré-remplie avec deux incidents passés :
  - `INC-204` — épuisement de pool après changement de config → *résolu par rollback + remise du pool à 40*.
  - `INC-187` — pic de latence Stripe → *résolu par circuit breaker*.

---

## 4. Déroulé pas à pas

Pour chaque étape : **ce qui se passe**, **la sortie de l'agent**, **ce que tu dis**.

### Étape 0 — L'orchestrateur reçoit les logs

L'orchestrateur initialise le **contexte partagé** (l'objet incident, vide) et va
appeler les agents un par un.

> *« Je colle les logs bruts. À partir de maintenant, c'est l'orchestrateur qui pilote — les agents ne se parlent jamais entre eux, ils répondent à l'orchestrateur. »*

### Étape 1 — Agent d'analyse des logs

Sortie : une timeline normalisée + anomalies détectées (saut du taux d'erreur,
saturation du pool, corrélation avec le déploiement de 14h00).

> *« Premier agent : il transforme du bruit en signal. Notez qu'il a déjà repéré le déploiement à 14h00 et la saturation du pool. »*

### Étape 2 — Agent d'extraction d'incident

Sortie (objet structuré) :

```json
{
  "titre": "Pic d'échecs de paiement",
  "severite": "SEV-1",
  "services": ["payment-api", "db-pool"],
  "fenetre": "14:23 → en cours",
  "symptomes": ["échec persistance tx", "pool saturé", "retry storm"]
}
```

> *« Le deuxième agent range tout ça en un objet exploitable. C'est ce contrat JSON que les agents suivants vont consommer — pas du texte libre. »*

### Étape 3 — Agent de recherche dans la base de connaissances

L'orchestrateur passe l'incident à l'agent KB, qui interroge la mémoire.

Sortie : **deux** incidents candidats — `INC-204` (changement de config pool) et
`INC-187` (latence Stripe). Les deux ressemblent au cas présent.

> *« Il ramène deux précédents. Et c'est là que ça devient intéressant : les deux collent. On a une ambiguïté. »*

### Étape 4 — Agent de cause racine — **premier passage**

Sortie : deux hypothèses concurrentes (changement de pool *vs* latence Stripe),
**confiance = 0,55**.

> *« L'agent est honnête : il hésite, confiance 0,55. Et c'est le moment clé… »*

### ⭐ Moment fort n°1 — La boucle de réflexion

La confiance (0,55) est **sous le seuil (0,75)**. L'orchestrateur **ne continue pas** :
il reboucle. Il redemande à l'agent logs une donnée ciblée (temps de rétention des
connexions + diff du déploiement) et reconfronte à la KB.

> *« Regardez : l'orchestrateur refuse d'aller plus loin avec un doute. Il décide de chercher plus de preuves. C'est ça, l'orchestration — pas un tapis roulant, une décision. »*

### Étape 4bis — Agent de cause racine — **second passage**

Avec les nouvelles preuves : le déploiement `v2.4.1` a réduit `max_pool_size` de 40 à 20 ;
la latence Stripe est dans la variation normale et n'explique pas la saturation.

Sortie : **cause racine = changement de `max_pool_size` (40 → 20) dans v2.4.1**,
**confiance = 0,88**. Au-dessus du seuil → on continue.

> *« Cette fois c'est tranché : la latence Stripe était une fausse piste. La vraie cause, c'est le déploiement. Confiance 0,88, on avance. »*

### ⭐ Moment fort n°2 — La validation humaine

Avant de proposer/exécuter quoi que ce soit, l'orchestrateur **s'arrête** et attend
une approbation. Sur un système de paiement, on ne laisse jamais un agent agir seul.

> *« L'agent a une remédiation prête. Mais on est sur du paiement : rien ne s'exécute sans qu'un humain valide. L'orchestrateur attend mon feu vert. »*

(Tu cliques « Approuver ».)

### Étape 5 — Agent de remédiation

Sortie, priorisée :

- **Immédiat** — rollback `payment-api v2.4.1` (ou remonter `max_pool_size` à 40).
- **Court terme** — ajouter un timeout d'acquisition + alerte à 80 % d'utilisation du pool.
- **Long terme** — gate de revue sur les changements de config d'infrastructure.

### Étape 6 — Agent de synthèse

Sortie : le rapport d'incident final (section 5).

---

## 5. Le rapport final (exemple de sortie)

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

> *« Et voilà le livrable : un rapport qu'on peut coller tel quel dans le post-mortem. »*

---

## 6. Clôture + questions anticipées

**Phrase de clôture :** *« Six agents, une boucle de réflexion, une porte de validation — et l'orchestrateur qui décide. C'est reproductible sur n'importe quel type d'incident, il suffit de changer les logs et la base de connaissances. »*

**Q : Pourquoi pas un seul gros prompt ?**
Parce qu'on perd l'inspectabilité (on ne voit pas le raisonnement étape par étape),
le contrôle (pas de point de validation), et la robustesse (un seul prompt mélange
tout et hallucine plus facilement).

**Q : Et si un agent se trompe / hallucine ?**
C'est justement le rôle du score de confiance + de la boucle : un doute déclenche
plus de preuves au lieu d'une conclusion hâtive. Et l'humain valide avant toute action.

**Q : Ça passe à l'échelle ?**
Oui. On peut paralléliser (analyse logs + recherche KB en même temps) et passer
d'un ordre figé à un orchestrateur « superviseur » qui choisit dynamiquement
quel agent appeler.

---

## 7. Minutage indicatif

| Bloc | Durée |
|------|-------|
| Intro + le message | 1 min |
| Étapes 1 → 3 | 1,5 min |
| Boucle de réflexion (moment fort n°1) | 1,5 min |
| Cause racine 2e passage | 1 min |
| Validation humaine (moment fort n°2) + remédiation | 1,5 min |
| Rapport final + clôture | 1 min |
| **Total** | **~7,5 min** |
