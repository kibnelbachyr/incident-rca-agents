// Types miroir de `src/models.py` (contrats pydantic, SPEC.md section 4) et
// des reponses de `src/api/*.py`. Tenus a jour manuellement : un seul jeu de
// contrats, cote backend, dont ce fichier reflete la forme JSON.

export interface TimelineEvent {
  time: string;
  event: string;
}

export interface LogAnalysis {
  timeline: TimelineEvent[];
  anomalies: string[];
  correlated_events: string[];
}

export interface Incident {
  titre: string;
  severite: string;
  services: string[];
  fenetre: string;
  symptomes: string[];
}

export interface KBMatch {
  id: string;
  similarite: number;
  resolution: string;
}

export interface KBMatches {
  matches: KBMatch[];
}

export interface RootCauseHypothesis {
  cause: string;
  raisonnement: string;
  confiance: number;
  preuves_manquantes: string[];
}

export interface RemediationPlan {
  immediat: string[];
  court_terme: string[];
  long_terme: string[];
}

export interface IncidentReport {
  titre: string;
  fenetre: string;
  impact: string;
  cause_racine: string;
  confiance: number;
  remediation: string[];
  precedent_lie: string | null;
  texte: string;
}

export interface SharedContext {
  raw_logs: string;
  log_analysis: LogAnalysis | null;
  incident: Incident | null;
  kb_matches: KBMatches | null;
  root_cause: RootCauseHypothesis | null;
  remediation_plan: RemediationPlan | null;
  report: IncidentReport | null;
  loop_count: number;
  root_cause_history: RootCauseHypothesis[];
  evidence_log: string[];
  approved: boolean | null;
  routing_note?: string;
}

export interface RemediationApprovalRequest {
  incident: Incident;
  root_cause: RootCauseHypothesis;
  kb_matches: KBMatches;
  message: string;
}

// --- src/api ---------------------------------------------------------------

export type ExecutorId =
  | "log_analyzer"
  | "incident_extractor"
  | "kb_search"
  | "root_cause"
  | "gather_evidence"
  | "human_approval"
  | "remediation"
  | "summary";

export interface StepPayload {
  executor_id: ExecutorId;
  context: SharedContext;
}

export interface MetaResponse {
  confidence_threshold: number;
  max_reflection_loops: number;
  kb_mode: string;
  use_real_azure_openai: boolean;
  cosmos_enabled: boolean;
}

export interface IncidentRecordSummary {
  id: string;
  started_at: string;
  finished_at: string;
  approved: boolean | null;
  titre: string | null;
  severite: string | null;
  cause: string | null;
  confiance: number | null;
}

export interface IncidentRecord {
  id: string;
  started_at: string;
  finished_at: string;
  approved: boolean | null;
  context: SharedContext;
}
