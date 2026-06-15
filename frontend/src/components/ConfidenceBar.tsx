interface ConfidenceBarProps {
  value: number;
  threshold: number;
}

/** Confidence gauge vs `CONFIDENCE_THRESHOLD` (cf. RootCauseExecutor, graph.py). */
export default function ConfidenceBar({ value, threshold }: ConfidenceBarProps) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  const thresholdPct = Math.round(Math.min(1, Math.max(0, threshold)) * 100);
  const sufficient = value >= threshold;

  return (
    <div className="confidence-bar">
      <div className="confidence-bar__track">
        <div
          className={`confidence-bar__fill ${sufficient ? "confidence-bar__fill--ok" : "confidence-bar__fill--low"}`}
          style={{ width: `${pct}%` }}
        />
        <div className="confidence-bar__threshold" style={{ left: `${thresholdPct}%` }} />
      </div>
      <span className="confidence-bar__label">
        confidence {value.toFixed(2)} {sufficient ? "≥" : "<"} threshold {threshold.toFixed(2)}
      </span>
    </div>
  );
}
