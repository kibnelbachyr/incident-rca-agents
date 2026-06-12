import type {
  Incident,
  IncidentReport,
  KBMatches,
  LogAnalysis,
  MetaResponse,
  RemediationPlan,
  RootCauseHypothesis,
  SharedContext,
  StepPayload,
} from "../types";
import ConfidenceBar from "./ConfidenceBar";

// Titres miroir de `_STEP_TITLES` (src/main.py).
const STEP_TITLES: Record<string, string> = {
  log_analyzer: "Agent 1/6 — Log Analyzer : analyse des logs bruts",
  incident_extractor: "Agent 2/6 — Incident Extractor : extraction de l'incident",
  kb_search: "Agent 3/6 — KB Search : recherche de precedents",
  root_cause: "Agent 4/6 — Root Cause : hypothese de cause racine",
  gather_evidence: "Boucle de reflexion — Gather Evidence : collecte de preuves complementaires",
  remediation: "Agent 5/6 — Remediation : plan de remediation (propose)",
  summary: "Agent 6/6 — Summary : rapport final",
  human_approval: "Validation humaine : remediation refusee",
};

interface StepCardProps {
  step: StepPayload;
  meta: MetaResponse | null;
}

export default function StepCard({ step, meta }: StepCardProps) {
  const { executor_id, context } = step;

  return (
    <article className={`step-card step-card--${executor_id}`}>
      <h3>{STEP_TITLES[executor_id] ?? executor_id}</h3>
      {renderBody(executor_id, context, meta)}
    </article>
  );
}

function renderBody(executorId: string, context: SharedContext, meta: MetaResponse | null) {
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
        <h4>Timeline reconstituee</h4>
        <ul className="timeline">
          {data.timeline.map((item, i) => (
            <li key={i}>
              <span className="timeline__time">{item.time}</span> {item.event}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h4>Anomalies detectees</h4>
        <ul>
          {data.anomalies.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </div>
      <div>
        <h4>Evenements correles</h4>
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
        <dt>Titre</dt>
        <dd>{data.titre}</dd>
        <dt>Severite</dt>
        <dd>
          <span className={`severity severity--${data.severite}`}>{data.severite}</span>
        </dd>
        <dt>Services</dt>
        <dd>{data.services.join(", ")}</dd>
        <dt>Fenetre</dt>
        <dd>{data.fenetre}</dd>
      </dl>
      <h4>Symptomes</h4>
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
    return <p className="empty">Aucun precedent trouve dans la base de connaissances.</p>;
  }
  return (
    <ul className="kb-matches">
      {data.matches.map((match) => (
        <li key={match.id}>
          <div className="kb-matches__header">
            <span className="kb-matches__id">{match.id}</span>
            <span className="kb-matches__similarity">similarite {match.similarite.toFixed(2)}</span>
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
        <strong>Cause retenue :</strong> {data.cause}
      </p>
      <p>
        <strong>Raisonnement :</strong> {data.raisonnement}
      </p>
      <ConfidenceBar value={data.confiance} threshold={threshold} />
      {willLoop ? (
        <div className="root-cause__verdict root-cause__verdict--low">
          <p>
            Confiance sous le seuil : l'orchestrateur reboucle pour chercher des preuves (passage {loopCount + 1}/
            {maxLoops}).
          </p>
          {data.preuves_manquantes.length > 0 && (
            <>
              <h4>Preuves manquantes a collecter</h4>
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
            ? "Confiance suffisante : passage a la validation humaine."
            : "Budget de reflexion epuise : passage a la validation humaine malgre une confiance sous le seuil."}
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
        Reboucle {context.loop_count}/{maxLoops} : Log Analyzer et KB Search re-sollicites avec les preuves
        manquantes ciblees.
      </p>
      {context.log_analysis && context.log_analysis.correlated_events.length > 0 && (
        <>
          <h4>Nouveaux evenements correles</h4>
          <ul>
            {context.log_analysis.correlated_events.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </>
      )}
      {context.kb_matches && context.kb_matches.matches.length > 0 && (
        <p>Base de connaissances reconfrontee : {context.kb_matches.matches.map((match) => match.id).join(", ")}</p>
      )}
    </div>
  );
}

/** Partage avec `History.tsx` (detail d'une execution passee). */
export function RemediationPlanView({ data }: { data: RemediationPlan }) {
  return (
    <div className="remediation-grid">
      <div>
        <h4>Immediat</h4>
        <ul>
          {data.immediat.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </div>
      <div>
        <h4>Court terme</h4>
        <ul>
          {data.court_terme.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </div>
      <div>
        <h4>Long terme</h4>
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
      L'humain a refuse la remediation : le workflow s'arrete ici. Aucun plan de remediation n'est genere ni affiche.
    </p>
  );
}
