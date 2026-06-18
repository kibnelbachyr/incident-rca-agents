# Copyright (c) Microsoft. All rights reserved.

"""Structured chat client abstraction used by the six agents.

Two implementations share the `StructuredChatClient` protocol:

- `StubChatClient`: deterministic responses replaying the demo scenario
  (SPEC.md section 6 / scenario-demo-incident-paiement.md), used when no
  usable Azure OpenAI endpoint is configured (offline mode).
- `AzureOpenAIStructuredChatClient`: real agents via
  `agent_framework.openai.OpenAIChatCompletionClient` + `as_agent(...)`,
  routed to Azure OpenAI / Microsoft Foundry via the `AZURE_OPENAI_*`
  variables (see SPEC.md section 3 and `.env.example`).

`get_chat_client(settings, light=..., scenario=...)` automatically picks
between the two based on `Settings.use_real_azure_openai` (DECISIONS.md #1
and #3); `scenario` selects the canned response set replayed by
`StubChatClient` (see `src.scenarios` for the registry of available
scenarios).
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from src.config import Settings

T = TypeVar("T", bound=BaseModel)


class StructuredChatClient(Protocol):
    """Minimal capability required by an agent: produce a JSON response
    validated against a pydantic model, given instructions and a prompt."""

    async def get_structured_response(
        self,
        *,
        agent_name: str,
        instructions: str,
        prompt: str,
        response_model: type[T],
    ) -> T: ...


# ---------------------------------------------------------------------------
# Deterministic stub (offline mode) — DECISIONS.md #4
# ---------------------------------------------------------------------------

# Canned responses keyed by scenario then by agent. Each agent entry is either
# a dict (single response, replayed on every call) or a list of dicts indexed
# by call number (the last element is reused beyond the list's length). The
# list form simulates the RootCause agent's reflection loop: 1st pass with low
# confidence (competing hypotheses), 2nd pass resolved after `GatherEvidence`.
_STUB_RESPONSES: dict[str, dict[str, dict[str, Any] | list[dict[str, Any]]]] = {
    "db_pool": {
        "LogAnalyzer": [
            # 1st pass: initial analysis of the raw logs.
            {
                "timeline": [
                    {"time": "14:00:11", "event": "Deployment payment-api v2.4.1 started (rolling, 6 pods, 90s window)"},
                    {"time": "14:00:12", "event": "Config applied — db.max_pool_size set to 20 (previous value: 40) via ConfigMap patch"},
                    {"time": "14:04:33", "event": "Rolling deployment complete — all 6 pods on v2.4.1"},
                    {"time": "14:16:02", "event": "DB pool utilisation crosses 70% threshold (first alert suppressed — below configured 85% limit)"},
                    {"time": "14:22:47", "event": "Pool 100% saturated: 20/20 connections acquired, 0 available"},
                    {"time": "14:23:15", "event": "First connection acquisition timeout after 5000ms — payment persistence failing"},
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
            # 2nd pass (GatherEvidence): focus on the config diff and the Stripe trajectory.
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
            # 1st pass: insufficient confidence, two competing hypotheses.
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
            # 2nd pass (after GatherEvidence): cause resolved, Stripe ruled out.
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
                "Set explicit connection acquisition timeout: hard limit 3000ms with structured error log and 503 response (currently unbounded)",
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
            "impact": "38% payment transaction failure rate at peak · ~3,400 failed transactions estimated",
            "cause_racine": (
                "Deployment v2.4.1 halved db.max_pool_size from 40 to 20 via ConfigMap patch. "
                "Pool exhausted under nominal load within 22 min. Stripe latency transient was a red herring — "
                "eliminated after targeted evidence gathering (Stripe recovered at 14:29; pool remained saturated until 14:41)."
            ),
            "confiance": 0.92,
            "remediation": [
                "IMMEDIATE  — Rollback v2.4.1, restore db.max_pool_size=40, drain stale connections, apply retry backoff",
                "SHORT-TERM — Pool utilisation alert >80%, acquisition timeout 3000ms, canary deployment policy, runbook update",
                "LONG-TERM  — CI infra config review gate, PgBouncer evaluation, capacity headroom dashboard",
            ],
            "precedent_lie": "INC-204 (identical root cause — pool config change — same resolution path)",
            "texte": (
                "INCIDENT REPORT — SEV-1\n"
                "═══════════════════════════════════════════════════\n"
                " Title    DB Pool Exhaustion — payment-api v2.4.1\n"
                " Window   14:23 → 14:41 UTC  (18 min resolved)\n"
                " Impact   38% payment failure rate · ~3,400 transactions lost\n"
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
                "  SHORT-TERM  Pool utilisation alert (>80%); timeout 3000ms\n"
                "              Canary deployment policy; runbook updated\n"
                "  LONG-TERM   CI infra config review gate; PgBouncer eval\n"
                "              Capacity headroom trending dashboard\n"
                "\n"
                "PRECEDENT  INC-204 — identical pattern, same resolution\n"
                "═══════════════════════════════════════════════════\n"
            ),
        },
    },
    "paypal_integration": {
        "LogAnalyzer": [
            # 1st pass: initial analysis, covers the 5 days up to the support escalation.
            {
                "timeline": [
                    {
                        "time": "2025-11-10 09:14:18",
                        "event": "Deployment payment-api v3.1.0 released to prod (rolling, 8 pods) — changelog: PayPal SDK 1.9→2.0 migration, webhook signature verification rewrite",
                    },
                    {
                        "time": "2025-11-10 09:24:03",
                        "event": "First webhook signature verification failure: header 'PAYPAL-TRANSMISSION-SIG' not found — event rejected (401)",
                    },
                    {
                        "time": "2025-11-10 11:02:14",
                        "event": "Order ORD-55012 stuck awaiting webhook confirmation (capture succeeded, IPN pending) — first stuck order",
                    },
                    {
                        "time": "2025-11-11 08:00:00",
                        "event": "Daily monitoring report: checkout success rate 99.3% (nominal) — no alert (metric covers synchronous checkout only)",
                    },
                    {
                        "time": "2025-11-12 19:05:27",
                        "event": "Order backlog reaches 41 orders in 'pending_confirmation' > 6h — no alert rule exists for this metric",
                    },
                    {
                        "time": "2025-11-13 10:12:51",
                        "event": "Support ticket #4471: customer reports 'paid but order shows pending'",
                    },
                    {
                        "time": "2025-11-14 09:18:36",
                        "event": "Third similar support ticket (#4502) this week — escalated to payment-api on-call",
                    },
                    {
                        "time": "2025-11-14 10:05:14",
                        "event": "On-call opens two hypotheses: (a) PayPal-side outage/API change, (b) payment-api regression",
                    },
                    {
                        "time": "2025-11-14 10:22:47",
                        "event": "status.paypal.com checked — no incidents reported in the last 7 days",
                    },
                    {
                        "time": "2025-11-14 11:40:19",
                        "event": "PayPal webhook retry exhaustion: txn=8GH40522 reaches max attempts (8/8) — delivery permanently failed",
                    },
                    {
                        "time": "2025-11-15 08:00:00",
                        "event": "New alert rule fires: pending_confirmation backlog > 80 for 24h (SEV-2) — first automated signal, 5 days post-deploy",
                    },
                ],
                "anomalies": [
                    "Checkout success rate stayed nominal (99.2–99.5%) throughout — the monitored metric covers only the synchronous checkout flow, not asynchronous webhook confirmation, masking the regression from automated alerting for 5 days",
                    "100% of inbound PayPal webhook signature verifications fail from the first event after deploy (09:24:03) onward — total, not intermittent or partial",
                    "Order backlog in 'pending_confirmation' grows monotonically from a baseline of ~29 to 94 (3.2×) over 5 days with no alert until the backlog manually crossed an 80-order threshold",
                    "No alert rule existed for webhook confirmation backlog prior to this incident — detection relied entirely on customer support tickets",
                ],
                "correlated_events": [
                    "payment-api v3.1.0 deploy (09:14:18, PayPal SDK migration + webhook signature rewrite) precedes the first signature failure (09:24:03) by under 10 minutes",
                    "status.paypal.com reports no incidents in the 7 days preceding investigation — weakens but does not eliminate an external PayPal-side cause specific to webhooks",
                    "Support escalation (5 days post-deploy) is the first human-triggered investigation; automated monitoring never flagged the regression",
                ],
            },
            # 2nd pass (GatherEvidence): focus on header casing and the application diff.
            {
                "timeline": [
                    {
                        "time": "2025-11-15 09:02:33",
                        "event": "Gateway access log sample: header received at the CDN edge as 'paypal-transmission-sig' (lowercase)",
                    },
                    {
                        "time": "2025-11-15 09:18:47",
                        "event": "Application code review: webhook verification reads request.headers['PAYPAL-TRANSMISSION-SIG'] — exact-case dict lookup",
                    },
                    {
                        "time": "2025-11-15 09:40:10",
                        "event": "Confirmed: API gateway/CDN edge normalises all headers to lowercase before forwarding to payment-api — case-sensitive lookup always misses",
                    },
                    {
                        "time": "2025-11-15 10:05:29",
                        "event": "Diff review: v3.1.0 webhook handler rewrite replaced case-insensitive header.get() with case-sensitive dict access, introduced at the SDK migration commit",
                    },
                    {
                        "time": "2025-11-15 10:30:00",
                        "event": "No corroborating report of a PayPal-wide webhook delivery incident found on any external channel during the 5-day window",
                    },
                ],
                "anomalies": [
                    "Header casing mismatch is deterministic and 100% reproducible: gateway always lowercases, application always looked up exact-case — every webhook was guaranteed to fail from the moment v3.1.0 deployed",
                    "v3.1.0 diff isolates a single behavioural change relevant to this failure: case-insensitive header.get() replaced by case-sensitive dict subscript access during the SDK migration rewrite",
                ],
                "correlated_events": [
                    "Gateway lowercase normalisation (infrastructure-level, unchanged) plus the new case-sensitive lookup (application-level, introduced by v3.1.0) together fully explain the 100% failure rate from 09:24:03 onward",
                    "No external PayPal status-page or support-channel corroboration of a webhook-specific outage at any point in the 5-day window — hypothesis (a) externally falsified",
                ],
            },
        ],
        "IncidentExtractor": {
            "titre": "SEV-2: PayPal webhook signature verification broken by payment-api v3.1.0 case-sensitive header regression",
            "severite": "SEV-2",
            "services": ["payment-api", "paypal-webhook", "order-service"],
            "fenetre": "2025-11-10 09:24 → 2025-11-15 11:08 UTC (5 days, resolved by hotfix)",
            "symptomes": [
                "100% of inbound PayPal webhook signature verifications rejected (401) from the first event after deploy",
                "Synchronous checkout success rate remained nominal (99.2–99.5%) — masked the regression from automated monitoring",
                "Order backlog in 'pending_confirmation' grew from a baseline of ~29 to 94 (3.2×) over 5 days",
                "PayPal webhook redelivery exhausted after 8/8 attempts — affected events permanently undelivered",
                "Customer support tickets reporting 'paid but order shows pending' were the only detection signal for the first 4 days",
            ],
        },
        "KBSearch": {
            "matches": [
                {
                    "id": "INC-241",
                    "similarite": 0.95,
                    "resolution": (
                        "Switched to a case-insensitive header lookup (header.get() instead of exact-case dict access) and "
                        "replayed pending events from the provider's retry queue. Root cause was identical: an SDK/handler "
                        "rewrite introduced a case-sensitive header lookup while the gateway normalises headers to lowercase."
                    ),
                },
                {
                    "id": "INC-223",
                    "similarite": 0.42,
                    "resolution": (
                        "Waited for provider-side resolution, temporarily failed over new critical transactions to a secondary "
                        "PSP, tracked via the public status page. Pattern mismatch here: status.paypal.com showed no incident "
                        "and the failure was 100% reproducible and deterministic from the deploy onward — inconsistent with a "
                        "transient provider-side degradation."
                    ),
                },
            ],
        },
        "RootCause": [
            # 1st pass: insufficient confidence, external vs internal hypothesis unresolved.
            {
                "cause": (
                    "Two competing hypotheses remain unresolved with current evidence: "
                    "(A) an undocumented PayPal-side degradation specific to webhook delivery, not visible on the public status page; "
                    "(B) a payment-api v3.1.0 regression in webhook signature verification introduced by the PayPal SDK migration"
                ),
                "raisonnement": (
                    "Both hypotheses are consistent with the observed symptoms. Hypothesis A is supported by precedent: INC-223 "
                    "shows PayPal has previously caused payment-side incidents through provider-side degradation alone, with no "
                    "internal code change required, and webhook-specific delivery problems are a known external failure mode not "
                    "always reflected on the general status page. Hypothesis B is supported by temporal correlation: the v3.1.0 "
                    "deploy at 09:14:18, which explicitly migrates the PayPal SDK and rewrites webhook signature verification, "
                    "precedes the first signature failure by under 10 minutes, and the failure is total (100%) rather than partial. "
                    "status.paypal.com shows no incident in the preceding 7 days, which weakens hypothesis A but does not rule out "
                    "a webhook-specific degradation invisible to the general status page. Precedent INC-241 matches hypothesis B "
                    "(header-casing regression introduced by a release); precedent INC-223 matches hypothesis A (genuine external "
                    "PayPal outage). The two precedents imply incompatible remediations: wait-and-failover vs. hotfix-and-replay. "
                    "Definitive discrimination requires: the raw header casing as received by the gateway versus as read by the "
                    "application code, a code-level diff of the v3.1.0 webhook handler rewrite, and any corroborating signal of a "
                    "PayPal-side webhook-specific incident beyond the general status page."
                ),
                "confiance": 0.5,
                "preuves_manquantes": [
                    "Raw HTTP header casing as received by the API gateway/CDN edge vs. as read by the application's signature verification code",
                    "Code-level diff of the v3.1.0 webhook handler rewrite (PayPal SDK migration)",
                    "Any corroborating signal of a PayPal-side webhook-specific incident beyond the general status page (support channels, other merchants)",
                ],
            },
            # 2nd pass (after GatherEvidence): cause resolved, external hypothesis ruled out.
            {
                "cause": (
                    "payment-api v3.1.0 replaced a case-insensitive header lookup with a case-sensitive dict access in the webhook "
                    "signature verification rewrite; the API gateway normalises all headers to lowercase, so the "
                    "'PAYPAL-TRANSMISSION-SIG' lookup missed on every single inbound webhook since the deploy"
                ),
                "raisonnement": (
                    "Evidence gathered in reflection loop 1 conclusively resolves the ambiguity: (1) the gateway access log sample "
                    "confirms the header arrives as 'paypal-transmission-sig' (lowercase); (2) application code review confirms the "
                    "verification reads request.headers['PAYPAL-TRANSMISSION-SIG'] with an exact-case dict lookup; (3) the v3.1.0 "
                    "diff shows this exact-case lookup replaced a prior case-insensitive header.get() call, introduced at the same "
                    "commit as the PayPal SDK migration; (4) no external channel (status page, support, other merchants) "
                    "corroborates a PayPal-side webhook incident at any point in the 5-day window. Hypothesis A (external PayPal "
                    "degradation) is eliminated: the failure is deterministic and 100% reproducible from a fixed infrastructure/"
                    "application mismatch, not a transient provider issue. Hypothesis B (payment-api regression) is confirmed. "
                    "Precedent INC-241 is a direct match: identical root cause (case-sensitive header lookup vs. lowercase-"
                    "normalising gateway), identical fix."
                ),
                "confiance": 0.93,
                "preuves_manquantes": [],
            },
        ],
        "Remediation": {
            "immediat": [
                "Deploy hotfix v3.1.1: replace the case-sensitive header dict access with a case-insensitive header.get() lookup in webhook signature verification",
                "Trigger reconciliation job to replay all backlogged PayPal webhook events (112 events in 'pending_confirmation') once the hotfix is live",
                "Manually confirm the highest-value stuck orders (oldest, highest amount) before the bulk reconciliation completes",
            ],
            "court_terme": [
                "Add a dedicated alert on 'pending_confirmation' backlog size and age (not just synchronous checkout success rate) — this incident took 5 days to surface because no async-confirmation metric was monitored",
                "Add a contract/integration test asserting webhook signature verification succeeds against lowercase-normalised headers, to catch gateway/application case-sensitivity mismatches before prod",
                "Update the deployment runbook: any change touching webhook/callback signature verification requires a synthetic end-to-end webhook test against the real gateway path before rollout",
            ],
            "long_terme": [
                "Standardise header access across all integrations (PayPal, future PSPs) through a single case-insensitive helper, eliminating this class of bug at the source",
                "Build a per-provider integration health dashboard tracking webhook delivery success rate distinctly from synchronous checkout success rate",
                "Build provider-side webhook delivery visibility (e.g., PayPal IPN dashboard) into on-call tooling, reducing reliance on the public status page alone",
            ],
        },
        "Summary": {
            "titre": "INCIDENT REPORT — SEV-2 — PayPal Webhook Signature Regression (payment-api v3.1.0)",
            "fenetre": "2025-11-10 09:24 → 2025-11-15 11:08 UTC (5 days, resolved by hotfix v3.1.1)",
            "impact": "100% of inbound PayPal webhook confirmations rejected for 5 days · 112 orders stuck in 'pending_confirmation' (3.2× baseline) · first detected via customer support tickets, not automated monitoring",
            "cause_racine": (
                "payment-api v3.1.0 migrated the PayPal SDK and rewrote webhook signature verification, replacing a "
                "case-insensitive header lookup with a case-sensitive dict access. The API gateway normalises all headers to "
                "lowercase, so the signature header lookup missed on every inbound webhook from the moment of deploy. A genuine "
                "past PayPal outage (INC-223) was considered and eliminated after gathering evidence — this failure was "
                "deterministic and 100% reproducible, not a transient provider-side degradation."
            ),
            "confiance": 0.93,
            "remediation": [
                "IMMEDIATE  — Hotfix v3.1.1 (case-insensitive header lookup), replay 112 backlogged webhook events, manually verify highest-value stuck orders",
                "SHORT-TERM — Alert on async confirmation backlog size/age, webhook signature contract test against gateway-normalised headers, runbook update for webhook-touching changes",
                "LONG-TERM  — Shared case-insensitive header helper across integrations, per-provider webhook health dashboard, provider-side delivery visibility tooling",
            ],
            "precedent_lie": "INC-241 (identical root cause — case-sensitive header lookup vs. lowercase-normalising gateway — same resolution path)",
            "texte": (
                "INCIDENT REPORT — SEV-2\n"
                "═══════════════════════════════════════════════════\n"
                " Title    PayPal Webhook Signature Regression — payment-api v3.1.0\n"
                " Window   2025-11-10 09:24 → 2025-11-15 11:08 UTC (5 days, hotfixed)\n"
                " Impact   100% webhook confirmations rejected · 112 orders stuck\n"
                " Decision Hotfix v3.1.1 approved and applied\n"
                "───────────────────────────────────────────────────\n"
                "\n"
                "ROOT CAUSE  (confidence 0.93 / threshold 0.75)\n"
                "Deployment v3.1.0 migrated the PayPal SDK (1.9 → 2.0) and\n"
                "rewrote webhook signature verification, replacing a\n"
                "case-insensitive header.get() lookup with a case-sensitive\n"
                "dict access. The API gateway normalises all headers to\n"
                "lowercase before forwarding, so the 'PAYPAL-TRANSMISSION-SIG'\n"
                "lookup missed on every single inbound webhook from 09:24:03\n"
                "onward. Synchronous checkout stayed nominal (99.2-99.5%),\n"
                "masking the regression from automated monitoring for 5 days.\n"
                "A genuine past PayPal outage (INC-223) was investigated as\n"
                "hypothesis A and eliminated: the failure was 100% reproducible\n"
                "and deterministic, not a transient provider degradation.\n"
                "\n"
                "AI ORCHESTRATION TRACE\n"
                "  Loop 1 → Root Cause confidence: 0.50  (below 0.75)\n"
                "    Missing: gateway header casing, v3.1.0 diff, external corroboration\n"
                "  Loop 2 → Root Cause confidence: 0.93  ✓ threshold met\n"
                "    PayPal outage hypothesis eliminated. Header regression confirmed.\n"
                "\n"
                "REMEDIATION (proposed — not executed on live systems)\n"
                "  IMMEDIATE   Hotfix v3.1.1: case-insensitive header lookup\n"
                "              Replay 112 backlogged webhook events; verify top orders\n"
                "  SHORT-TERM  Async backlog alert; webhook signature contract test\n"
                "              Runbook update for webhook-touching changes\n"
                "  LONG-TERM   Shared header helper across integrations\n"
                "              Per-provider webhook health dashboard\n"
                "\n"
                "PRECEDENT  INC-241 — identical pattern, same resolution\n"
                "═══════════════════════════════════════════════════\n"
            ),
        },
    },
}


class StubChatClient:
    """Deterministic "stub" client for running the demo offline.

    Makes no network calls: returns canned responses that satisfy the
    pydantic contracts in `src/models.py` and reproduce the selected demo
    scenario (`scenario`, cf. `src.scenarios`), including the `RootCause`
    reflection loop (1st pass low confidence, 2nd pass high confidence after
    `GatherEvidence`).
    """

    def __init__(self, scenario: str = "db_pool") -> None:
        self._scenario = scenario
        self._call_counts: dict[str, int] = {}

    async def get_structured_response(
        self,
        *,
        agent_name: str,
        instructions: str,
        prompt: str,
        response_model: type[T],
    ) -> T:
        del instructions, prompt  # unused by the stub: canned responses

        call_index = self._call_counts.get(agent_name, 0)
        self._call_counts[agent_name] = call_index + 1

        try:
            scenario_responses = _STUB_RESPONSES[self._scenario]
        except KeyError as exc:
            raise KeyError(f"No stub response defined for scenario '{self._scenario}'") from exc

        try:
            responses = scenario_responses[agent_name]
        except KeyError as exc:
            raise KeyError(
                f"No stub response defined for agent '{agent_name}' (scenario '{self._scenario}')"
            ) from exc

        if isinstance(responses, list):
            payload = responses[min(call_index, len(responses) - 1)]
        else:
            payload = responses

        return response_model.model_validate(payload)


# ---------------------------------------------------------------------------
# Real client (Azure OpenAI / Microsoft Foundry)
# ---------------------------------------------------------------------------


class AzureOpenAIStructuredChatClient:
    """Real implementation, based on `agent_framework.openai.OpenAIChatCompletionClient`.

    A distinct `Agent` is created (and cached) per `(agent_name,
    response_model)` pair, with `default_options={"response_format":
    response_model}` to force a JSON output matching the expected pydantic
    schema.
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
            # id=agent_name (instead of the random uuid4 default, cf.
            # agent_framework._agents.BaseAgent.__init__): the framework's OTel
            # instrumentation sources `gen_ai.agent.id` from `Agent.id`, not
            # `Agent.name` (agent_framework.observability.AgentTelemetryLayer). A
            # stable id is required for traces to attach to the Foundry External
            # Agent registration (scripts/register_foundry_agents.py,
            # docs/deployment.md #8.13).
            agent = self._chat_client.as_agent(
                id=agent_name,
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


def get_chat_client(settings: Settings, *, light: bool, scenario: str = "db_pool") -> StructuredChatClient:
    """Picks the structured client: real if Azure OpenAI is configured, stub otherwise.

    `light=True` selects the "light" deployment (`AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT`,
    e.g. gpt-4o-mini); `light=False` selects the "strong" deployment
    (`AZURE_OPENAI_CHAT_DEPLOYMENT`, e.g. gpt-4o) — see SPEC.md section 2.
    `scenario` only applies to the offline stub (cf. `StubChatClient`); the
    real client doesn't need it, since the content comes from the model itself.
    """

    if not settings.use_real_azure_openai:
        return StubChatClient(scenario=scenario)

    from azure.identity import AzureCliCredential, DefaultAzureCredential

    assert settings.azure_openai_endpoint is not None  # guaranteed by use_real_azure_openai

    credential = AzureCliCredential() if settings.azure_auth_mode == "cli" else DefaultAzureCredential()
    model = settings.azure_openai_chat_deployment_light if light else settings.azure_openai_chat_deployment

    return AzureOpenAIStructuredChatClient(
        model=model,
        endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        credential=credential,
    )
