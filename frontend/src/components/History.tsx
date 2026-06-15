import { useEffect, useState } from "react";

import { fetchHistory, fetchHistoryRecord } from "../api";
import type { IncidentRecord, IncidentRecordSummary, MetaResponse } from "../types";
import ConfidenceBar from "./ConfidenceBar";
import { RemediationPlanView } from "./DetailPanel";

interface HistoryProps {
  meta: MetaResponse | null;
}

export default function History({ meta }: HistoryProps) {
  const [summaries, setSummaries] = useState<IncidentRecordSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<IncidentRecord | null>(null);
  const [selectedError, setSelectedError] = useState<string | null>(null);

  useEffect(() => {
    fetchHistory()
      .then(setSummaries)
      .catch((err: unknown) => setError(String(err)))
      .finally(() => setLoading(false));
  }, []);

  async function openRecord(id: string) {
    setSelectedError(null);
    try {
      setSelected(await fetchHistoryRecord(id));
    } catch (err) {
      setSelectedError(String(err));
    }
  }

  if (selected) {
    return <HistoryDetail record={selected} meta={meta} onBack={() => setSelected(null)} />;
  }

  return (
    <div className="history">
      {selectedError && <p className="error-banner">{selectedError}</p>}
      {loading && <p className="empty">Loading history…</p>}
      {error && <p className="error-banner">{error}</p>}
      {!loading && !error && summaries.length === 0 && <p className="empty">No runs recorded yet.</p>}
      {summaries.length > 0 && (
        <table className="history-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Title</th>
              <th>Severity</th>
              <th>Cause</th>
              <th>Confidence</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {summaries.map((item) => (
              <tr key={item.id} className="history-table__row" onClick={() => openRecord(item.id)}>
                <td>{new Date(item.finished_at).toLocaleString("en-GB")}</td>
                <td>{item.titre ?? "—"}</td>
                <td>{item.severite ?? "—"}</td>
                <td>{item.cause ?? "—"}</td>
                <td>{item.confiance !== null ? item.confiance.toFixed(2) : "—"}</td>
                <td>
                  <DecisionBadge approved={item.approved} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function DecisionBadge({ approved }: { approved: boolean | null }) {
  if (approved === null) return <span className="badge">pending</span>;
  return approved ? (
    <span className="badge badge--ok">approved</span>
  ) : (
    <span className="badge badge--low">rejected</span>
  );
}

interface HistoryDetailProps {
  record: IncidentRecord;
  meta: MetaResponse | null;
  onBack: () => void;
}

function HistoryDetail({ record, meta, onBack }: HistoryDetailProps) {
  const { context } = record;
  const threshold = meta?.confidence_threshold ?? 0.75;

  return (
    <div className="history-detail">
      <button className="button" onClick={onBack}>
        ← Back to history
      </button>
      <p className="history-detail__meta">
        Run {record.id} — {new Date(record.started_at).toLocaleString("en-GB")} →{" "}
        {new Date(record.finished_at).toLocaleString("en-GB")} — <DecisionBadge approved={record.approved} />
      </p>

      {context.incident && (
        <article className="history-card">
          <h3>Incident</h3>
          <dl className="kv">
            <dt>Title</dt>
            <dd>{context.incident.titre}</dd>
            <dt>Severity</dt>
            <dd>{context.incident.severite}</dd>
            <dt>Services</dt>
            <dd>{context.incident.services.join(", ")}</dd>
            <dt>Window</dt>
            <dd>{context.incident.fenetre}</dd>
          </dl>
        </article>
      )}

      {context.root_cause && (
        <article className="history-card">
          <h3>Root Cause</h3>
          <p>
            <strong>Cause:</strong> {context.root_cause.cause}
          </p>
          <p>
            <strong>Reasoning:</strong> {context.root_cause.raisonnement}
          </p>
          <ConfidenceBar value={context.root_cause.confiance} threshold={threshold} />
        </article>
      )}

      {context.remediation_plan && (
        <article className="history-card">
          <h3>Remediation Plan (proposed)</h3>
          <RemediationPlanView data={context.remediation_plan} />
        </article>
      )}

      {context.report && (
        <article className="history-card">
          <h3>Final Report</h3>
          <pre className="report-text">{context.report.texte}</pre>
        </article>
      )}

      {context.approved === false && <p className="empty">The human rejected the remediation for this run.</p>}
    </div>
  );
}
