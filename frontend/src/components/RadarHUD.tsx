import type { ExecutorId, StepPayload } from "../types";

// Mirrors the topology of `src/orchestrator/graph.py`:
//
//   LogAnalyzer -> IncidentExtractor -> KBSearch -> RootCause --[switch]--+
//                        ^                                                |
//                        | confidence < threshold AND loop_count < max    | else
//                        +---------------- GatherEvidence <---------------+
//                                                                          v
//                                                             HumanApproval (HITL)
//                                                                          | approved
//                                                                          v
//                                                         Remediation -> Summary
//
// The 8 executors are placed around the radar ring at 45-degree increments,
// in execution order, with the reflection-loop node (GatherEvidence) sharing
// the ring between RootCause and HumanApproval.

interface NodeDef {
  id: ExecutorId;
  code: string;
  label: string;
  /** Degrees clockwise from top (12 o'clock). */
  angle: number;
  labelDx: number;
  labelDy: number;
  anchor: "start" | "middle" | "end";
}

const CENTER = 290;
const RADIUS = 190;

const NODES: NodeDef[] = [
  { id: "log_analyzer", code: "01", label: "Log Analyzer", angle: 0, labelDx: 0, labelDy: -34, anchor: "middle" },
  {
    id: "incident_extractor",
    code: "02",
    label: "Incident Extractor",
    angle: 45,
    labelDx: 24,
    labelDy: -18,
    anchor: "start",
  },
  { id: "kb_search", code: "03", label: "KB Search", angle: 90, labelDx: 28, labelDy: 5, anchor: "start" },
  { id: "root_cause", code: "04", label: "Root Cause", angle: 135, labelDx: 24, labelDy: 32, anchor: "start" },
  {
    id: "gather_evidence",
    code: "RX",
    label: "Gather Evidence",
    angle: 180,
    labelDx: 0,
    labelDy: 44,
    anchor: "middle",
  },
  {
    id: "human_approval",
    code: "HITL",
    label: "Human Approval",
    angle: 225,
    labelDx: -24,
    labelDy: 32,
    anchor: "end",
  },
  { id: "remediation", code: "05", label: "Remediation", angle: 270, labelDx: -28, labelDy: 5, anchor: "end" },
  { id: "summary", code: "06", label: "Summary", angle: 315, labelDx: -24, labelDy: -18, anchor: "end" },
];

const NODE_BY_ID = new Map(NODES.map((node) => [node.id, node]));

function position(angle: number, radius: number): [number, number] {
  const rad = (angle * Math.PI) / 180;
  return [CENTER + radius * Math.sin(rad), CENTER - radius * Math.cos(rad)];
}

interface EdgeDef {
  from: ExecutorId;
  to: ExecutorId;
  loop?: boolean;
}

const EDGES: EdgeDef[] = [
  { from: "log_analyzer", to: "incident_extractor" },
  { from: "incident_extractor", to: "kb_search" },
  { from: "kb_search", to: "root_cause" },
  { from: "root_cause", to: "human_approval" },
  { from: "human_approval", to: "remediation" },
  { from: "remediation", to: "summary" },
  { from: "root_cause", to: "gather_evidence", loop: true },
];

/** Consecutive `step` pairs, in execution order. */
function consecutivePairs(steps: StepPayload[]): Set<string> {
  const pairs = new Set<string>();
  for (let i = 1; i < steps.length; i++) {
    pairs.add(`${steps[i - 1].executor_id}->${steps[i].executor_id}`);
  }
  return pairs;
}

/**
 * `HumanApprovalExecutor` only yields a `step` (executor_id="human_approval")
 * on rejection (src/orchestrator/executors.py): on approval it falls through
 * directly to `remediation` without `yield_output`. We infer passage through
 * the HITL gate, and the `root_cause -> human_approval` edge, from that.
 */
function visitedIds(steps: StepPayload[]): Set<ExecutorId> {
  const ids = new Set(steps.map((step) => step.executor_id));
  if (ids.has("remediation") || ids.has("summary")) {
    ids.add("human_approval");
  }
  return ids;
}

function traveledEdges(steps: StepPayload[]): Set<string> {
  const traveled = consecutivePairs(steps);
  const ids = new Set(steps.map((step) => step.executor_id));
  if (ids.has("remediation")) {
    traveled.add("root_cause->human_approval");
    traveled.add("human_approval->remediation");
  }
  if (ids.has("summary")) {
    traveled.add("remediation->summary");
  }
  return traveled;
}

export type Phase = "idle" | "running" | "awaiting_approval" | "done" | "error";

interface RadarHUDProps {
  steps: StepPayload[];
  phase: Phase;
  runId: string | null;
  selectedId: ExecutorId | null;
  onSelect: (id: ExecutorId) => void;
}

export default function RadarHUD({ steps, phase, runId, selectedId, onSelect }: RadarHUDProps) {
  const visited = visitedIds(steps);
  const traveled = traveledEdges(steps);
  // `human_approval` is added to `visited` by inference when remediation proceeds
  // (see `visitedIds`), but on approval it never yields its own `step` payload —
  // so it has nothing to show in the detail panel and must stay non-clickable.
  const withData = new Set(steps.map((step) => step.executor_id));
  const running = phase === "running";
  const awaitingApproval = phase === "awaiting_approval";

  const activeId: ExecutorId | null = awaitingApproval
    ? "human_approval"
    : running && steps.length > 0
      ? steps[steps.length - 1].executor_id
      : null;

  const sweepClass = awaitingApproval
    ? "radar-hud__sweep radar-hud__sweep--active radar-hud__sweep--alert"
    : running
      ? "radar-hud__sweep radar-hud__sweep--active"
      : "radar-hud__sweep";

  const readout = phaseReadout(phase, activeId);
  const size = CENTER * 2;

  return (
    <div className="radar-hud">
      <div className="radar-hud__frame">
        <div className={sweepClass} />
        <svg className="radar-hud__svg" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Agent orchestration radar">
          {[0.27, 0.52, 0.76, 1].map((fraction) => (
            <circle
              key={fraction}
              className={`radar-ring${fraction === 1 ? " radar-ring--outer" : ""}`}
              cx={CENTER}
              cy={CENTER}
              r={RADIUS * fraction}
            />
          ))}
          <line className="radar-crosshair" x1={CENTER - RADIUS} y1={CENTER} x2={CENTER + RADIUS} y2={CENTER} />
          <line className="radar-crosshair" x1={CENTER} y1={CENTER - RADIUS} x2={CENTER} y2={CENTER + RADIUS} />

          {EDGES.map((edge) => {
            const from = NODE_BY_ID.get(edge.from)!;
            const to = NODE_BY_ID.get(edge.to)!;
            const [x1, y1] = position(from.angle, RADIUS);
            const [x2, y2] = position(to.angle, RADIUS);
            const key = `${edge.from}->${edge.to}`;
            const reverseKey = `${edge.to}->${edge.from}`;
            const isTraveled = traveled.has(key) || traveled.has(reverseKey);
            return (
              <line
                key={key}
                className={`radar-chord${isTraveled ? " radar-chord--traveled" : ""}${edge.loop ? " radar-chord--loop" : ""}`}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
              />
            );
          })}

          {NODES.map((node) => {
            const [x, y] = position(node.angle, RADIUS);
            const isVisited = visited.has(node.id);
            const isActive = node.id === activeId;
            const isSelected = node.id === selectedId;
            const isAlert = isActive && awaitingApproval;
            const stateClass = isAlert
              ? "radar-node--alert"
              : isActive
                ? "radar-node--active"
                : isVisited
                  ? "radar-node--visited"
                  : "radar-node--pending";
            const clickable = withData.has(node.id);

            return (
              <g
                key={node.id}
                className={`radar-node ${stateClass}${isSelected ? " radar-node--selected" : ""}`}
                transform={`translate(${x}, ${y})`}
                onClick={clickable ? () => onSelect(node.id) : undefined}
                onKeyDown={
                  clickable
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onSelect(node.id);
                        }
                      }
                    : undefined
                }
                role={clickable ? "button" : undefined}
                tabIndex={clickable ? 0 : undefined}
                aria-label={clickable ? `${node.label} — view details` : node.label}
              >
                <circle className="radar-node__halo" r={22} />
                <circle className="radar-node__core" r={20} />
                <text className="radar-node__code" textAnchor="middle" dy="4">
                  {node.code}
                </text>
                <text className="radar-node__label" x={node.labelDx} y={node.labelDy} textAnchor={node.anchor}>
                  {node.label}
                </text>
              </g>
            );
          })}
        </svg>

        <div className="radar-hud__readout">
          <span className="radar-hud__readout-label">Status</span>
          <span className={`radar-hud__readout-value${readout.alert ? " radar-hud__readout-value--alert" : ""}`}>
            {readout.text}
          </span>
          {runId && <span className="radar-hud__readout-run">RUN {runId.slice(0, 8)}</span>}
        </div>
      </div>
    </div>
  );
}

function phaseReadout(phase: Phase, activeId: ExecutorId | null): { text: string; alert: boolean } {
  switch (phase) {
    case "idle":
      return { text: "Standby", alert: false };
    case "running":
      return { text: activeId ? NODE_BY_ID.get(activeId)!.label : "Initializing", alert: false };
    case "awaiting_approval":
      return { text: "Awaiting Approval", alert: true };
    case "done":
      return { text: "Complete", alert: false };
    case "error":
      return { text: "Error", alert: true };
  }
}
