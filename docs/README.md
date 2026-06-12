# Documentation

Documentation détaillée du projet, complémentaire à `SPEC.md` (contrats JSON
et critères d'acceptation), `DECISIONS.md` (journal des choix d'architecture)
et `scenario-demo-incident-paiement.md` (script de présentation).

| Document | Contenu |
|----------|---------|
| [`architecture.md`](architecture.md) | Tous les composants du système, leur rôle, leurs contrats de données ; principes de conception et contraintes non négociables. |
| [`how-it-works.md`](how-it-works.md) | Fonctionnement interne : topologie du graphe d'orchestration, boucle de réflexion, human-in-the-loop, flux SSE, propagation du `SharedContext`. |
| [`deployment.md`](deployment.md) | Guide de déploiement : dev local (CLI/UI), configuration, Docker, Azure via `azd`. |
| [`demo-guide.md`](demo-guide.md) | Guide de démo pas à pas (CLI et UI web), avec les valeurs concrètes du scénario fourni, variantes (refus humain, Azure OpenAI réel). |

## Par où commencer ?

- **Découvrir le projet** : `README.md` (racine) pour le démarrage rapide,
  puis `architecture.md` pour la vue d'ensemble des composants.
- **Comprendre l'orchestration** : `how-it-works.md`, en parallèle de
  `src/orchestrator/graph.py` et `src/orchestrator/executors.py`.
- **Déployer** : `deployment.md`.
- **Présenter la démo** : `demo-guide.md` (déroulé pratique) et
  `scenario-demo-incident-paiement.md` (script de présentation, message à
  faire passer).
