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
        <img src="/favicon.svg" alt="" className="header__logo" />
        <div>
          <h1>
            Incident RCA <span>// Radar</span>
          </h1>
          <p>Multi-agent payment incident diagnostics — live demo</p>
        </div>
      </div>

      <nav className="header__tabs">
        <button className={view === "demo" ? "tab tab--active" : "tab"} onClick={() => onViewChange("demo")}>
          Live Run
        </button>
        <button className={view === "history" ? "tab tab--active" : "tab"} onClick={() => onViewChange("history")}>
          History
        </button>
      </nav>

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
