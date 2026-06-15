import { useEffect, useState } from "react";

import { fetchMeta, startRun, submitApproval } from "./api";
import ApprovalCard from "./components/ApprovalCard";
import Footer from "./components/Footer";
import Header, { type View } from "./components/Header";
import History from "./components/History";
import StepCard from "./components/StepCard";
import TopologyGraph from "./components/TopologyGraph";
import type { MetaResponse, RemediationApprovalRequest, StepPayload } from "./types";

type Phase = "idle" | "running" | "awaiting_approval" | "done" | "error";

export default function App() {
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [view, setView] = useState<View>("demo");
  const [phase, setPhase] = useState<Phase>("idle");
  const [runId, setRunId] = useState<string | null>(null);
  const [steps, setSteps] = useState<StepPayload[]>([]);
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
    setApprovalRequest(null);
    setFinalApproved(null);
    setErrorMessage(null);
    setRunId(null);

    try {
      await startRun({
        onRunStarted: (data) => setRunId(data.run_id),
        onStep: (data) => setSteps((prev) => [...prev, data]),
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
        onStep: (data) => setSteps((prev) => [...prev, data]),
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

  return (
    <div className="app">
      <Header meta={meta} view={view} onViewChange={setView} />
      <main className="main">
        {view === "history" ? (
          <History meta={meta} />
        ) : (
          <>
            <TopologyGraph
              steps={steps}
              running={phase === "running"}
              awaitingApproval={phase === "awaiting_approval"}
            />

            <div className="controls">
              <button className="button button--primary" onClick={handleStart} disabled={isBusy}>
                {phase === "idle" ? "Lancer le diagnostic" : "Relancer sur les logs de démo"}
              </button>
              <StatusLine phase={phase} finalApproved={finalApproved} />
            </div>

            {errorMessage && <p className="error-banner">{errorMessage}</p>}

            <div className="steps">
              {steps.map((step, i) => (
                <StepCard key={i} step={step} meta={meta} />
              ))}
            </div>

            {approvalRequest && (
              <ApprovalCard
                request={approvalRequest}
                confidenceThreshold={meta?.confidence_threshold ?? 0.75}
                disabled={phase !== "awaiting_approval"}
                onApprove={() => handleApproval(true)}
                onReject={() => handleApproval(false)}
              />
            )}
          </>
        )}
      </main>
      <Footer />
    </div>
  );
}

function StatusLine({ phase, finalApproved }: { phase: Phase; finalApproved: boolean | null }) {
  switch (phase) {
    case "idle":
      return <p className="status">Prêt à analyser data/payment-incident.log.</p>;
    case "running":
      return <p className="status status--active">Orchestration en cours…</p>;
    case "awaiting_approval":
      return <p className="status status--active">En attente de validation humaine.</p>;
    case "done":
      return (
        <p className="status">
          Terminé —{" "}
          {finalApproved ? "remédiation approuvée, rapport ci-dessus." : "remédiation refusée par l'humain."}
        </p>
      );
    case "error":
      return <p className="status status--error">Une erreur est survenue.</p>;
  }
}
