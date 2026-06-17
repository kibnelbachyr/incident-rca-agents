import type { RemediationApprovalRequest } from "../types";
import ConfidenceBar from "./ConfidenceBar";

interface ApprovalCardProps {
  request: RemediationApprovalRequest;
  confidenceThreshold: number;
  disabled: boolean;
  onApprove: () => void;
  onReject: () => void;
}

/** HITL gate — no remediation without explicit human approval. */
export default function ApprovalCard({ request, confidenceThreshold, disabled, onApprove, onReject }: ApprovalCardProps) {
  const { incident, root_cause, kb_matches } = request;
  const confPct = (root_cause.confiance * 100).toFixed(0);

  return (
    <div className="approval-card">
      <div className="approval-card__incident">
        <span className={`sev-pill sev-pill--${incident.severite}`}>{incident.severite}</span>
        <span className="approval-card__incident-title">{incident.titre}</span>
      </div>

      <div className="approval-card__services">
        {incident.services.map((svc) => (
          <span key={svc} className="service-chip">{svc}</span>
        ))}
      </div>

      <div className="cause-callout">
        <span className="cause-callout__label">Root cause — {confPct}% confidence</span>
        <p className="cause-callout__text">{root_cause.cause}</p>
      </div>

      <ConfidenceBar value={root_cause.confiance} threshold={confidenceThreshold} />

      {kb_matches.matches.length > 0 && (
        <div className="approval-card__precedents">
          <span className="approval-card__precedents-label">Related precedents</span>
          <span className="approval-card__precedents-list">
            {kb_matches.matches.map((m) => `${m.id} (${Math.round(m.similarite * 100)}%)`).join("  ·  ")}
          </span>
        </div>
      )}

      <p className="approval-card__note">
        Reminder: the remediation plan is proposed only — no action will be executed on any live system.
      </p>

      <p className="approval-card__message">{request.message}</p>

      <div className="approval-card__actions">
        <button className="button button--reject" onClick={onReject} disabled={disabled}>
          Reject
        </button>
        <button className="button button--approve" onClick={onApprove} disabled={disabled}>
          Approve remediation
        </button>
      </div>
    </div>
  );
}
