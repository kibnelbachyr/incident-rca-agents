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
