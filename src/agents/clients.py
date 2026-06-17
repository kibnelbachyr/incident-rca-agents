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
                {"time": "14:00:11", "event": "Deployment payment-api v2.4.1 started (rolling, 6 pods, 90s window)"},
                {"time": "14:00:12", "event": "Config applied — db.max_pool_size set to 20 (previous value: 40) via ConfigMap patch"},
                {"time": "14:04:33", "event": "Rolling deployment complete — all 6 pods on v2.4.1"},
                {"time": "14:16:02", "event": "DB pool utilisation crosses 70% threshold (first alert suppressed — below configured 85% limit)"},
                {"time": "14:22:47", "event": "Pool 100% saturated: 20/20 connections acquired, 0 available"},
                {"time": "14:23:15", "event": "First connection acquisition timeout after 5 000ms — payment persistence failing"},
                {"time": "14:23:31", "event": "Stripe API latency: 780ms p95 (baseline 600ms, +30% deviation)"},
                {"time": "14:24:50", "event": "Error rate at 38% over 60s window — SEV-1 threshold exceeded"},
                {"time": "14:26:30", "event": "Client retry storm: inbound traffic 3.4× baseline, amplifying pool backpressure"},
                {"time": "14:29:18", "event": "Stripe API latency returns to 640ms — within normal variance"},
            ],
            "anomalies": [
                "DB connection pool: 70% → 100% saturation in under 7 minutes (14:16–14:22), followed by immediate cascading persistence failures",
                "Payment error rate: 0.18% → 38% in 25 minutes — catastrophic success rate degradation",
                "Client retry storm at 3.4× baseline — positive feedback loop amplifying already saturated pool",
                "Stripe gateway latency transient spike +30% (14:23–14:29), self-resolved — temporal overlap with error surge but independent trajectory",
                "Connection acquisition timeouts unbounded (no explicit timeout configured) — requests block indefinitely",
            ],
            "correlated_events": [
                "Deployment v2.4.1 (14:00:11) preceded pool saturation (14:22:47) by 22 min 36s — consistent with load accumulation under halved pool capacity",
                "db.max_pool_size change applied at the exact deployment timestamp: the only infrastructure delta between v2.4.0 and v2.4.1 visible in logs",
                "Stripe latency spike (14:23–14:29) coincides with error surge but self-resolves: insufficient to explain 18-minute persistence of saturation",
            ],
        },
        # 2e passage (GatherEvidence) : focus sur le diff de config et la trajectoire Stripe.
        {
            "timeline": [
                {"time": "14:00:12", "event": "ConfigMap diff confirmed: db.max_pool_size 40 → 20 in v2.4.1 (only config change)"},
                {"time": "14:23:31", "event": "Stripe API latency: 780ms p95 (single spike, within Stripe's documented variance range)"},
                {"time": "14:24:33", "event": "Stripe API latency: 820ms (peak value observed, self-correcting)"},
                {"time": "14:29:18", "event": "Stripe API latency: 640ms — fully normalised, back to baseline"},
                {"time": "14:30:05", "event": "DB pool: still 100% saturated at 14:30, 1 minute after Stripe normalised — no correlation"},
                {"time": "14:35:47", "event": "On-call diff review: v2.4.1 ConfigMap confirms db.max_pool_size was the sole change"},
            ],
            "anomalies": [
                "Stripe latency normalised (640ms) at 14:29 but pool saturation persisted until rollback at 14:41 — 12-minute gap eliminates Stripe as causal factor",
                "v2.4.1 ConfigMap diff: db.max_pool_size is the only infrastructure change — no other config variables modified",
            ],
            "correlated_events": [
                "Stripe recovery (14:29) did NOT correlate with incident recovery — Stripe is not the root cause",
                "Pool saturation onset ~22 min post-deploy matches expected depletion under halved capacity (~18 TPS nominal load)",
            ],
        },
    ],
    "IncidentExtractor": {
        "titre": "SEV-1: DB pool exhaustion following payment-api v2.4.1 deployment",
        "severite": "SEV-1",
        "services": ["payment-api", "db-pool", "postgres-primary"],
        "fenetre": "14:23 → 14:41 UTC (18 minutes, resolved by rollback)",
        "symptomes": [
            "DB connection pool saturated at 100% (20/20) — zero connections available for 18 minutes",
            "Payment transaction persistence failures: 38% error rate at peak (vs 0.18% baseline)",
            "Client retry storm amplifying inbound load to 3.4× baseline, worsening pool backpressure",
            "Connection acquisition timeouts unbounded — no hard limit configured, requests queued indefinitely",
            "Stripe API latency transient (+30%) — self-resolved, investigated and ruled out as causal factor",
        ],
    },
    "KBSearch": {
        "matches": [
            {
                "id": "INC-204",
                "similarite": 0.98,
                "resolution": (
                    "Rollback deployment to v2.4.0 and restore db.max_pool_size=40 via emergency ConfigMap patch. "
                    "Root cause was identical: ConfigMap change halved the pool, exhausting connections under nominal load. "
                    "Prevention applied: mandatory infrastructure config review gate added to CI pipeline."
                ),
            },
            {
                "id": "INC-187",
                "similarite": 0.52,
                "resolution": (
                    "Deployed circuit breaker with exponential backoff on Stripe payment processor calls. "
                    "Root cause: external processor degradation causing cascading timeouts and connection hold-time spikes. "
                    "Pattern mismatch here: Stripe recovered independently; pool saturation persisted — this precedent does not apply."
                ),
            },
        ],
    },
    "RootCause": [
        # 1er passage : confiance insuffisante, deux hypotheses concurrentes.
        {
            "cause": (
                "Two competing hypotheses remain unresolved with current evidence: "
                "(A) db.max_pool_size halved by v2.4.1 ConfigMap patch, saturating the pool under nominal load; "
                "(B) Stripe gateway degradation causing connection hold-time spikes that exhaust the pool via backpressure"
            ),
            "raisonnement": (
                "Both hypotheses explain the pool saturation and error surge. The v2.4.1 deployment at 14:00 halved "
                "db.max_pool_size from 40 to 20 immediately before the incident window — a strong temporal correlation. "
                "Simultaneously, Stripe API latency elevated to 780ms at 14:23 (+30%), which could independently "
                "extend transaction hold-times and exhaust connections via a different mechanism. "
                "Precedent INC-204 matches hypothesis A (pool config change, same resolution). "
                "Precedent INC-187 matches hypothesis B (Stripe degradation, different resolution). "
                "The two precedents point to opposite root causes and therefore incompatible remediation strategies. "
                "Definitive discrimination requires: the exact pool config diff from the v2.4.1 ConfigMap, "
                "and the Stripe latency trajectory after 14:26 — whether it self-resolved while the pool remained "
                "saturated is the critical discriminator between the two hypotheses."
            ),
            "confiance": 0.55,
            "preuves_manquantes": [
                "v2.4.1 ConfigMap diff: confirm db.max_pool_size value before and after deployment",
                "Stripe latency trajectory after 14:26 — did it recover while pool remained saturated?",
                "DB pool utilisation trend between 14:04 (deploy complete) and 14:16 (70% threshold) to model depletion rate",
            ],
        },
        # 2e passage (après GatherEvidence) : cause tranchée, Stripe écarté.
        {
            "cause": (
                "Deployment payment-api v2.4.1 reduced db.max_pool_size from 40 to 20 via ConfigMap patch, "
                "exhausting the DB connection pool under nominal production load within 22 minutes"
            ),
            "raisonnement": (
                "Evidence gathered in reflection loop 1 conclusively resolves the ambiguity: "
                "(1) v2.4.1 ConfigMap diff confirms db.max_pool_size reduced 40→20 — the only infrastructure change in this deployment. "
                "(2) Stripe API latency returned to baseline (640ms) at 14:29, yet pool saturation persisted until rollback at 14:41. "
                "The 12-minute gap between Stripe recovery and incident resolution eliminates hypothesis B entirely: "
                "if Stripe were the cause, incident recovery would have followed Stripe's normalisation. It did not. "
                "(3) The 22-minute depletion window is mechanistically consistent with ~18 TPS nominal payment load "
                "exhausting 20 connections, whereas 40 connections would have provided sufficient headroom. "
                "Hypothesis B (Stripe degradation) is eliminated. Hypothesis A (pool config change) is confirmed. "
                "Precedent INC-204 is a direct match: identical root cause, identical resolution path."
            ),
            "confiance": 0.92,
            "preuves_manquantes": [],
        },
    ],
    "Remediation": {
        "immediat": [
            "Rollback payment-api to v2.4.0 OR apply emergency ConfigMap patch restoring db.max_pool_size=40 without full rollback (faster, lower risk)",
            "Drain and reset DB connection pool: force-close stale acquired connections to unblock recovery immediately",
            "Apply client-side backoff config: exponential backoff, max 3 retries, 2s base delay — suppress retry storm",
        ],
        "court_terme": [
            "Add Prometheus alert: pool utilisation >80% for >60s triggers PagerDuty (currently no alert on this metric — first notification came from users)",
            "Set explicit connection acquisition timeout: hard limit 3 000ms with structured error log and 503 response (currently unbounded)",
            "Update deployment runbook: any ConfigMap change to db.*, worker_count, or queue_depth requires load-test sign-off before prod rollout",
            "Add automated canary: 5% traffic to new version for 10 min, automatic rollback if error rate >2%",
        ],
        "long_terme": [
            "Introduce mandatory infrastructure config review gate in CI pipeline: changes to pool, worker, or queue parameters require Platform team approval",
            "Evaluate PgBouncer connection pooler to decouple application pool config from database connection limits",
            "Implement connection pool headroom trending dashboard: visualise capacity buffer over time to catch erosion before exhaustion",
        ],
    },
    "Summary": {
        "titre": "INCIDENT SEV-1 — DB Pool Exhaustion (payment-api v2.4.1)",
        "fenetre": "14:23 → 14:41 UTC (18 min, resolved by rollback)",
        "impact": "38% payment transaction failure rate at peak · ~3 400 failed transactions estimated",
        "cause_racine": (
            "Deployment v2.4.1 halved db.max_pool_size from 40 to 20 via ConfigMap patch. "
            "Pool exhausted under nominal load within 22 min. Stripe latency transient was a red herring — "
            "eliminated after targeted evidence gathering (Stripe recovered at 14:29; pool remained saturated until 14:41)."
        ),
        "confiance": 0.92,
        "remediation": [
            "IMMEDIATE  — Rollback v2.4.1, restore db.max_pool_size=40, drain stale connections, apply retry backoff",
            "SHORT-TERM — Pool utilisation alert >80%, acquisition timeout 3 000ms, canary deployment policy, runbook update",
            "LONG-TERM  — CI infra config review gate, PgBouncer evaluation, capacity headroom dashboard",
        ],
        "precedent_lie": "INC-204 (identical root cause — pool config change — same resolution path)",
        "texte": (
            "INCIDENT REPORT — SEV-1\n"
            "═══════════════════════════════════════════════════\n"
            " Title    DB Pool Exhaustion — payment-api v2.4.1\n"
            " Window   14:23 → 14:41 UTC  (18 min resolved)\n"
            " Impact   38% payment failure rate · ~3 400 transactions lost\n"
            " Decision Rollback approved and applied\n"
            "───────────────────────────────────────────────────\n"
            "\n"
            "ROOT CAUSE  (confidence 0.92 / threshold 0.75)\n"
            "Deployment v2.4.1 halved db.max_pool_size from 40 to 20\n"
            "via ConfigMap patch — the only infrastructure change in\n"
            "this release. Under nominal production load (~18 TPS), the\n"
            "pool exhausted within 22 minutes, blocking all transaction\n"
            "persistence. A Stripe API latency transient (+30%) was\n"
            "investigated as hypothesis B and eliminated: Stripe recovered\n"
            "at 14:29 while pool saturation persisted until 14:41 — a\n"
            "12-minute gap that rules out Stripe as the causal factor.\n"
            "\n"
            "AI ORCHESTRATION TRACE\n"
            "  Loop 1 → Root Cause confidence: 0.55  (below 0.75)\n"
            "    Missing: pool diff, Stripe trajectory post-14:26\n"
            "  Loop 2 → Root Cause confidence: 0.92  ✓ threshold met\n"
            "    Stripe hypothesis eliminated. DB pool config confirmed.\n"
            "\n"
            "REMEDIATION (proposed — not executed on live systems)\n"
            "  IMMEDIATE   Rollback to v2.4.0; restore db.max_pool_size=40\n"
            "              Drain stale connections; apply client retry backoff\n"
            "  SHORT-TERM  Pool utilisation alert (>80%); timeout 3 000ms\n"
            "              Canary deployment policy; runbook updated\n"
            "  LONG-TERM   CI infra config review gate; PgBouncer eval\n"
            "              Capacity headroom trending dashboard\n"
            "\n"
            "PRECEDENT  INC-204 — identical pattern, same resolution\n"
            "═══════════════════════════════════════════════════\n"
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
