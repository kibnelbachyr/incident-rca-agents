import type {
  ExecutorId,
  Incident,
  IncidentReport,
  KBMatches,
  LogAnalysis,
  MetaResponse,
  RemediationApprovalRequest,
  RemediationPlan,
  RootCauseHypothesis,
  SharedContext,
  StepPayload,
} from "../types";
import ApprovalCard from "./ApprovalCard";
import ConfidenceBar from "./ConfidenceBar";
import type { Phase } from "./PipelineHUD";

const STEP_TITLES: Record<ExecutorId, string> = {
  log_analyzer: "Log Analyzer",
  incident_extractor: "Incident Extractor",
  kb_search: "KB Search",
  root_cause: "Root Cause Analysis",
  gather_evidence: "Reflection Loop — Gather Evidence",
  human_approval: "Human Approval — Rejected",
  remediation: "Remediation Plan (proposed)",
  summary: "Final Report",
};

const STEP_CODES: Record<ExecutorId, string> = {
  log_analyzer: "01",
  incident_extractor: "02",
  kb_search: "03",
  root_cause: "04",
  gather_evidence: "RX",
  human_approval: "HITL",
  remediation: "05",
  summary: "06",
};

interface DetailPanelProps {
  step: StepPayload | null;
  stepIndex: number | null;
  totalSteps: number;
  onPrev: () => void;
  onNext: () => void;
  meta: MetaResponse | null;
  phase: Phase;
  approvalRequest: RemediationApprovalRequest | null;
  onApprove: () => void;
  onReject: () => void;
}

export default function DetailPanel({
  step,
  stepIndex,
  totalSteps,
  onPrev,
  onNext,
  meta,
  phase,
  approvalRequest,
  onApprove,
  onReject,
}: DetailPanelProps) {
  if (approvalRequest && phase === "awaiting_approval") {
    return (
      <div className="detail-panel detail-panel--alert">
        <DetailHeader code="HITL" title="Human Approval Required" status="Action required" alert />
        <div className="detail-panel__body">
          <ApprovalCard
            request={approvalRequest}
            confidenceThreshold={meta?.confidence_threshold ?? 0.75}
            disabled={false}
            onApprove={onApprove}
            onReject={onReject}
          />
        </div>
      </div>
    );
  }

  if (!step) {
    return (
      <div className="detail-panel">
        <DetailHeader code="--" title="Standby" status="Idle" />
        <div className="detail-panel__body">
          <p className="empty">
            Awaiting orchestration start. Run the diagnostic to begin streaming live agent output here.
          </p>
        </div>
      </div>
    );
  }

  const { executor_id, context } = step;

  return (
    <div className="detail-panel">
      <DetailHeader
        code={STEP_CODES[executor_id]}
        title={STEP_TITLES[executor_id] ?? executor_id}
        status="Online"
        nav={stepIndex !== null ? { index: stepIndex, total: totalSteps, onPrev, onNext } : undefined}
      />
      <div className="detail-panel__body">{renderBody(executor_id, context, meta)}</div>
    </div>
  );
}

interface DetailNav {
  index: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
}

function DetailHeader({
  code,
  title,
  status,
  alert,
  nav,
}: {
  code: string;
  title: string;
  status: string;
  alert?: boolean;
  nav?: DetailNav;
}) {
  return (
    <div className="detail-panel__header">
      <span className="detail-panel__code">{code}</span>
      <div className="detail-panel__heading">
        <span className="detail-panel__title">{title}</span>
        <span className="detail-panel__status">{status}</span>
      </div>
      {nav && (
        <div className="detail-panel__nav">
          <button
            type="button"
            className="detail-panel__nav-btn"
            onClick={nav.onPrev}
            disabled={nav.index <= 0}
            aria-label="Previous step"
          >
            ‹
          </button>
          <span className="detail-panel__nav-count">
            {nav.index + 1} / {nav.total}
          </span>
          <button
            type="button"
            className="detail-panel__nav-btn"
            onClick={nav.onNext}
            disabled={nav.index >= nav.total - 1}
            aria-label="Next step"
          >
            ›
          </button>
        </div>
      )}
      {alert && <span className="badge badge--low">HITL</span>}
    </div>
  );
}

function renderBody(executorId: ExecutorId, context: SharedContext, meta: MetaResponse | null) {
  switch (executorId) {
    case "log_analyzer":
      return context.log_analysis ? <LogAnalysisView data={context.log_analysis} /> : null;
    case "incident_extractor":
      return context.incident ? <IncidentView data={context.incident} /> : null;
    case "kb_search":
      return context.kb_matches ? <KBMatchesView data={context.kb_matches} /> : null;
    case "root_cause":
      return context.root_cause ? (
        <RootCauseView data={context.root_cause} meta={meta} loopCount={context.loop_count} history={context.root_cause_history} />
      ) : null;
    case "gather_evidence":
      return <GatherEvidenceView context={context} meta={meta} />;
    case "remediation":
      return context.remediation_plan ? <RemediationPlanView data={context.remediation_plan} /> : null;
    case "summary":
      return context.report ? <SummaryView data={context.report} meta={meta} /> : null;
    case "human_approval":
      return <RejectionView />;
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Event type classifier for timeline dots
// ---------------------------------------------------------------------------

function classifyEvent(text: string): "deploy" | "config" | "error" | "warning" | "stripe" | "default" {
  const t = text.toLowerCase();
  if (t.includes("deploy") || t.includes("rolling") || t.includes("rollback")) return "deploy";
  if (t.includes("configmap") || t.includes("config") || t.includes("diff")) return "config";
  if (t.includes("error") || t.includes("failure") || t.includes("timeout") || t.includes("lost") || t.includes("block")) return "error";
  if (t.includes("stripe") || t.includes("latency") || t.includes("820") || t.includes("780") || t.includes("640")) return "stripe";
  if (t.includes("saturate") || t.includes("100%") || t.includes("storm") || t.includes("retry") || t.includes("crosses") || t.includes("alert")) return "warning";
  return "default";
}

// ---------------------------------------------------------------------------
// LogAnalysisView
// ---------------------------------------------------------------------------

function LogAnalysisView({ data }: { data: LogAnalysis }) {
  return (
    <div className="log-analysis-layout">
      <section className="log-section">
        <h4>Reconstructed Timeline</h4>
        <ul className="timeline-rich">
          {data.timeline.map((item, i) => {
            const type = classifyEvent(item.event);
            return (
              <li key={i} className={`timeline-rich__entry timeline-rich__entry--${type}`}>
                <span className="timeline-rich__dot" />
                <span className="timeline-rich__time">{item.time}</span>
                <span className="timeline-rich__text">{item.event}</span>
              </li>
            );
          })}
        </ul>
      </section>

      <div className="log-aside">
        <section className="log-section">
          <h4>Detected Anomalies</h4>
          <ul className="anomaly-list">
            {data.anomalies.map((item, i) => (
              <li key={i} className="anomaly-list__item">
                <span className="anomaly-list__icon">⚠</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="log-section">
          <h4>Correlated Events</h4>
          <ul className="correlation-list">
            {data.correlated_events.map((item, i) => (
              <li key={i} className="correlation-list__item">
                <span className="correlation-list__arrow">→</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// IncidentView
// ---------------------------------------------------------------------------

function IncidentView({ data }: { data: Incident }) {
  return (
    <div className="incident-layout">
      <div className="incident-header">
        <span className={`sev-pill sev-pill--${data.severite}`}>{data.severite}</span>
        <span className="incident-title">{data.titre}</span>
      </div>

      <div className="incident-meta">
        <div className="incident-meta__item">
          <span className="incident-meta__label">Window</span>
          <span className="incident-meta__value">{data.fenetre}</span>
        </div>
        <div className="incident-meta__item">
          <span className="incident-meta__label">Services</span>
          <span className="incident-meta__value">
            {data.services.map((svc) => (
              <span key={svc} className="service-chip">{svc}</span>
            ))}
          </span>
        </div>
      </div>

      <section className="log-section">
        <h4>Symptoms</h4>
        <ul className="symptom-list">
          {data.symptomes.map((item, i) => (
            <li key={i} className="symptom-list__item">
              <span className="symptom-list__icon">▸</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// KBMatchesView
// ---------------------------------------------------------------------------

function KBMatchesView({ data }: { data: KBMatches }) {
  if (data.matches.length === 0) {
    return <p className="empty">No matching precedent found in the knowledge base.</p>;
  }
  return (
    <div className="kb-cards">
      {data.matches.map((match) => {
        const pct = Math.round(match.similarite * 100);
        const strength = pct >= 90 ? "strong" : pct >= 60 ? "moderate" : "weak";
        return (
          <div key={match.id} className={`kb-card kb-card--${strength}`}>
            <div className="kb-card__header">
              <span className="kb-card__id">{match.id}</span>
              <span className={`kb-card__strength kb-card__strength--${strength}`}>
                {strength === "strong" ? "STRONG MATCH" : strength === "moderate" ? "PARTIAL MATCH" : "WEAK MATCH"}
              </span>
              <span className="kb-card__pct">{pct}%</span>
            </div>
            <div className="kb-card__bar-track">
              <div
                className={`kb-card__bar-fill kb-card__bar-fill--${strength}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="kb-card__resolution">{match.resolution}</p>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RootCauseView
// ---------------------------------------------------------------------------

function RootCauseView({
  data,
  meta,
  loopCount,
  history,
}: {
  data: RootCauseHypothesis;
  meta: MetaResponse | null;
  loopCount: number;
  history: RootCauseHypothesis[];
}) {
  const threshold = meta?.confidence_threshold ?? 0.75;
  const maxLoops = meta?.max_reflection_loops ?? 2;
  const willLoop = data.confiance < threshold && loopCount < maxLoops;
  const isPass2 = history.length >= 2;

  return (
    <div className="root-cause-layout">
      {isPass2 && history.length > 0 && (
        <div className="loop-badge">
          Loop {history.length} / {maxLoops} — re-analysis complete
        </div>
      )}

      <div className="confidence-display">
        <div className="confidence-display__number">
          <span
            className={`confidence-display__value ${data.confiance >= threshold ? "confidence-display__value--ok" : "confidence-display__value--low"}`}
          >
            {(data.confiance * 100).toFixed(0)}
            <span className="confidence-display__unit">%</span>
          </span>
          <span className="confidence-display__label">Confidence</span>
        </div>
        <div className="confidence-display__bar">
          <ConfidenceBar value={data.confiance} threshold={threshold} />
        </div>
      </div>

      <div className="cause-callout">
        <span className="cause-callout__label">Root cause identified</span>
        <p className="cause-callout__text">{data.cause}</p>
      </div>

      <section className="log-section">
        <h4>Reasoning</h4>
        <p className="reasoning-text">{data.raisonnement}</p>
      </section>

      {willLoop ? (
        <div className="verdict-banner verdict-banner--loop">
          <span className="verdict-banner__icon">↩</span>
          <div>
            <strong>Confidence {data.confiance.toFixed(2)} below threshold {threshold.toFixed(2)}</strong>
            <p>Orchestrator routing to evidence gathering — loop {loopCount + 1}/{maxLoops}</p>
            {data.preuves_manquantes.length > 0 && (
              <div className="evidence-targets">
                {data.preuves_manquantes.map((item, i) => (
                  <span key={i} className="evidence-tag">{item}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className={`verdict-banner ${data.confiance >= threshold ? "verdict-banner--ok" : "verdict-banner--exhausted"}`}>
          <span className="verdict-banner__icon">{data.confiance >= threshold ? "✓" : "⚡"}</span>
          <div>
            <strong>
              {data.confiance >= threshold
                ? `Confidence ${data.confiance.toFixed(2)} ≥ threshold ${threshold.toFixed(2)}`
                : `Reflection budget exhausted (${maxLoops}/${maxLoops} loops)`}
            </strong>
            <p>Proceeding to human approval gate</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// GatherEvidenceView
// ---------------------------------------------------------------------------

function GatherEvidenceView({ context, meta }: { context: SharedContext; meta: MetaResponse | null }) {
  const maxLoops = meta?.max_reflection_loops ?? 2;
  const prevHypothesis = context.root_cause_history.length > 0
    ? context.root_cause_history[context.root_cause_history.length - 1]
    : null;

  return (
    <div className="gather-layout">
      {context.routing_note && (
        <div className="routing-note">
          <span className="routing-note__icon">↩</span>
          <p>{context.routing_note}</p>
        </div>
      )}

      <div className="gather-progress">
        <span className="gather-progress__label">Reflection loop</span>
        <span className="gather-progress__value">{context.loop_count} / {maxLoops}</span>
      </div>

      {prevHypothesis && prevHypothesis.preuves_manquantes.length > 0 && (
        <section className="log-section">
          <h4>Investigation Targets</h4>
          <div className="evidence-targets">
            {prevHypothesis.preuves_manquantes.map((item, i) => (
              <span key={i} className="evidence-tag">{item}</span>
            ))}
          </div>
        </section>
      )}

      {context.log_analysis && context.log_analysis.correlated_events.length > 0 && (
        <section className="log-section">
          <h4>New Findings</h4>
          <ul className="correlation-list">
            {context.log_analysis.correlated_events.map((item, i) => (
              <li key={i} className="correlation-list__item">
                <span className="correlation-list__arrow">→</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {context.kb_matches && context.kb_matches.matches.length > 0 && (
        <section className="log-section">
          <h4>KB Re-checked</h4>
          <p className="reasoning-text">
            Precedents re-evaluated with updated incident profile:{" "}
            {context.kb_matches.matches.map((m) => `${m.id} (${Math.round(m.similarite * 100)}%)`).join(", ")}
          </p>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RemediationPlanView (exported — used by History)
// ---------------------------------------------------------------------------

const PHASE_LABELS = [
  { key: "immediat" as const, label: "Immediate", sub: "NOW", cls: "remediation-phase--now" },
  { key: "court_terme" as const, label: "Short-term", sub: "+24h", cls: "remediation-phase--soon" },
  { key: "long_terme" as const, label: "Long-term", sub: "+30d", cls: "remediation-phase--later" },
];

export function RemediationPlanView({ data }: { data: RemediationPlan }) {
  return (
    <div className="remediation-columns">
      {PHASE_LABELS.map(({ key, label, sub, cls }) => (
        <div key={key} className={`remediation-phase ${cls}`}>
          <div className="remediation-phase__header">
            <span className="remediation-phase__label">{label}</span>
            <span className="remediation-phase__sub">{sub}</span>
          </div>
          <ol className="remediation-actions">
            {data[key].map((item, i) => (
              <li key={i} className="remediation-action">{item}</li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SummaryView
// ---------------------------------------------------------------------------

function SummaryView({ data, meta }: { data: IncidentReport; meta: MetaResponse | null }) {
  const threshold = meta?.confidence_threshold ?? 0.75;

  function copyReport() {
    void navigator.clipboard.writeText(data.texte);
  }

  return (
    <div className="summary-layout">
      <div className="summary-kpi-row">
        <div className="summary-kpi">
          <span className="summary-kpi__label">Window</span>
          <span className="summary-kpi__value">{data.fenetre}</span>
        </div>
        <div className="summary-kpi">
          <span className="summary-kpi__label">Impact</span>
          <span className="summary-kpi__value summary-kpi__value--alert">{data.impact}</span>
        </div>
        <div className="summary-kpi">
          <span className="summary-kpi__label">Confidence</span>
          <span className={`summary-kpi__value ${data.confiance >= threshold ? "summary-kpi__value--ok" : "summary-kpi__value--warn"}`}>
            {(data.confiance * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      <div className="cause-callout">
        <span className="cause-callout__label">Root cause</span>
        <p className="cause-callout__text">{data.cause_racine}</p>
      </div>

      <section className="log-section">
        <h4>Remediation (proposed)</h4>
        <ul className="remediation-summary-list">
          {data.remediation.map((item, i) => (
            <li key={i} className="remediation-summary-list__item">{item}</li>
          ))}
        </ul>
      </section>

      {data.precedent_lie && (
        <div className="precedent-ref">
          <span className="precedent-ref__label">Related precedent</span>
          <span className="precedent-ref__value">{data.precedent_lie}</span>
        </div>
      )}

      <section className="log-section">
        <h4>
          Full Report
          <button type="button" className="copy-btn" onClick={copyReport} title="Copy to clipboard">
            Copy
          </button>
        </h4>
        <pre className="report-text">{data.texte}</pre>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RejectionView
// ---------------------------------------------------------------------------

function RejectionView() {
  return (
    <div className="rejection-view">
      <div className="verdict-banner verdict-banner--reject">
        <span className="verdict-banner__icon">✗</span>
        <div>
          <strong>Remediation rejected</strong>
          <p>The human did not authorise the remediation plan. The pipeline stops here — no plan is generated or displayed.</p>
        </div>
      </div>
    </div>
  );
}
