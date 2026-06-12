# DECISIONS.md — Journal des decisions d'architecture

Decisions prises en autonomie pendant le developpement de la demo. Une ligne
de contexte + justification par decision, ordre chronologique.

1. **`agent-framework` 1.8.x a casse les noms cites dans le brief.**
   `ChatAgent` / `agent_framework.azure.AzureOpenAIChatClient` / `create_agent`
   n'existent plus (verifie par introspection du package installe + doc
   Microsoft Learn "Significant Changes"). Remplaces par `Agent` (cree via
   `BaseChatClient.as_agent(...)`) et
   `agent_framework.openai.OpenAIChatCompletionClient`, qui route vers Azure
   OpenAI via `azure_endpoint=` / `credential=` / les variables `AZURE_OPENAI_*`.
   Conforme a la consigne "si une API a change, suis la doc, pas le brief".

2. **Contexte partage = un seul objet pydantic (`SharedContext`) qui circule
   par message entre les `Executor`** (`ctx.send_message`), plutot que
   `ctx.set_state`/`get_state`. Plus simple a inspecter/logger a chaque etape
   du streaming, et evite tout etat global mutable partage entre executions
   concurrentes du workflow.

3. **Abstraction `StructuredChatClient` (Protocol) avec deux implementations** :
   `StubChatClient` (reponses figees, deterministes, zero appel reseau) et
   `AzureOpenAIStructuredChatClient` (agents reels via `as_agent` +
   `default_options={"response_format": <ModelePydantic>}`).
   `get_chat_client(settings, light=...)` choisit automatiquement selon
   `Settings.use_real_azure_openai` (endpoint Azure OpenAI reel configure ou
   non). Permet d'executer toute la demo et les 8 criteres d'acceptation hors
   ligne, sans credentials Azure.

4. **`StubChatClient` reproduit fidelement le scenario de demo**, y compris la
   boucle de reflexion : pour l'agent `RootCause`, le 1er appel renvoie
   confiance 0.55 (deux hypotheses concurrentes + `preuves_manquantes` non
   vide), le 2e appel (apres `GatherEvidence`) renvoie confiance 0.88 et
   designe le changement de `max_pool_size` (Stripe ecarte). Les autres agents
   renvoient une reponse canonique conforme a SPEC.md section 4 / section 6.

5. **`GatherEvidence` n'est PAS un 7e agent.** C'est une etape de
   l'orchestrateur (cf. SPEC.md section 5) qui re-sollicite les agents
   `LogAnalyzer` (avec les `preuves_manquantes` en focus) et `KBSearch`, et
   fusionne le resultat dans `SharedContext` avant de repasser dans
   `RootCause`. Conserve exactement les "six agents specialises" de la section 2.

6. **Boucle de reflexion implementee avec `add_switch_case_edge_group`** apres
   l'executeur `RootCause` : `Case(needs_more_evidence -> GatherEvidence)`,
   `Default(-> HumanApproval)`, et `add_edge(GatherEvidence, RootCause)` ferme
   le cycle. `needs_more_evidence` = `confiance < CONFIDENCE_THRESHOLD and
   loop_count < MAX_REFLECTION_LOOPS` : la boucle est donc bornee par
   construction (critere d'acceptation 8).

7. **Porte HITL implementee avec `ctx.request_info(RemediationApprovalRequest,
   response_type=bool)` + `@response_handler`** plutot que
   `@tool(approval_mode="always_require")` : la remediation est un executeur
   dedie (pas un appel d'outil isole), donc geler l'executeur lui-meme via
   `request_info` est plus direct et produit un `RequestInfoEvent` observable
   dans le flux (critere d'acceptation 5).

8. **`LocalKnowledgeBase` calcule une similarite de Jaccard reelle** entre le
   vocabulaire (services + symptomes) de l'incident et celui (services +
   symptomes + tags) de chaque precedent de `knowledge_base.json`. Avec
   seulement deux precedents et `top_k=2`, les deux sont toujours retournes :
   le critere d'acceptation 2 est satisfait independamment du LLM/stub.
   Interface `KnowledgeBase` commune avec `AzureAISearchKnowledgeBase`
   (`azure.search.documents.aio.SearchClient`) pour `KB_MODE=azure_search`.

9. **`Incident.severite` valide par regex `^SEV-[1-5]$`** (pas un `Literal`
   fige sur "SEV-1") : conserve le contrat reutilisable pour d'autres
   incidents tout en validant le format attendu par le critere 1.

10. **Aucun secret en dur** : `Settings` (pydantic-settings) lit uniquement
    `.env` / variables d'environnement ; `.env` reste hors git, seul
    `.env.example` est versionne.

11. **La remediation reste strictement un plan affiche.** `RemediationPlan`
    est un objet de donnees ; aucun executeur n'appelle d'API d'infrastructure
    reelle. "Executer" = afficher le plan dans le rapport CLI apres
    approbation humaine.

12. **Pas de `from __future__ import annotations` dans `executors.py`.**
    `@response_handler` (sur `HumanApprovalExecutor.handle_response`)
    introspecte la signature via `inspect.signature(...).annotation` SANS
    resoudre les chaines PEP 563 ; avec l'import `__future__`,
    `WorkflowContext[SharedContext, SharedContext]` devient une chaine et
    `_validate_response_handler_signature` echoue (`ValueError: ... must be
    annotated as WorkflowContext...`). Tous les types utilises sont importes
    en tete de fichier, donc retirer l'import futur est sans risque sous
    Python 3.11+.

13. **`ctx.yield_output(context)` transmet une reference directe (pas une
    copie) au `SharedContext` mutable.** Apres un `run()` complet, tous les
    evenements `type="output"` du resultat partagent donc le MEME objet
    final : les champs reaffectes (ex. `root_cause`, `log_analysis`) ne
    refletent que la derniere valeur si inspectes a posteriori, alors que les
    champs accumules par `.append()`/`.extend()` (`root_cause_history`,
    `evidence_log`) conservent l'historique complet. Les tests
    d'orchestration lisent donc `root_cause_history` pour distinguer les deux
    passages de `RootCause`. En streaming (`stream=True`), chaque
    `event.data` reste un instantane pertinent au moment de l'emission.

14. **`HumanApprovalExecutor` garde le `SharedContext` complet sur
    `self._context`** (attribut d'instance) entre `handle()` (qui emet
    `request_info`) et `@response_handler handle_response()` (qui recoit la
    reponse). `RemediationApprovalRequest` ne porte qu'un sous-ensemble
    (incident, root_cause, kb_matches) car c'est ce sous-ensemble qui doit
    etre presente a l'humain / serialise dans l'evenement `request_info` ; le
    contexte complet, lui, doit reprendre son chemin dans le graphe via
    `ctx.send_message`. Ce pattern fonctionne car le `Workflow` et ses
    executeurs persistent entre les deux appels `workflow.run()` (premier run
    qui pause, puis `run(responses={...})`).

15. **Refus humain = `ctx.yield_output(context)` au lieu de
    `ctx.send_message(context)`** dans `handle_response`. Aucune arete ne
    part de `human_approval` vers un noeud terminal alternatif : c'est
    l'ABSENCE de `send_message` qui arrete le graphe (plus aucun executeur a
    invoquer), tandis que `yield_output` produit la seule sortie observable
    (`approved=False`, `remediation_plan=None`, `report=None`). Conforme a
    SPEC.md/CLAUDE.md : aucun plan n'est genere ni affiche sans approbation.

16. **`needs_more_evidence` est une closure qui capture `settings`** (et non
    une fonction pure `(context, settings)`), car `Case(condition:
    Callable[[Any], bool], target=...)` n'accepte qu'un seul argument (le
    `SharedContext` achemine sur l'arete). `CONFIDENCE_THRESHOLD` /
    `MAX_REFLECTION_LOOPS` ne font pas partie du contrat de donnees ; ils sont
    injectes via la portee de `build_workflow(settings)`, qui est aussi
    l'endroit naturel ou `light_client`/`strong_client` et les agents
    partages (`log_analyzer_agent`, `kb_search_agent`, reutilises par
    `GatherEvidenceExecutor`) sont construits.

17. **Persistance via un `Protocol` `PersistenceStore`** (src/tools/persistence.py),
    sur le meme modele que `KnowledgeBase` (DECISIONS.md #8) :
    `LocalPersistenceStore` (fichiers JSON sous `output/runs/`, mode par
    defaut/hors-ligne) et `CosmosPersistenceStore`
    (`azure.cosmos.aio.CosmosClient`, partition key `/id`). `get_persistence_store(settings)`
    choisit selon `settings.cosmos_endpoint`. Le conteneur Cosmos est suppose
    deja provisionne par Bicep (azd) : le code applicatif ne fait que du
    data-plane (`upsert_item`/`read_item`/`query_items`), jamais de creation
    de base/conteneur, et utilise `AzureCliCredential`/`DefaultAzureCredential`
    selon `AZURE_AUTH_MODE` (variantes async de DECISIONS.md, coherentes avec
    `src/agents/clients.py`).

18. **API FastAPI en deux phases SSE** (`src/api/runs.py`) au lieu d'un
    websocket ou de `agent_framework_devui`/`ag_ui` (generiques, non adaptes a
    l'UI du domaine) : `POST /api/runs` cree un `Workflow`
    (`build_workflow`), le garde dans `app.state.runs` (registre en memoire
    `{run_id: RunState}`) et streame un evenement `step` par sortie d'agent
    (y compris la boucle `RootCause <-> GatherEvidence`) jusqu'a
    `request_info` (`approval_required`). `POST /api/runs/{id}/approval`
    reprend le MEME objet `Workflow` via `workflow.run(responses={request_id:
    bool})` : conserver l'instance est necessaire car `HumanApprovalExecutor`
    porte l'etat sur `self._context` entre les deux appels (DECISIONS.md
    #14). Le refus (DECISIONS.md #15) ne produit qu'un `step`
    `human_approval` puis `done` ; l'approbation produit `remediation` +
    `summary` puis persiste le `SharedContext` final via `PersistenceStore`
    avant `done`. `EventSource` ne permettant pas le POST, le flux est
    consomme cote client via `fetch` + `ReadableStream` (`frontend/src/api.ts`).

19. **Frontend React + Vite, scaffolding minimal** (`frontend/`) : en dev,
    `vite.config.ts` proxy `/api` vers `127.0.0.1:8000` (pas de CORS a gerer) ;
    en prod, `frontend/dist/` est servi par FastAPI via `StaticFiles` au
    montage `/` (`src/api/app.py`). `frontend/src/types.ts` reprend 1:1 les
    contrats de `src/models.py` + les reponses de `src/api/*.py` (un seul jeu
    de contrats cote backend, ce fichier reflete la forme JSON — tenu a jour
    manuellement, pas de generation de schema pour rester simple en demo).
    `TopologyGraph` anime le graphe a 8 noeuds de `src/orchestrator/graph.py` ;
    comme `HumanApprovalExecutor` n'emet un `step` qu'en cas de refus
    (DECISIONS.md #15), le passage par la porte HITL en cas d'approbation est
    deduit (noeud + aretes `root_cause -> human_approval -> remediation`
    marques visites/traverses) de la presence d'un `step` `remediation` dans
    le flux, plutot que d'une transition consecutive explicite.

20. **`Dockerfile` reconstruit pour servir l'API + l'UI (plus le CLI)** :
    `ENTRYPOINT` passe de `python -m src.main` a
    `uvicorn src.api.app:app --host 0.0.0.0 --port 8000`
    (`src/api/app.py`, DECISIONS.md #18, monte `frontend/dist/` via
    `StaticFiles` si present). Etape 1 (`node:20-slim`, alias
    `frontend-build`) execute `npm ci` + `npm run build` sur `frontend/` et
    produit `frontend/dist/` ; etape 2 (`python:3.11-slim`) installe le
    paquet (`pip install -e .`, conserve `src.config.REPO_ROOT` aligne sur
    `/app` pour les chemins par defaut `data/*.json|log` et
    `frontend/dist/`) puis copie `frontend/dist/` depuis l'etape 1.
    `.dockerignore` exclut desormais `frontend/node_modules/`,
    `frontend/dist/`, `frontend/*.tsbuildinfo` (arbre hote jamais embarque,
    seul le build reproductible de l'etape 1 l'est) ainsi que `infra/`,
    `.azure/`, `azure.yaml` (artefacts azd/Bicep sans rapport avec l'image
    applicative). `EXPOSE 8000` (port d'ingress Container Apps) et
    `ENV AZURE_AUTH_MODE=managed_identity` restent inchanges.

21. **Provisionnement Azure via Bicep + Azure Developer CLI (azd)** :
    `azure.yaml` declare un seul service `api` (`language: docker`, `host:
    containerapp`, `docker.path: ./Dockerfile`) ; `infra/main.bicep` (portee
    `subscription`) cree le resource group puis delegue a
    `infra/resources.bicep` (portee resource group, parametre via
    `infra/main.parameters.json` -> `${AZURE_ENV_NAME}` / `${AZURE_LOCATION}` /
    `${AZURE_PRINCIPAL_ID}`). Conforme a CLAUDE.md "Stack technique"/"Hebergement
    cible" : `resources.bicep` provisionne Log Analytics + Application Insights,
    une identite managee utilisateur (attachee au Container App), un Container
    Registry (+role `AcrPull`), un compte Azure OpenAI avec deux deploiements
    (`gpt-4o` et `gpt-4o-mini`, sku `GlobalStandard`, versions `2024-08-06` /
    `2024-07-18` verifiees via Microsoft Learn), Azure AI Search (sku `basic`,
    pour le RAG), Cosmos DB serverless (base `incidents` / conteneur `records`,
    partition key `/id`, alignes sur `src/tools/persistence.py`), un Container
    Apps Environment et le Container App (`tags: {'azd-service-name': 'api'}`,
    ingress externe port 8000, image placeholder
    `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest` remplacee par
    `azd deploy`). Deux fichiers Bicep (et non une modularisation par service)
    pour rester lisible en demo ; les deux compilent sans erreur via le Bicep
    CLI standalone (`bicep build`, v0.44.1).

22. **Aucun secret en clair sur les ressources deployees** : `disableLocalAuth:
    true` sur le compte Azure OpenAI et sur le compte Cosmos DB desactive les
    cles API/maitre — toute l'authentification data-plane passe par des role
    assignments Microsoft Entra ID (`Cognitive Services OpenAI User`, `Search
    Index Data Reader`, le role Cosmos DB integre "Built-in Data Contributor"
    `00000000-0000-0000-0000-000000000002` reference directement par GUID sans
    `sqlRoleDefinitions` custom, et `AcrPull`), tous accordes au
    `principalId`/`clientId` de l'identite managee du Container App. Celui-ci
    recoit aussi `AZURE_AUTH_MODE=managed_identity` et
    `AZURE_CLIENT_ID=<identity.clientId>` (necessaire pour que
    `DefaultAzureCredential` choisisse cette identite utilisateur plutot qu'une
    autre). Un parametre optionnel `principalId` (rempli par azd via
    `AZURE_PRINCIPAL_ID`, vide par defaut) accorde les memes roles data-plane au
    compte du developpeur, pour pointer `AZURE_AUTH_MODE=cli` (`az login`) vers
    les vraies ressources deployees — les sorties `AZURE_OPENAI_ENDPOINT` /
    `AZURE_AI_SEARCH_ENDPOINT` / `COSMOS_ENDPOINT` / ... de `main.bicep`
    correspondent 1:1 aux alias de `Settings` (`src/config.py`) et sont
    recuperables via `azd env get-values` pour completer un `.env` local.
    `openAiChatDeploymentLight` porte un `dependsOn` explicite vers
    `openAiChatDeployment` : Azure OpenAI rejette les operations de deploiement
    concurrentes sur le meme compte, donc sans cette dependance ARM peut
    paralleliser les deux et l'un des deux echoue. Le Container App garde
    `scale: {minReplicas: 1, maxReplicas: 1}` : `app.state.runs`
    (src/api/runs.py, DECISIONS.md #18) est un registre en memoire par
    processus, donc plusieurs replicas casseraient la reprise HITL. `KB_MODE`
    n'est volontairement PAS positionne sur le Container App (reste
    `"local"`, valeur par defaut de `Settings`) : Azure AI Search est
    provisionne (RAG, CLAUDE.md) et `AZURE_AI_SEARCH_ENDPOINT`/`_INDEX` sont
    injectes avec le role `Search Index Data Reader`, mais sans pipeline
    d'indexation de `data/knowledge_base.json` un `KB_MODE=azure_search` avec
    index vide casserait le critere d'acceptation 2 (DECISIONS.md #8) ; un
    utilisateur peut basculer manuellement apres indexation.
