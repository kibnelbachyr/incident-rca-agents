import { useEffect, useRef } from "react";

export interface FeedEntry {
  id: string;
  type: "start" | "agent" | "route" | "hitl" | "done" | "error";
  code?: string;
  label: string;
  detail: string;
}

interface ActivityFeedProps {
  entries: FeedEntry[];
}

const ICONS: Record<FeedEntry["type"], string> = {
  start: "▶",
  agent: "✓",
  route: "↩",
  hitl: "⏸",
  done: "◼",
  error: "✗",
};

export default function ActivityFeed({ entries }: ActivityFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  return (
    <div className="activity-feed">
      <div className="activity-feed__header">
        <span className="activity-feed__title">Orchestration Log</span>
        {entries.length > 0 && (
          <span className="activity-feed__count">{entries.length}</span>
        )}
      </div>
      <div className="activity-feed__body">
        {entries.length === 0 ? (
          <p className="activity-feed__empty">Waiting for run to start…</p>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.id}
              className={`activity-feed__entry activity-feed__entry--${entry.type}`}
            >
              <span className="activity-feed__icon">{ICONS[entry.type]}</span>
              {entry.code ? (
                <span className="activity-feed__code">{entry.code}</span>
              ) : (
                <span className="activity-feed__code activity-feed__code--empty" />
              )}
              <div className="activity-feed__text">
                <span className="activity-feed__label">{entry.label}</span>
                <span className="activity-feed__detail">{entry.detail}</span>
              </div>
            </div>
          ))
        )}
        <div ref={bottomRef} aria-hidden="true" />
      </div>
    </div>
  );
}
