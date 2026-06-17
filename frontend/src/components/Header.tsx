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
        <img src="/softwareone-logo.png" alt="SoftwareOne" className="header__logo" />
        <div className="header__brand">
          <span className="header__brand-sep" aria-hidden="true" />
          <div>
            <h1>
              Incident RCA
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

      <div className="header__event" aria-label="VivaTech Paris 2026">
        <span className="header__event-mark">VT</span>
        <span className="header__event-name">VivaTech Paris 2025</span>
      </div>

      {meta && (
        <div className="header__badges">
        </div>
      )}
    </header>
  );
}
