import { useEffect, useState } from "react";

import { fetchMeta, fetchScenarios, startRun, submitApproval } from "./api";
import ActivityFeed, { type FeedEntry } from "./components/ActivityFeed";
import DetailPanel from "./components/DetailPanel";
import Footer from "./components/Footer";
import Header, { type View } from "./components/Header";
import History from "./components/History";
import PipelineHUD, { type Phase } from "./components/PipelineHUD";
import type {
  ExecutorId,
  MetaResponse,
  RemediationApprovalRequest,
  ScenarioInfo,
  StepPayload,
} from "./types";

// --------------------------------------------------------------------------
// Step code / label maps (shared with ActivityFeed entry construction)
// --------------------------------------------------------------------------

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

const STEP_LABELS: Record<ExecutorId, string> = {
  log_analyzer: "Log Analyzer",
  incident_extractor: "Incident Extractor",
  kb_search: "KB Search",
  root_cause: "Root Cause",
  gather_evidence: "Gather Evidence",
  human_approval: "Human Approval",
  remediation: "Remediation",
  summary: "Summary",
};

function stepSummary(step: StepPayload, threshold: number): string {
  const { executor_id, context } = step;
  switch (executor_id) {
    case "log_analyzer": {
      const la = context.log_analysis;
      return la
        ? `${la.timeline.length} events · ${la.anomalies.length} anomalies · ${la.correlated_events.length} correlations`
        : "Complete";
    }
    case "incident_extractor": {
      const inc = context.incident;
      return inc ? `${inc.severite} · ${inc.titre}` : "Complete";
    }
    case "kb_search": {
      const kb = context.kb_matches;
      return kb?.matches.length
        ? kb.matches.map((m) => `${m.id} (${Math.round(m.similarite * 100)}%)`).join(" · ")
        : "No precedents found";
    }
    case "root_cause": {
      const rc = context.root_cause;
      if (!rc) return "Complete";
      const ok = rc.confiance >= threshold;
      return `confidence ${rc.confiance.toFixed(2)} ${ok ? "✓ threshold met" : `— BELOW threshold ${threshold.toFixed(2)}`}`;
    }
    case "gather_evidence":
      return `Loop ${context.loop_count} — targeted re-analysis complete`;
    case "remediation": {
      const rp = context.remediation_plan;
      return rp
        ? `${rp.immediat.length} immediate · ${rp.court_terme.length} short-term · ${rp.long_terme.length} long-term`
        : "Complete";
    }
    case "summary":
      return "Full incident report generated";
    case "human_approval":
      return "Remediation rejected by human";
    default:
      return "Complete";
  }
}

function makeStepEntries(step: StepPayload, threshold: number): FeedEntry[] {
  const { executor_id, context } = step;
  const entries: FeedEntry[] = [];

  if (executor_id === "gather_evidence" && context.routing_note) {
    entries.push({
      id: `route-${context.loop_count}-${Date.now()}`,
      type: "route",
      label: "Orchestrator",
      detail: context.routing_note,
    });
  }

  entries.push({
    id: `step-${executor_id}-${Date.now()}`,
    type: executor_id === "human_approval" ? "hitl" : "agent",
    code: STEP_CODES[executor_id],
    label: STEP_LABELS[executor_id],
    detail: stepSummary(step, threshold),
  });

  return entries;
}

// --------------------------------------------------------------------------
// App
// --------------------------------------------------------------------------

export default function App() {
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [view, setView] = useState<View>("demo");
  const [phase, setPhase] = useState<Phase>("idle");
  const [runId, setRunId] = useState<string | null>(null);
  const [steps, setSteps] = useState<StepPayload[]>([]);
  const [manualIndex, setManualIndex] = useState<number | null>(null);
  const [approvalRequest, setApprovalRequest] = useState<RemediationApprovalRequest | null>(null);
  const [finalApproved, setFinalApproved] = useState<boolean | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [feedEntries, setFeedEntries] = useState<FeedEntry[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [scenarioId, setScenarioId] = useState<string>("");

  useEffect(() => {
    fetchMeta()
      .then(setMeta)
      .catch(() => undefined);
    fetchScenarios()
      .then((data) => {
        setScenarios(data.scenarios);
        setScenarioId(data.default);
      })
      .catch(() => undefined);
  }, []);

  const selectedScenario = scenarios.find((s) => s.id === scenarioId) ?? null;

  async function handleStart() {
    setPhase("running");
    setSteps([]);
    setManualIndex(null);
    setApprovalRequest(null);
    setFinalApproved(null);
    setErrorMessage(null);
    setRunId(null);
    setFeedEntries([]);

    const threshold = meta?.confidence_threshold ?? 0.75;
    const scenarioLabel = selectedScenario?.label ?? scenarioId;

    try {
      await startRun(scenarioId, {
        onRunStarted: (data) => {
          setRunId(data.run_id);
          setFeedEntries([
            {
              id: "start",
              type: "start",
              label: `RUN ${data.run_id.slice(0, 8).toUpperCase()}`,
              detail: `Orchestration started — scenario: ${scenarioLabel}`,
            },
          ]);
        },
        onStep: (data) => {
          setSteps((prev) => [...prev, data]);
          const newEntries = makeStepEntries(data, threshold);
          setFeedEntries((prev) => [...prev, ...newEntries]);
        },
        onApprovalRequired: (data) => {
          setApprovalRequest(data.request);
          setPhase("awaiting_approval");
          setFeedEntries((prev) => [
            ...prev,
            {
              id: "hitl-gate",
              type: "hitl",
              label: "Human Approval",
              detail: "Awaiting human decision — remediation proposed",
            },
          ]);
        },
        onDone: (data) => {
          setFinalApproved(data.approved);
          setPhase("done");
          setFeedEntries((prev) => [
            ...prev,
            {
              id: "done",
              type: "done",
              label: "Pipeline complete",
              detail: data.approved
                ? "Remediation approved — report generated"
                : "Remediation rejected — pipeline halted",
            },
          ]);
        },
        onError: (data) => {
          setErrorMessage(data.message);
          setPhase("error");
          setFeedEntries((prev) => [
            ...prev,
            { id: "error", type: "error", label: "Error", detail: data.message },
          ]);
        },
      });
    } catch (err) {
      setErrorMessage(String(err));
      setPhase("error");
    }
  }

  async function handleApproval(approved: boolean) {
    if (!runId) return;
    setPhase("running");
    setApprovalRequest(null);

    const threshold = meta?.confidence_threshold ?? 0.75;

    try {
      await submitApproval(runId, approved, {
        onStep: (data) => {
          setSteps((prev) => [...prev, data]);
          const newEntries = makeStepEntries(data, threshold);
          setFeedEntries((prev) => [...prev, ...newEntries]);
        },
        onDone: (data) => {
          setFinalApproved(data.approved);
          setPhase("done");
          setFeedEntries((prev) => [
            ...prev,
            {
              id: "done",
              type: "done",
              label: "Pipeline complete",
              detail: data.approved
                ? "Remediation approved — report generated"
                : "Remediation rejected — pipeline halted",
            },
          ]);
        },
        onError: (data) => {
          setErrorMessage(data.message);
          setPhase("error");
          setFeedEntries((prev) => [
            ...prev,
            { id: "error", type: "error", label: "Error", detail: data.message },
          ]);
        },
      });
    } catch (err) {
      setErrorMessage(String(err));
      setPhase("error");
    }
  }

  const isBusy = phase === "running" || phase === "awaiting_approval";
  const selectedIndex = manualIndex ?? (steps.length > 0 ? steps.length - 1 : null);
  const selectedStep = selectedIndex !== null ? (steps[selectedIndex] ?? null) : null;
  const selectedExecutorId = selectedStep?.executor_id ?? null;

  function handleSelectNode(id: ExecutorId) {
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].executor_id === id) {
        setManualIndex(i);
        return;
      }
    }
  }

  function handlePrev() {
    if (selectedIndex === null || selectedIndex <= 0) return;
    setManualIndex(selectedIndex - 1);
  }

  function handleNext() {
    if (selectedIndex === null || selectedIndex >= steps.length - 1) return;
    const next = selectedIndex + 1;
    setManualIndex(next >= steps.length - 1 ? null : next);
  }

  return (
    <div className="app">
      <Header meta={meta} view={view} onViewChange={setView} />

      {view === "history" ? (
        <main className="main main--history">
          <History meta={meta} />
        </main>
      ) : (
        <main className="main">
          <div className="main__top">
            <PipelineHUD
              steps={steps}
              phase={phase}
              runId={runId}
              selectedId={selectedExecutorId}
              onSelect={handleSelectNode}
            />
            <ActivityFeed entries={feedEntries} />
          </div>

          <DetailPanel
            step={selectedStep}
            stepIndex={selectedIndex}
            totalSteps={steps.length}
            onPrev={handlePrev}
            onNext={handleNext}
            meta={meta}
            phase={phase}
            approvalRequest={approvalRequest}
            onApprove={() => handleApproval(true)}
            onReject={() => handleApproval(false)}
          />

          <div className="main__controls">
            {scenarios.length > 0 && (
              <div className="scenario-select" role="group" aria-label="Scenario">
                <span className="scenario-select__label">Scenario</span>
                {scenarios.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={s.id === scenarioId ? "tab tab--active" : "tab"}
                    onClick={() => setScenarioId(s.id)}
                    disabled={isBusy}
                    title={s.description}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            )}
            <button className="button button--primary" onClick={handleStart} disabled={isBusy || !scenarioId}>
              {phase === "idle" ? "Run Diagnostic" : "Re-run Diagnostic"}
            </button>
            <StatusLine phase={phase} finalApproved={finalApproved} scenarioLabel={selectedScenario?.label ?? null} />
            {errorMessage && <p className="error-banner">{errorMessage}</p>}
          </div>
        </main>
      )}

      <Footer />
    </div>
  );
}

function StatusLine({
  phase,
  finalApproved,
  scenarioLabel,
}: {
  phase: Phase;
  finalApproved: boolean | null;
  scenarioLabel: string | null;
}) {
  switch (phase) {
    case "idle":
      return <p className="status">Ready — will run scenario: {scenarioLabel ?? "…"}.</p>;
    case "running":
      return <p className="status status--active">Orchestration in progress…</p>;
    case "awaiting_approval":
      return <p className="status status--active">Awaiting human approval.</p>;
    case "done":
      return (
        <p className="status">
          Complete —{" "}
          {finalApproved ? "remediation approved, report generated." : "remediation rejected by the human."}
        </p>
      );
    case "error":
      return <p className="status status--error">An error occurred.</p>;
  }
}
