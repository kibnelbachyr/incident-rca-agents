import type { MetaResponse } from "../types";

export type View = "demo" | "history";

interface HeaderProps {
  meta: MetaResponse | null;
  view: View;
  onViewChange: (view: View) => void;
}

export default function Header({ meta, view, onViewChange }: HeaderProps) {
  return (
    <header className="header">
      <div className="header__title">
        <img src="/sw1-mark.svg" alt="SoftwareOne" className="header__logo" />
        <div className="header__brand">
          <span className="header__brand-sw1">SoftwareOne</span>
          <span className="header__brand-sep" aria-hidden="true" />
          <div>
            <h1>
              Incident RCA <span>Pipeline</span>
            </h1>
            <p>Multi-agent AI diagnostics — live orchestration demo</p>
          </div>
        </div>
      </div>

      <nav className="header__tabs">
        <button
          className={view === "demo" ? "tab tab--active" : "tab"}
          onClick={() => onViewChange("demo")}
        >
          Live Run
        </button>
        <button
          className={view === "history" ? "tab tab--active" : "tab"}
          onClick={() => onViewChange("history")}
        >
          History
        </button>
      </nav>

      <div className="header__event" aria-label="VivaTech Paris 2025">
        <span className="header__event-mark">VT</span>
        <span className="header__event-name">VivaTech Paris 2025</span>
      </div>

      {meta && (
        <div className="header__badges">
          <span className="badge">Confidence ≥ {meta.confidence_threshold.toFixed(2)}</span>
          <span className="badge">Max loops {meta.max_reflection_loops}</span>
          <span className="badge">KB: {meta.kb_mode}</span>
          <span className="badge">{meta.use_real_azure_openai ? "Azure OpenAI" : "Offline (stub)"}</span>
          <span className="badge">{meta.cosmos_enabled ? "Cosmos DB" : "Local persistence"}</span>
        </div>
      )}
    </header>
  );
}
