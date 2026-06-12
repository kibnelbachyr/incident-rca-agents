import type { RemediationApprovalRequest } from "../types";
import ConfidenceBar from "./ConfidenceBar";

interface ApprovalCardProps {
  request: RemediationApprovalRequest;
  confidenceThreshold: number;
  disabled: boolean;
  onApprove: () => void;
  onReject: () => void;
}

/** Porte HITL (DECISIONS.md) : aucune remediation sans validation humaine explicite. */
export default function ApprovalCard({ request, confidenceThreshold, disabled, onApprove, onReject }: ApprovalCardProps) {
  const { incident, root_cause, kb_matches } = request;

  return (
    <div className="approval-card">
      <h3>Validation humaine requise</h3>
      <p className="approval-card__message">{request.message}</p>
      <dl className="kv">
        <dt>Incident</dt>
        <dd>
          {incident.titre} ({incident.severite})
        </dd>
        <dt>Services</dt>
        <dd>{incident.services.join(", ")}</dd>
        <dt>Cause retenue</dt>
        <dd>{root_cause.cause}</dd>
        {kb_matches.matches.length > 0 && (
          <>
            <dt>Precedents lies</dt>
            <dd>{kb_matches.matches.map((match) => match.id).join(", ")}</dd>
          </>
        )}
      </dl>
      <ConfidenceBar value={root_cause.confiance} threshold={confidenceThreshold} />
      <p className="approval-card__note">
        Rappel : la remediation reste un plan affiche ; aucune action n'est executee sur un systeme reel.
      </p>
      <div className="approval-card__actions">
        <button className="button button--reject" onClick={onReject} disabled={disabled}>
          Refuser
        </button>
        <button className="button button--approve" onClick={onApprove} disabled={disabled}>
          Approuver la remediation
        </button>
      </div>
    </div>
  );
}
