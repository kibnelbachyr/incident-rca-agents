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
