# Copyright (c) Microsoft. All rights reserved.

"""Contrats de donnees (pydantic) echanges entre l'orchestrateur et les agents.

Ces modeles sont la "source de verite" des schemas JSON definis dans SPEC.md
section 4. Chaque agent renvoie exclusivement un JSON valide selon l'un de ces
modeles (via `response_format` cote client de chat). L'orchestrateur accumule
ces sorties dans `SharedContext`, qui circule de noeud en noeud dans le graphe
`WorkflowBuilder`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. LogAnalyzer -> LogAnalysis
# ---------------------------------------------------------------------------


class TimelineEvent(BaseModel):
    """Un evenement normalise extrait des logs bruts."""

    time: str
    event: str


class LogAnalysis(BaseModel):
    """Sortie de l'agent `LogAnalyzer` (SPEC.md section 4.1)."""

    timeline: list[TimelineEvent]
    anomalies: list[str]
    correlated_events: list[str]


# ---------------------------------------------------------------------------
# 2. IncidentExtractor -> Incident
# ---------------------------------------------------------------------------


class Incident(BaseModel):
    """Sortie de l'agent `IncidentExtractor` (SPEC.md section 4.2)."""

    titre: str
    severite: str = Field(pattern=r"^SEV-[1-5]$")
    services: list[str]
    fenetre: str
    symptomes: list[str]


# ---------------------------------------------------------------------------
# 3. KBSearch -> KBMatches
# ---------------------------------------------------------------------------


class KBMatch(BaseModel):
    """Un precedent retourne par la base de connaissances."""

    id: str
    similarite: float = Field(ge=0.0, le=1.0)
    resolution: str


class KBMatches(BaseModel):
    """Sortie de l'agent `KBSearch` (SPEC.md section 4.3)."""

    matches: list[KBMatch] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 4. RootCause -> RootCauseHypothesis
# ---------------------------------------------------------------------------


class RootCauseHypothesis(BaseModel):
    """Sortie de l'agent `RootCause` (SPEC.md section 4.4).

    Si `confiance < CONFIDENCE_THRESHOLD`, `preuves_manquantes` doit lister ce
    que l'orchestrateur va aller chercher (boucle `GatherEvidence`).
    """

    cause: str
    raisonnement: str
    confiance: float = Field(ge=0.0, le=1.0)
    preuves_manquantes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5. Remediation -> RemediationPlan (derriere HITL)
# ---------------------------------------------------------------------------


class RemediationPlan(BaseModel):
    """Sortie de l'agent `Remediation` (SPEC.md section 4.5).

    Plan propose uniquement : aucune action n'est executee sur un vrai systeme.
    """

    immediat: list[str]
    court_terme: list[str]
    long_terme: list[str]


# ---------------------------------------------------------------------------
# 6. Summary -> IncidentReport
# ---------------------------------------------------------------------------


class IncidentReport(BaseModel):
    """Sortie de l'agent `Summary` (SPEC.md section 4.6 / scenario section 5).

    `texte` porte le rapport pret-a-coller (format scenario) ; les autres
    champs exposent les valeurs cles pour un affichage structure.
    """

    titre: str
    fenetre: str
    impact: str
    cause_racine: str
    confiance: float = Field(ge=0.0, le=1.0)
    remediation: list[str]
    precedent_lie: str | None = None
    texte: str


# ---------------------------------------------------------------------------
# Human-in-the-loop : porte de validation avant remediation
# ---------------------------------------------------------------------------


class RemediationApprovalRequest(BaseModel):
    """Donnees presentees a l'humain avant d'invoquer l'agent `Remediation`.

    Emis via `ctx.request_info(request_data=..., response_type=bool)` ; le
    workflow reste en pause tant qu'aucune reponse booleenne n'est recue.
    """

    incident: Incident
    root_cause: RootCauseHypothesis
    kb_matches: KBMatches
    message: str = "Valider le passage a la remediation ?"


# ---------------------------------------------------------------------------
# Contexte partage (orchestrateur) : grossit au fil du graphe
# ---------------------------------------------------------------------------


class SharedContext(BaseModel):
    """Contexte detenu par l'orchestrateur et transmis de noeud en noeud.

    Les agents sont sans etat : ils ne lisent/ecrivent jamais ce contexte
    directement, c'est l'orchestrateur (les `Executor`) qui le met a jour
    entre chaque appel d'agent.
    """

    raw_logs: str

    # Sorties successives des agents.
    log_analysis: LogAnalysis | None = None
    incident: Incident | None = None
    kb_matches: KBMatches | None = None
    root_cause: RootCauseHypothesis | None = None
    remediation_plan: RemediationPlan | None = None
    report: IncidentReport | None = None

    # Boucle de reflexion (bornee par MAX_REFLECTION_LOOPS).
    loop_count: int = 0
    root_cause_history: list[RootCauseHypothesis] = Field(default_factory=list)
    evidence_log: list[str] = Field(default_factory=list)

    # Porte de validation humaine.
    approved: bool | None = None
