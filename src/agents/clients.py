# Copyright (c) Microsoft. All rights reserved.

"""Abstraction du client de chat structure utilise par les six agents.

Deux implementations partagent le protocole `StructuredChatClient` :

- `StubChatClient` : reponses deterministes rejouant le scenario de demo
  (SPEC.md section 6 / scenario-demo-incident-paiement.md), utilisee quand
  aucun endpoint Azure OpenAI exploitable n'est configure (mode hors-ligne).
- `AzureOpenAIStructuredChatClient` : agents reels via
  `agent_framework.openai.OpenAIChatCompletionClient` + `as_agent(...)`,
  route vers Azure OpenAI / Microsoft Foundry par les variables `AZURE_OPENAI_*`
  (voir SPEC.md section 3 et `.env.example`).

`get_chat_client(settings, light=...)` choisit automatiquement entre les deux
selon `Settings.use_real_azure_openai` (DECISIONS.md #1 et #3).
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from src.config import Settings

T = TypeVar("T", bound=BaseModel)


class StructuredChatClient(Protocol):
    """Capacite minimale requise par un agent : produire une reponse JSON
    validee contre un modele pydantic, a partir d'instructions et d'un prompt."""

    async def get_structured_response(
        self,
        *,
        agent_name: str,
        instructions: str,
        prompt: str,
        response_model: type[T],
    ) -> T: ...


# ---------------------------------------------------------------------------
# Stub deterministe (mode hors-ligne) — DECISIONS.md #4
# ---------------------------------------------------------------------------

# Reponses canon par agent. Chaque entree est soit un dict (reponse unique,
# rejouee a chaque appel), soit une liste de dicts indexee par numero d'appel
# (le dernier element est reutilise au-dela de la longueur de la liste). La
# liste permet de simuler la boucle de reflexion de l'agent RootCause :
# 1er passage confiance basse (deux hypotheses), 2e passage tranche.
_STUB_RESPONSES: dict[str, dict[str, Any] | list[dict[str, Any]]] = {
    "LogAnalyzer": [
        # 1er passage : analyse initiale des logs bruts.
        {
            "timeline": [
                {"time": "14:00:11", "event": "Deploiement de payment-api v2.4.1 en production (rolling, 6 pods)"},
                {"time": "14:00:12", "event": "Application de la config db.max_pool_size=20 (precedemment 40)"},
                {"time": "14:22:47", "event": "Pool de connexions DB sature a 100% (20/20), aucune connexion libre"},
                {"time": "14:23:15", "event": "Premiers connection acquisition timeout apres 5000ms"},
                {"time": "14:24:50", "event": "Taux d'erreur a 38% sur 60s - candidat SEV"},
                {"time": "14:26:30", "event": "Tempete de retries clients : trafic entrant x3.4 vs normal"},
            ],
            "anomalies": [
                "Utilisation du pool de connexions DB passe de 70% a 100% en 6 minutes (14:16-14:22)",
                "Taux d'erreur de paiement passe de 0,18% a 38% en moins de 25 minutes",
                "Tempete de retries cote client qui amplifie la charge sur un pool deja sature",
            ],
            "correlated_events": [
                "Le deploiement v2.4.1 (14:00:11) precede la saturation du pool (14:22:47) d'environ 22 minutes",
                "La modification de db.max_pool_size a ete appliquee au moment exact du deploiement",
            ],
        },
        # 2e passage (GatherEvidence) : focus sur le diff de config et la latence Stripe.
        {
            "timeline": [
                {"time": "14:00:12", "event": "Diff de deploiement confirme : db.max_pool_size 40 -> 20"},
                {"time": "14:23:31", "event": "Latence d'appel Stripe 780ms (p95 de reference 600ms)"},
                {"time": "14:24:33", "event": "Latence d'appel Stripe 820ms (pic observe)"},
                {"time": "14:29:18", "event": "Latence Stripe revenue a 640ms, dans la variance normale"},
                {"time": "14:30:05", "event": "Pool DB toujours sature a 100% alors que Stripe est redevenu normal"},
                {"time": "14:35:47", "event": "Revue de diff de l'oncall : confirmation db.max_pool_size 40 -> 20 dans v2.4.1"},
            ],
            "anomalies": [
                "La latence Stripe redevient normale (640ms) des 14:29:18, alors que la saturation du pool DB persiste au-dela de 14:30",
                "Le diff du deploiement v2.4.1 confirme une reduction de moitie de db.max_pool_size (40 -> 20)",
            ],
            "correlated_events": [
                "Le retour a la normale de la latence Stripe (14:29) ne coincide pas avec la fin de l'incident : Stripe n'explique pas la duree de la saturation",
                "La reduction de db.max_pool_size coincide exactement avec l'horodatage du deploiement v2.4.1 (14:00:11-12)",
            ],
        },
    ],
    "IncidentExtractor": {
        "titre": "Pic d'echecs de paiement",
        "severite": "SEV-1",
        "services": ["payment-api", "db-pool"],
        "fenetre": "14:23 -> en cours",
        "symptomes": [
            "echec de persistance des transactions (no DB connection)",
            "pool de connexions DB sature a 100%",
            "tempete de retries cote client amplifiant la charge",
        ],
    },
    "KBSearch": {
        "matches": [
            {
                "id": "INC-204",
                "similarite": 0.82,
                "resolution": (
                    "Rollback du deploiement et restauration de db.max_pool_size a 40 ; "
                    "ajout d'une alerte sur l'utilisation du pool de connexions."
                ),
            },
            {
                "id": "INC-187",
                "similarite": 0.61,
                "resolution": (
                    "Mise en place d'un circuit breaker et de retries avec backoff sur "
                    "les appels au processeur de paiement externe (Stripe)."
                ),
            },
        ],
    },
    "RootCause": [
        # 1er passage : confiance insuffisante, deux hypotheses concurrentes.
        {
            "cause": (
                "Deux hypotheses concurrentes : (a) la reduction de db.max_pool_size par le "
                "deploiement v2.4.1, (b) une degradation de la latence du processeur de paiement Stripe"
            ),
            "raisonnement": (
                "La saturation du pool de connexions DB et la hausse de la latence Stripe sont "
                "toutes deux correlees temporellement avec le pic du taux d'erreur a 14:24. Les "
                "precedents INC-204 (config pool) et INC-187 (latence Stripe) collent tous les deux "
                "au profil de symptomes observe. Aucune preuve definitive ne permet encore de "
                "departager ces deux pistes."
            ),
            "confiance": 0.55,
            "preuves_manquantes": [
                "Diff de configuration du deploiement v2.4.1 : valeur de db.max_pool_size avant/apres",
                "Evolution de la latence Stripe apres 14:26 (retour a la normale ou degradation persistante)",
            ],
        },
        # 2e passage (apres GatherEvidence) : cause tranchee, Stripe ecarte.
        {
            "cause": (
                "Le deploiement payment-api v2.4.1 a reduit db.max_pool_size de 40 a 20, saturant "
                "le pool de connexions DB sous la charge nominale"
            ),
            "raisonnement": (
                "Le diff de deploiement confirme la reduction de db.max_pool_size de 40 a 20, "
                "appliquee exactement au moment du deploiement (14:00:11-12). Le pool atteint 100% "
                "d'utilisation 22 minutes plus tard et les echecs de persistance demarrent "
                "immediatement apres. La latence Stripe, elevee un court instant (780-820ms), est "
                "revenue a la normale (640ms) des 14:29 alors que la saturation du pool persistait : "
                "elle n'explique donc pas la duree ni la severite de l'incident. Cette piste est ecartee."
            ),
            "confiance": 0.88,
            "preuves_manquantes": [],
        },
    ],
    "Remediation": {
        "immediat": [
            "Rollback de payment-api vers v2.4.0 (ou remonter db.max_pool_size a 40 sans rollback complet)",
        ],
        "court_terme": [
            "Ajouter un timeout d'acquisition de connexion explicite et le journaliser",
            "Ajouter une alerte a 80% d'utilisation du pool de connexions DB",
        ],
        "long_terme": [
            "Mettre en place une porte de revue (gate) obligatoire sur les changements de "
            "configuration infra avant deploiement",
        ],
    },
    "Summary": {
        "titre": "INCIDENT SEV-1 - Pic d'echecs de paiement",
        "fenetre": "14:23 -> 14:41 (resolu)",
        "impact": "38% des transactions en echec",
        "cause_racine": (
            "Le deploiement payment-api v2.4.1 a reduit max_pool_size de 40 a 20. Le pool s'est "
            "sature a 14:23, empechant la persistance des transactions. La latence Stripe observee "
            "etait dans la normale (fausse piste ecartee)."
        ),
        "confiance": 0.88,
        "remediation": [
            "Rollback v2.4.1 (applique apres validation)",
            "Timeout d'acquisition + alerte a 80% du pool",
            "Gate de revue sur les changements de config infra",
        ],
        "precedent_lie": "INC-204 (meme schema, meme resolution)",
        "texte": (
            "INCIDENT SEV-1 — Pic d'échecs de paiement\n"
            "Fenêtre : 14:23 → 14:41 (résolu)   Impact : 38% des transactions en échec\n"
            "\n"
            "CAUSE RACINE (confiance 0,88)\n"
            "Le déploiement payment-api v2.4.1 a réduit max_pool_size de 40 à 20.\n"
            "Le pool s'est saturé à 14:23, empêchant la persistance des transactions.\n"
            "La latence Stripe observée était dans la normale (fausse piste écartée).\n"
            "\n"
            "REMÉDIATION\n"
            "1. Rollback v2.4.1 (appliqué après validation)\n"
            "2. Timeout d'acquisition + alerte à 80% du pool\n"
            "3. Gate de revue sur les changements de config infra\n"
            "\n"
            "PRÉCÉDENT LIÉ : INC-204 (même schéma, même résolution)"
        ),
    },
}


class StubChatClient:
    """Client "stub" deterministe pour executer la demo hors-ligne.

    Ne fait aucun appel reseau : renvoie des reponses figees qui respectent
    les contrats pydantic de `src/models.py` et reproduisent le scenario de
    demo, y compris la boucle de reflexion de `RootCause` (1er passage
    confiance 0.55, 2e passage confiance 0.88 apres `GatherEvidence`).
    """

    def __init__(self) -> None:
        self._call_counts: dict[str, int] = {}

    async def get_structured_response(
        self,
        *,
        agent_name: str,
        instructions: str,
        prompt: str,
        response_model: type[T],
    ) -> T:
        del instructions, prompt  # non utilises par le stub : reponses figees

        call_index = self._call_counts.get(agent_name, 0)
        self._call_counts[agent_name] = call_index + 1

        try:
            responses = _STUB_RESPONSES[agent_name]
        except KeyError as exc:
            raise KeyError(f"Aucune reponse stub definie pour l'agent '{agent_name}'") from exc

        if isinstance(responses, list):
            payload = responses[min(call_index, len(responses) - 1)]
        else:
            payload = responses

        return response_model.model_validate(payload)


# ---------------------------------------------------------------------------
# Client reel (Azure OpenAI / Microsoft Foundry)
# ---------------------------------------------------------------------------


class AzureOpenAIStructuredChatClient:
    """Implementation reelle, basee sur `agent_framework.openai.OpenAIChatCompletionClient`.

    Un `Agent` distinct est cree (et mis en cache) par couple
    `(agent_name, response_model)`, avec
    `default_options={"response_format": response_model}` pour forcer une
    sortie JSON conforme au schema pydantic attendu.
    """

    def __init__(self, *, model: str, endpoint: str, api_version: str, credential: object) -> None:
        from agent_framework.openai import OpenAIChatCompletionClient

        self._chat_client = OpenAIChatCompletionClient(
            model=model,
            azure_endpoint=endpoint,
            api_version=api_version,
            credential=credential,
        )
        self._agents: dict[tuple[str, type], Any] = {}

    async def get_structured_response(
        self,
        *,
        agent_name: str,
        instructions: str,
        prompt: str,
        response_model: type[T],
    ) -> T:
        key = (agent_name, response_model)
        agent = self._agents.get(key)
        if agent is None:
            agent = self._chat_client.as_agent(
                name=agent_name,
                instructions=instructions,
                default_options={"response_format": response_model},
            )
            self._agents[key] = agent

        response = await agent.run(prompt)
        return response_model.model_validate_json(response.text)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_chat_client(settings: Settings, *, light: bool) -> StructuredChatClient:
    """Choisit le client structure : reel si Azure OpenAI est configure, sinon stub.

    `light=True` selectionne le deploiement "leger" (`AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT`,
    ex. gpt-4o-mini) ; `light=False` selectionne le deploiement "fort"
    (`AZURE_OPENAI_CHAT_DEPLOYMENT`, ex. gpt-4o) — voir SPEC.md section 2.
    """

    if not settings.use_real_azure_openai:
        return StubChatClient()

    from azure.identity import AzureCliCredential, DefaultAzureCredential

    assert settings.azure_openai_endpoint is not None  # garanti par use_real_azure_openai

    credential = AzureCliCredential() if settings.azure_auth_mode == "cli" else DefaultAzureCredential()
    model = settings.azure_openai_chat_deployment_light if light else settings.azure_openai_chat_deployment

    return AzureOpenAIStructuredChatClient(
        model=model,
        endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        credential=credential,
    )
