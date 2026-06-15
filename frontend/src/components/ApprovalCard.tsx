import type { RemediationApprovalRequest } from "../types";
import ConfidenceBar from "./ConfidenceBar";

interface ApprovalCardProps {
  request: RemediationApprovalRequest;
  confidenceThreshold: number;
  disabled: boolean;
  onApprove: () => void;
  onReject: () => void;
}

/** HITL gate (DECISIONS.md): no remediation without explicit human approval. */
export default function ApprovalCard({ request, confidenceThreshold, disabled, onApprove, onReject }: ApprovalCardProps) {
  const { incident, root_cause, kb_matches } = request;

  return (
    <div className="approval-card">
      <p className="approval-card__message">{request.message}</p>
      <dl className="kv">
        <dt>Incident</dt>
        <dd>
          {incident.titre} ({incident.severite})
        </dd>
        <dt>Services</dt>
        <dd>{incident.services.join(", ")}</dd>
        <dt>Root cause</dt>
        <dd>{root_cause.cause}</dd>
        {kb_matches.matches.length > 0 && (
          <>
            <dt>Related precedents</dt>
            <dd>{kb_matches.matches.map((match) => match.id).join(", ")}</dd>
          </>
        )}
      </dl>
      <ConfidenceBar value={root_cause.confiance} threshold={confidenceThreshold} />
      <p className="approval-card__note">
        Reminder: the remediation remains a displayed plan only — no action is executed on a real system.
      </p>
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
