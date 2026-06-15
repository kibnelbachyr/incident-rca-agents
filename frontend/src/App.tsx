import { useEffect, useState } from "react";

import { fetchMeta, startRun, submitApproval } from "./api";
import DetailPanel from "./components/DetailPanel";
import Footer from "./components/Footer";
import Header, { type View } from "./components/Header";
import History from "./components/History";
import RadarHUD, { type Phase } from "./components/RadarHUD";
import type { ExecutorId, MetaResponse, RemediationApprovalRequest, StepPayload } from "./types";

export default function App() {
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [view, setView] = useState<View>("demo");
  const [phase, setPhase] = useState<Phase>("idle");
  const [runId, setRunId] = useState<string | null>(null);
  const [steps, setSteps] = useState<StepPayload[]>([]);
  const [selectedStepId, setSelectedStepId] = useState<ExecutorId | null>(null);
  const [approvalRequest, setApprovalRequest] = useState<RemediationApprovalRequest | null>(null);
  const [finalApproved, setFinalApproved] = useState<boolean | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchMeta()
      .then(setMeta)
      .catch(() => undefined);
  }, []);

  async function handleStart() {
    setPhase("running");
    setSteps([]);
    setSelectedStepId(null);
    setApprovalRequest(null);
    setFinalApproved(null);
    setErrorMessage(null);
    setRunId(null);

    try {
      await startRun({
        onRunStarted: (data) => setRunId(data.run_id),
        onStep: (data) => {
          setSteps((prev) => [...prev, data]);
          setSelectedStepId(data.executor_id);
        },
        onApprovalRequired: (data) => {
          setApprovalRequest(data.request);
          setPhase("awaiting_approval");
        },
        onDone: (data) => {
          setFinalApproved(data.approved);
          setPhase("done");
        },
        onError: (data) => {
          setErrorMessage(data.message);
          setPhase("error");
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

    try {
      await submitApproval(runId, approved, {
        onStep: (data) => {
          setSteps((prev) => [...prev, data]);
          setSelectedStepId(data.executor_id);
        },
        onDone: (data) => {
          setFinalApproved(data.approved);
          setPhase("done");
        },
        onError: (data) => {
          setErrorMessage(data.message);
          setPhase("error");
        },
      });
    } catch (err) {
      setErrorMessage(String(err));
      setPhase("error");
    }
  }

  const isBusy = phase === "running" || phase === "awaiting_approval";
  const stepsById = new Map(steps.map((step) => [step.executor_id, step]));
  const selectedStep = selectedStepId ? stepsById.get(selectedStepId) ?? null : null;

  return (
    <div className="app">
      <Header meta={meta} view={view} onViewChange={setView} />

      {view === "history" ? (
        <main className="main main--history">
          <History meta={meta} />
        </main>
      ) : (
        <main className="main">
          <RadarHUD
            steps={steps}
            phase={phase}
            runId={runId}
            selectedId={selectedStepId}
            onSelect={setSelectedStepId}
          />

          <DetailPanel
            step={selectedStep}
            meta={meta}
            phase={phase}
            approvalRequest={approvalRequest}
            onApprove={() => handleApproval(true)}
            onReject={() => handleApproval(false)}
          />

          <div className="main__controls">
            <button className="button button--primary" onClick={handleStart} disabled={isBusy}>
              {phase === "idle" ? "Run Diagnostic" : "Re-run on Demo Logs"}
            </button>
            <StatusLine phase={phase} finalApproved={finalApproved} />
            {errorMessage && <p className="error-banner">{errorMessage}</p>}
          </div>
        </main>
      )}

      <Footer />
    </div>
  );
}

function StatusLine({ phase, finalApproved }: { phase: Phase; finalApproved: boolean | null }) {
  switch (phase) {
    case "idle":
      return <p className="status">Ready to analyze data/payment-incident.log.</p>;
    case "running":
      return <p className="status status--active">Orchestration in progress…</p>;
    case "awaiting_approval":
      return <p className="status status--active">Awaiting human approval.</p>;
    case "done":
      return (
        <p className="status">
          Complete — {finalApproved ? "remediation approved, report above." : "remediation rejected by the human."}
        </p>
      );
    case "error":
      return <p className="status status--error">An error occurred.</p>;
  }
}
