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
        <RootCauseView data={context.root_cause} meta={meta} loopCount={context.loop_count} />
      ) : null;
    case "gather_evidence":
      return <GatherEvidenceView context={context} meta={meta} />;
    case "remediation":
      return context.remediation_plan ? <RemediationPlanView data={context.remediation_plan} /> : null;
    case "summary":
      return context.report ? <SummaryView data={context.report} /> : null;
    case "human_approval":
      return <RejectionView />;
    default:
      return null;
  }
}

function LogAnalysisView({ data }: { data: LogAnalysis }) {
  return (
    <div className="step-body log-analysis-grid">
      <div>
        <h4>Reconstructed timeline</h4>
        <ul className="timeline">
          {data.timeline.map((item, i) => (
            <li key={i}>
              <span className="timeline__time">{item.time}</span> {item.event}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h4>Detected anomalies</h4>
        <ul>
          {data.anomalies.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </div>
      <div>
        <h4>Correlated events</h4>
        <ul>
          {data.correlated_events.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function IncidentView({ data }: { data: Incident }) {
  return (
    <div className="step-body">
      <dl className="kv">
        <dt>Title</dt>
        <dd>{data.titre}</dd>
        <dt>Severity</dt>
        <dd>
          <span className={`severity severity--${data.severite}`}>{data.severite}</span>
        </dd>
        <dt>Services</dt>
        <dd>{data.services.join(", ")}</dd>
        <dt>Window</dt>
        <dd>{data.fenetre}</dd>
      </dl>
      <h4>Symptoms</h4>
      <ul>
        {data.symptomes.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function KBMatchesView({ data }: { data: KBMatches }) {
  if (data.matches.length === 0) {
    return <p className="empty">No matching precedent found in the knowledge base.</p>;
  }
  return (
    <ul className="kb-matches">
      {data.matches.map((match) => (
        <li key={match.id}>
          <div className="kb-matches__header">
            <span className="kb-matches__id">{match.id}</span>
            <span className="kb-matches__similarity">similarity {match.similarite.toFixed(2)}</span>
          </div>
          <p>{match.resolution}</p>
        </li>
      ))}
    </ul>
  );
}

function RootCauseView({
  data,
  meta,
  loopCount,
}: {
  data: RootCauseHypothesis;
  meta: MetaResponse | null;
  loopCount: number;
}) {
  const threshold = meta?.confidence_threshold ?? 0.75;
  const maxLoops = meta?.max_reflection_loops ?? 2;
  const willLoop = data.confiance < threshold && loopCount < maxLoops;

  return (
    <div className="step-body">
      <p>
        <strong>Root cause:</strong> {data.cause}
      </p>
      <p>
        <strong>Reasoning:</strong> {data.raisonnement}
      </p>
      <ConfidenceBar value={data.confiance} threshold={threshold} />
      {willLoop ? (
        <div className="root-cause__verdict root-cause__verdict--low">
          <p>
            Confidence below threshold: the orchestrator loops back to gather more evidence (pass {loopCount + 1}/
            {maxLoops}).
          </p>
          {data.preuves_manquantes.length > 0 && (
            <>
              <h4>Missing evidence to collect</h4>
              <ul>
                {data.preuves_manquantes.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      ) : (
        <p className="root-cause__verdict root-cause__verdict--ok">
          {data.confiance >= threshold
            ? "Confidence sufficient: proceeding to human approval."
            : "Reflection budget exhausted: proceeding to human approval despite confidence below threshold."}
        </p>
      )}
    </div>
  );
}

function GatherEvidenceView({ context, meta }: { context: SharedContext; meta: MetaResponse | null }) {
  const maxLoops = meta?.max_reflection_loops ?? 2;
  return (
    <div className="step-body">
      <p>
        Loop {context.loop_count}/{maxLoops}: Log Analyzer and KB Search are re-queried with the targeted missing
        evidence.
      </p>
      {context.log_analysis && context.log_analysis.correlated_events.length > 0 && (
        <>
          <h4>New correlated events</h4>
          <ul>
            {context.log_analysis.correlated_events.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </>
      )}
      {context.kb_matches && context.kb_matches.matches.length > 0 && (
        <p>Knowledge base re-checked: {context.kb_matches.matches.map((match) => match.id).join(", ")}</p>
      )}
    </div>
  );
}

/** Shared with `History.tsx` (detail view of a past run). */
export function RemediationPlanView({ data }: { data: RemediationPlan }) {
  return (
    <div className="remediation-grid">
      <div>
        <h4>Immediate</h4>
        <ul>
          {data.immediat.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </div>
      <div>
        <h4>Short term</h4>
        <ul>
          {data.court_terme.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </div>
      <div>
        <h4>Long term</h4>
        <ul>
          {data.long_terme.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function SummaryView({ data }: { data: IncidentReport }) {
  return (
    <div className="step-body">
      <pre className="report-text">{data.texte}</pre>
    </div>
  );
}

function RejectionView() {
  return (
    <p className="empty">
      The human rejected the remediation: the workflow stops here. No remediation plan is generated or displayed.
    </p>
  );
}
