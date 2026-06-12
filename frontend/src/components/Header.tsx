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
          <h1>Incident RCA Agents</h1>
          <p>Diagnostic multi-agents d'un incident de paiement — démo</p>
        </div>
      </div>

      <nav className="header__tabs">
        <button className={view === "demo" ? "tab tab--active" : "tab"} onClick={() => onViewChange("demo")}>
          Démo
        </button>
        <button className={view === "history" ? "tab tab--active" : "tab"} onClick={() => onViewChange("history")}>
          Historique
        </button>
      </nav>

      {meta && (
        <div className="header__badges">
          <span className="badge">seuil confiance {meta.confidence_threshold.toFixed(2)}</span>
          <span className="badge">boucles max {meta.max_reflection_loops}</span>
          <span className="badge">KB {meta.kb_mode}</span>
          <span className="badge">{meta.use_real_azure_openai ? "Azure OpenAI" : "mode hors-ligne (stub)"}</span>
          <span className="badge">{meta.cosmos_enabled ? "Cosmos DB" : "persistance locale"}</span>
        </div>
      )}
    </header>
  );
}
