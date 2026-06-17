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

23. **Documentation detaillee dans `docs/`, en complement (pas en
    remplacement) de `SPEC.md`/`DECISIONS.md`/`scenario-demo-incident-paiement.md`** :
    quatre fichiers a portee de lecture distincte -
    `architecture.md` (composants, contrats `src/models.py`, principes de
    conception/contraintes non negociables), `how-it-works.md` (mecanique
    interne - propagation du `SharedContext`, topologie de
    `build_workflow`, boucle de reflexion, HITL via `request_info`/
    `response_handler`, protocole SSE des deux phases de `src/api/runs.py`),
    `deployment.md` (reference de configuration, Docker, `azd`/Bicep,
    tableau des ressources et roles RBAC) et `demo-guide.md` (deroule
    pratique CLI/UI avec les valeurs reelles du `StubChatClient` -
    confiance 0.55 -> 0.88 -, variantes refus humain / Azure OpenAI reel).
    `SPEC.md` reste la reference des contrats JSON et criteres
    d'acceptation, `DECISIONS.md` le journal des choix techniques, et
    `scenario-demo-incident-paiement.md` le script de presentation (message,
    minutage) : `docs/` y renvoie plutot que de les dupliquer. Linke depuis
    `README.md` ("Aller plus loin") via `docs/README.md` (index).

24. **`gpt-4o` `2024-08-06` retire de `infra/resources.bicep` -> `2024-11-20`.**
    Un `azd up` reel a echoue au provisioning de `openAiChatDeployment` avec
    `ServiceModelDeprecating: The model 'Format:OpenAI,Name:gpt-4o,Version:2024-08-06'
    is in deprecating state and cannot be used for new deployments`. Verifie
    via le [Model Retirement Schedule](https://learn.microsoft.com/azure/ai-foundry/openai/concepts/model-retirement-schedule)
    Microsoft Learn : `gpt-4o` `2024-05-13` et `2024-08-06` sont "Deprecated"
    (retrait 2026-10-01, plus disponibles pour de nouveaux deploiements),
    `2024-11-20` est "GA" (retrait 2026-10-01 egalement, remplacement
    `gpt-5.1`). `gpt-4o-mini` `2024-07-18` reste "GA", non touche par cette
    erreur, laisse inchange. `docs/deployment.md` §8.11 documente ce mode de
    panne (et le fait que les versions de modeles Azure OpenAI se deprecient
    avec le temps independamment du code) ainsi que l'echec `package-api:
    building image: signal: killed` observe en parallele (OOM probable du
    build Docker lance en meme temps que le provisioning par `azd up`).

25. **Projet Microsoft Foundry (`accounts/projects`) + instrumentation OTel de
    l'Agent Framework vers Application Insights : l'orchestration
    `WorkflowBuilder` est tracee dans Observability > Traces (ai.azure.com).**
    Cote infra (`infra/resources.bicep`), `openAi` passe de
    `Microsoft.CognitiveServices/accounts@2024-10-01` (`kind: 'OpenAI'`) a
    `@2025-06-01` (`kind: 'AIServices'`, `properties.allowProjectManagement:
    true`) : upgrade GA non destructif documente par
    [Upgrade Azure OpenAI to Microsoft Foundry](https://learn.microsoft.com/azure/foundry/how-to/upgrade-azure-openai)
    (endpoint, cles, role assignments et deploiements `gpt-4o`/`gpt-4o-mini`
    inchanges ; rollback = revenir a `kind: 'OpenAI'`). Une nouvelle ressource
    `foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01'`
    (`proj-${resourceToken}`, schema verifie via
    [accounts/projects](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2025-06-01/accounts/projects))
    expose le "projet" Foundry ; ses sorties `AZURE_FOUNDRY_PROJECT_NAME` /
    `AZURE_FOUNDRY_PROJECT_ID` sont propagees par `main.bicep`.

    Cote code, nouveau module `src/observability.py`
    (`configure_observability(settings)`, appele au demarrage de
    `src.main.run_demo` et `src.api.app.create_app`) cable
    `configure_azure_monitor(connection_string=...)` (package
    `azure-monitor-opentelemetry`, ajoute a `pyproject.toml`) puis
    `enable_instrumentation(enable_sensitive_data=...)`, pattern documente sur
    [agent_framework.observability](https://learn.microsoft.com/agent-framework/agents/observability).
    No-op si `APPLICATIONINSIGHTS_CONNECTION_STRING` est absente (mode
    hors-ligne / `StubChatClient`, aucune dependance reseau ajoutee). Une fois
    actif, `workflow.run()` (`src.orchestrator.build_workflow`) emet des spans
    `workflow.run` / `executor.process <id>` couvrant les six agents, la
    boucle de reflexion `RootCause <-> GatherEvidence` et la porte HITL
    `HumanApproval`. Nouveau champ `Settings.enable_sensitive_data` (alias
    `ENABLE_SENSITIVE_DATA`, defaut `false`, documente dans `.env.example`) :
    capture optionnelle des prompts/reponses dans les traces, reserve au dev
    (donnees potentiellement sensibles).

    La connexion Application Insights <-> projet Foundry (categorie
    `AppInsights` de `Microsoft.CognitiveServices/accounts/projects/connections`)
    n'a PAS ete codifiee en Bicep : ce type de ressource n'expose `AppInsights`
    dans `category` qu'a l'alias "latest" non versionne, absent des versions GA
    `2025-06-01`/`2025-09-01` verifiees — conformement a CLAUDE.md "ne pas
    deviner les API". Cette connexion est documentee comme etape manuelle
    ponctuelle dans `docs/deployment.md` §8.12 (portail ai.azure.com, projet
    Foundry > Agents > Traces > Connect -> selectionner
    `appi-${resourceToken}`), conformement au parcours officiel
    [Trace agent runs](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-agent-setup#connect-application-insights-to-your-foundry-project).

26. **`azd up` echoue sur `foundryProject` (`BadRequest: ... To create
    projects, you must enable a managed identity on your resource`) ->
    `identity: SystemAssigned` ajoute a `openAi`.** Un `azd up` reel apres
    DECISIONS.md #25 a echoue au provisioning de
    `aoai-${resourceToken}/proj-${resourceToken}` avec
    `BadRequest: Unsupported configuration. To create projects, you must
    enable a managed identity on your resource.` (le message generique "A
    resource with this name already exists or is in a conflicting state"
    n'est que le wrapper ARM standard d'un echec de sous-ressource imbriquee,
    pas un conflit de nommage distinct). Fix : `identity: { type:
    'SystemAssigned' }` ajoute au compte `openAi`
    (`Microsoft.CognitiveServices/accounts`) - `accounts/projects` (#25) ne
    requiert pas d'identite propre, seul le compte parent en a besoin pour
    gerer ses projets. Ajout non destructif (nouvelle identite systeme sur une
    ressource existante, aucun impact sur endpoint/cles/role assignments
    existants). Si `azd up` echoue encore avec "already exists or is in a
    conflicting state" apres ce fix, verifier dans le portail Azure si
    `proj-${resourceToken}` existe deja sous `aoai-${resourceToken}` (onglet
    "Projects") dans un etat `Failed` et le supprimer avant de relancer (un
    retry `azd up`/`azd provision` simple suffit normalement, PUT ARM etant
    idempotent).

27. **`azd up` echoue encore sur `foundryProject` apres #26 (meme
    `BadRequest: ... must enable a managed identity on your resource`, sur
    un environnement neuf) -> `identity: SystemAssigned` ajoute aussi sur le
    PROJET, pas seulement sur le compte.** Sur un environnement neuf,
    `aoai-${resourceToken}` est cree avec succes en ~17s (identite incluse,
    #26), mais `aoai-${resourceToken}/proj-${resourceToken}` echoue 805ms
    plus tard avec le meme `BadRequest: Unsupported configuration. To create
    projects, you must enable a managed identity on your resource.` - ce qui
    invalide l'hypothese de #26 selon laquelle "`accounts/projects` ne
    requiert pas d'identite propre, seul le compte parent en a besoin".
    Confirmation via le module de reference Microsoft
    [`avm/ptn/ai-ml/ai-foundry`](https://github.com/Azure/bicep-registry-modules/blob/main/avm/ptn/ai-ml/ai-foundry/modules/project/main.bicep) :
    la ressource `Microsoft.CognitiveServices/accounts/projects` y declare
    elle-meme `identity: { type: 'SystemAssigned' }`, en plus de
    `managedIdentities: { systemAssigned: true }` sur le compte parent (module
    `avm/res/cognitive-services/account`). Fix : `identity: { type:
    'SystemAssigned' }` ajoute a `foundryProject` (en plus de celle sur
    `openAi`, #26) - type `Identity` valide pour
    `accounts/projects@2025-06-01` (`'None' | 'SystemAssigned' |
    'SystemAssigned, UserAssigned' | 'UserAssigned'`, schema deja verifie en
    #25). Ajout non destructif (nouvelle identite systeme sur une ressource
    enfant, aucun impact sur les sorties
    `AZURE_FOUNDRY_PROJECT_NAME`/`AZURE_FOUNDRY_PROJECT_ID` ni sur les role
    assignments existants, qui referencent uniquement l'identite du Container
    App).

28. **`azd provision` echoue ensuite sur le compte `openAi`
    (`aoai-${resourceToken}`, tres rapidement) avec `BadRequest:
    PublicNetworkAccess is required for this resouce` [sic] ->
    `publicNetworkAccess: 'Enabled'` ajoute explicitement aux `properties`
    de `openAi`.** Apres #27, un retry sur l'environnement de la Defaillance
    #3 a echoue en 1.665s sur le compte lui-meme (qui avait pourtant reussi
    en 17s lors de la tentative precedente) avec ce `BadRequest` (toujours
    sous le meme wrapper generique "already exists or in a conflicting
    state"). Avec `allowProjectManagement: true` (#25) et un sous-projet
    `accounts/projects` ayant sa propre identite (#27), Azure exige
    desormais que `properties.publicNetworkAccess` du compte parent soit
    explicitement renseigne - il ne peut plus rester implicite/omis.
    Confirmation : le module de reference
    [`avm/res/cognitive-services/account`](https://github.com/Azure/bicep-registry-modules/blob/main/avm/res/cognitive-services/account/main.bicep)
    (utilise par `avm/ptn/ai-ml/ai-foundry`, #27) ne laisse JAMAIS cette
    propriete implicite :
    `publicNetworkAccess: publicNetworkAccess != null ? publicNetworkAccess
    : (!empty(networkAcls) ? 'Enabled' : 'Disabled')`. Fix :
    `publicNetworkAccess: 'Enabled'` ajoute aux `properties` de `openAi`
    (`Microsoft.CognitiveServices/accounts`, enum `'Disabled' | 'Enabled'`
    valide pour `@2025-06-01`). `'Enabled'` car ce bicep ne provisionne
    aucun VNet/private endpoint : le Container App et l'identite dev
    (`principalId`) accedent a `aoai-${resourceToken}` via son endpoint
    public, comme c'etait implicitement le cas avant ce changement (le
    compte avait reussi sans cette propriete lors de la Defaillance #3).
    Ajout non destructif, ne restreint aucun acces existant.

29. **Rendre les six agents visibles dans l'UI du projet Microsoft Foundry ->
    script `scripts/register_foundry_agents.py` utilisant
    `ExternalAgentDefinition`, pas `PromptAgentDefinition`.** Les agents de
    cette demo s'executent hors de Foundry, directement contre Azure OpenAI
    via le Microsoft Agent Framework (`AzureOpenAIStructuredChatClient`,
    `src/agents/clients.py`) - il n'y a pas d'orchestration "native Foundry"
    a la place. `PromptAgentDefinition` suppose que Foundry heberge et execute
    l'agent (prompt + modele geres cote Foundry) : inadapte ici, et aurait
    introduit une deuxieme source de verite pour les instructions/le modele
    de chaque agent. `ExternalAgentDefinition` (`azure-ai-projects`,
    `discriminator="external"`) correspond exactement au cas : "Represents a
    third-party agent hosted outside Foundry (...) Registration is
    metadata-only" - confirme par introspection du SDK installe
    (`inspect.getsource`), conformement a la consigne "ne pas deviner les
    API". Aucune ressource de calcul n'est creee ; seule l'entree apparait
    dans l'onglet Agents du projet.

    Precondition corrigee au passage : `AgentTelemetryLayer` (package
    `agent_framework`, instrumentation OTel) source l'attribut de span
    `gen_ai.agent.id` depuis `Agent.id`, pas `Agent.name` - confirme par
    lecture du source installe. Sans `id` explicite,
    `BaseChatClient.as_agent(...)` genere un `uuid4()` aleatoire a chaque
    redemarrage du processus, qui ne correspondrait alors jamais a l'`id`
    statique enregistre dans Foundry (le nom de l'agent, ex. `RootCause`) -
    les traces (#25, docs/deployment.md §8.12) ne se seraient jamais
    rattachees a l'enregistrement External Agent. Fix : `id=agent_name`
    ajoute a l'appel `as_agent(...)` dans
    `AzureOpenAIStructuredChatClient.get_structured_response`
    (`src/agents/clients.py`) - meme valeur que `agent_name` deja utilise
    comme `name=`, donc aucun changement de comportement visible ailleurs.

    L'enregistrement (`AIProjectClient(..., allow_preview=True)`,
    `agents.create_version(agent_name=..., definition=ExternalAgentDefinition())`)
    est une fonctionnalite **preview** d'`azure-ai-projects` >=2.2.0 - a
    documenter comme telle (docs/deployment.md §8.13), l'API pouvant changer
    avant la GA. Dependance ajoutee dans un groupe optionnel distinct
    `[foundry]` (`pyproject.toml`), separe de `[dev]` : sans rapport avec
    l'execution ou les tests de la demo elle-meme, seulement avec ce script
    d'enregistrement ponctuel.

    Endpoint du projet (`AZURE_FOUNDRY_PROJECT_ENDPOINT`, nouveau) construit
    par concatenation de chaines dans `infra/resources.bicep`
    (`'https://${openAi.name}.services.ai.azure.com/api/projects/${foundryProject.name}'`,
    forme documentee par `AIProjectClient`) plutot que lu sur une propriete
    de ressource : confirme via la doc Microsoft Learn que
    `Microsoft.CognitiveServices/accounts/projects`
    (`ProjectProperties`) n'expose que `description`/`displayName`, aucune
    propriete d'endpoint. `openAi.name` == `properties.customSubDomainName`
    (les deux fixes a `aoai-${resourceToken}` dans la ressource existante,
    #21) : pas de lookup manuel necessaire, recupere comme les autres
    sorties Bicep via `azd env get-values >> .env` (deja le flux dev-local
    documente, §8.7).

    Pas d'enregistrement separe pour le "workflow" (`WorkflowBuilder`, la
    boucle de reflexion, la porte HITL) : Foundry n'a pas de ressource
    "workflow" a enregistrer independamment des agents qui le composent, et
    la timeline d'execution complete (executors, boucle, HITL) est deja
    entierement visible via les traces OTel existantes (#25,
    docs/deployment.md §8.12) une fois Application Insights connecte -
    aucun gap a combler ici.

30. **Correction de #29 : Foundry a bien une ressource "workflow"
    enregistrable (`WorkflowAgentDefinition`) -> script
    `scripts/register_foundry_workflow.py` + CSDL ecrit a la main
    `scripts/foundry_workflow.yaml`.** Le dernier paragraphe de #29 affirmait
    qu'aucune ressource "workflow" distincte n'existait cote Foundry ;
    relecture de la doc officielle "Declarative Workflows" (Microsoft Agent
    Framework) et introspection du SDK installe (`azure-ai-projects==2.2.0`,
    `_models.py`) montrent le contraire : `WorkflowAgentDefinition` existe
    bien (`discriminator="workflow"`, champ `workflow: str` = "The CSDL YAML
    definition of the workflow"), enregistrable via le meme
    `agents.create_version(agent_name=..., definition=...)` que les six
    agents. Conserve #29 tel quel (registre historique) plutot que de le
    corriger sur place.

    Aucun exportateur n'existe pour generer ce CSDL depuis le
    `WorkflowBuilder` Python (ni dans `agent-framework`, ni cote Foundry) :
    le YAML est donc ecrit a la main, en miroir de la topologie reelle de
    `src/orchestrator/graph.py` (sequence des six agents, boucle
    `RootCause <-> GatherEvidence` bornee par `loopCount`/`maxReflectionLoops`,
    porte HITL `Question`/`approved`) - valeurs de seuil/boucle recopiees en
    dur (`confidenceThreshold: 0.75`, `maxReflectionLoops: 2`) car ce workflow
    autonome cote Foundry n'a pas acces a `src/config.py`/`.env`. Champs
    Pydantic (`confiance`, `preuves_manquantes`, `texte`, etc.) repris
    exactement de `src/models.py` dans les expressions Power Fx du YAML.
    Schema CSDL (kinds d'action, boucles via `GotoAction`+`If`, porte HITL via
    `Question`) confirme par lecture de la doc officielle plutot que devine,
    conformement a la consigne "ne pas deviner les API" - cf. en-tete de
    `foundry_workflow.yaml` pour le detail des choix (forme trigger-based du
    CSDL, espace de noms `Local.*`, fonctions Power Fx utilisees).

    Header `Foundry-Features: WorkflowAgents=V1Preview` (fonctionnalite
    preview) : confirme par lecture du source installe
    (`azure/ai/projects/operations/_patch_agents.py`) que le SDK l'ajoute
    automatiquement dans `create_version` dans le cas ou
    `AIProjectClient(..., allow_preview=True)` est utilise - le meme flag
    `allow_preview=True` deja en place pour #29, aucun code supplementaire
    necessaire.

    Limite assumee, documentee dans l'en-tete de `foundry_workflow.yaml` et
    docs/deployment.md §8.14 : ce CSDL ne s'execute pas reellement (les six
    `InvokeAzureAgent` referencent des `ExternalAgentDefinition` - entrees
    metadata-only sans modele/instructions cote Foundry, cf. #29), donc
    "Run Workflow" dans le portail echouera probablement a la premiere
    invocation d'agent. Sa valeur est l'affichage de la topologie
    (noeuds/aretes/conditions) dans le canevas visuel, pas l'execution ;
    l'execution reelle reste 100% `src/orchestrator/graph.py` + `executors.py`,
    observable via les traces OTel (#25, docs/deployment.md §8.12). A
    resynchroniser a la main si `graph.py` change.
