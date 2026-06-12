import { useEffect, useState } from "react";

import { fetchHistory, fetchHistoryRecord } from "../api";
import type { IncidentRecord, IncidentRecordSummary, MetaResponse } from "../types";
import ConfidenceBar from "./ConfidenceBar";
import { RemediationPlanView } from "./StepCard";

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
      {loading && <p className="empty">Chargement de l'historique...</p>}
      {error && <p className="error-banner">{error}</p>}
      {!loading && !error && summaries.length === 0 && (
        <p className="empty">Aucune execution enregistree pour le moment.</p>
      )}
      {summaries.length > 0 && (
        <table className="history-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Titre</th>
              <th>Severite</th>
              <th>Cause</th>
              <th>Confiance</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {summaries.map((item) => (
              <tr key={item.id} className="history-table__row" onClick={() => openRecord(item.id)}>
                <td>{new Date(item.finished_at).toLocaleString("fr-FR")}</td>
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
  if (approved === null) return <span className="badge">en attente</span>;
  return approved ? (
    <span className="badge badge--ok">approuvée</span>
  ) : (
    <span className="badge badge--low">refusée</span>
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
        ← Retour à l'historique
      </button>
      <p className="history-detail__meta">
        Execution {record.id} — {new Date(record.started_at).toLocaleString("fr-FR")} →{" "}
        {new Date(record.finished_at).toLocaleString("fr-FR")} — <DecisionBadge approved={record.approved} />
      </p>

      {context.incident && (
        <article className="step-card">
          <h3>Incident</h3>
          <dl className="kv">
            <dt>Titre</dt>
            <dd>{context.incident.titre}</dd>
            <dt>Severite</dt>
            <dd>{context.incident.severite}</dd>
            <dt>Services</dt>
            <dd>{context.incident.services.join(", ")}</dd>
            <dt>Fenetre</dt>
            <dd>{context.incident.fenetre}</dd>
          </dl>
        </article>
      )}

      {context.root_cause && (
        <article className="step-card">
          <h3>Cause racine retenue</h3>
          <p>
            <strong>Cause :</strong> {context.root_cause.cause}
          </p>
          <p>
            <strong>Raisonnement :</strong> {context.root_cause.raisonnement}
          </p>
          <ConfidenceBar value={context.root_cause.confiance} threshold={threshold} />
        </article>
      )}

      {context.remediation_plan && (
        <article className="step-card">
          <h3>Plan de remediation (proposé)</h3>
          <RemediationPlanView data={context.remediation_plan} />
        </article>
      )}

      {context.report && (
        <article className="step-card">
          <h3>Rapport final</h3>
          <pre className="report-text">{context.report.texte}</pre>
        </article>
      )}

      {context.approved === false && (
        <p className="empty">L'humain a refusé la remédiation lors de cette exécution.</p>
      )}
    </div>
  );
}
