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
// Rendered as a left-to-right pipeline: the 7 trunk stages run along the main
// rail (chevron stages, with the HITL gate drawn as a diamond), while the
// reflection loop (RootCause -> GatherEvidence -> IncidentExtractor) is drawn
// as an underpass lane beneath KBSearch/RootCause.

export type Phase = "idle" | "running" | "awaiting_approval" | "done" | "error";

type NodeShape = "chevron" | "diamond" | "loop";

interface NodeDef {
  id: ExecutorId;
  code: string;
  label: string;
  x: number;
  y: number;
  shape: NodeShape;
}

const VIEW_W = 1280;
const VIEW_H = 260;
const MAIN_Y = 84;
const LOOP_Y = 200;
const CHEVRON_W = 152;
const CHEVRON_H = 64;
const NOTCH = 18;
const DIAMOND = 82;
const LOOP_W = 144;
const LOOP_H = 58;

const NODES: NodeDef[] = [
  { id: "log_analyzer", code: "01", label: "Log Analyzer", x: 96, y: MAIN_Y, shape: "chevron" },
  { id: "incident_extractor", code: "02", label: "Incident Extractor", x: 278, y: MAIN_Y, shape: "chevron" },
  { id: "kb_search", code: "03", label: "KB Search", x: 460, y: MAIN_Y, shape: "chevron" },
  { id: "root_cause", code: "04", label: "Root Cause", x: 642, y: MAIN_Y, shape: "chevron" },
  { id: "human_approval", code: "HITL", label: "Human Approval", x: 824, y: MAIN_Y, shape: "diamond" },
  { id: "remediation", code: "05", label: "Remediation", x: 1006, y: MAIN_Y, shape: "chevron" },
  { id: "summary", code: "06", label: "Summary", x: 1188, y: MAIN_Y, shape: "chevron" },
  { id: "gather_evidence", code: "RX", label: "Gather Evidence", x: 556, y: LOOP_Y, shape: "loop" },
];

const NODE_BY_ID = new Map(NODES.map((node) => [node.id, node]));

/** Trunk order, left to right. */
const MAIN_ORDER: ExecutorId[] = [
  "log_analyzer",
  "incident_extractor",
  "kb_search",
  "root_cause",
  "human_approval",
  "remediation",
  "summary",
];

const MAIN_EDGES: [ExecutorId, ExecutorId][] = [
  ["log_analyzer", "incident_extractor"],
  ["incident_extractor", "kb_search"],
  ["kb_search", "root_cause"],
  ["root_cause", "human_approval"],
  ["human_approval", "remediation"],
  ["remediation", "summary"],
];

/** Reflection loop, drawn as a curved underpass beneath KBSearch/RootCause. */
const LOOP_EDGES: { key: string; d: string }[] = [
  { key: "root_cause->gather_evidence", d: "M 620 116 C 620 150, 600 148, 600 171" },
  { key: "gather_evidence->incident_extractor", d: "M 512 171 C 430 171, 330 148, 278 116" },
];

function halfWidth(shape: NodeShape): number {
  switch (shape) {
    case "diamond":
      return DIAMOND / 2;
    case "loop":
      return LOOP_W / 2;
    default:
      return CHEVRON_W / 2;
  }
}

function labelDy(shape: NodeShape): number {
  switch (shape) {
    case "diamond":
      return DIAMOND / 2 + 18;
    case "loop":
      return LOOP_H / 2 + 18;
    default:
      return CHEVRON_H / 2 + 18;
  }
}

/** Arrow-shaped pipeline stage: flat sides, a notch on the left, a point on the right. */
function chevronPath(w: number, h: number, notch: number): string {
  const x0 = -w / 2;
  const x1 = w / 2;
  const y0 = -h / 2;
  const y1 = h / 2;
  return `M ${x0} ${y0} L ${x1 - notch} ${y0} L ${x1} 0 L ${x1 - notch} ${y1} L ${x0} ${y1} L ${x0 + notch} 0 Z`;
}

/** Diamond "gate" shape for the HITL decision point. */
function diamondPath(size: number): string {
  const r = size / 2;
  return `M 0 ${-r} L ${r} 0 L 0 ${r} L ${-r} 0 Z`;
}

function NodeShapeEl({ shape, className, fill }: { shape: NodeShape; className: string; fill?: string }) {
  switch (shape) {
    case "diamond":
      return <path className={className} fill={fill} d={diamondPath(DIAMOND)} />;
    case "loop":
      return (
        <rect
          className={className}
          fill={fill}
          x={-LOOP_W / 2}
          y={-LOOP_H / 2}
          width={LOOP_W}
          height={LOOP_H}
          rx={10}
        />
      );
    default:
      return <path className={className} fill={fill} d={chevronPath(CHEVRON_W, CHEVRON_H, NOTCH)} />;
  }
}

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

/** The edge leading to the current position: pulses while the run is live. */
function activeEdgeKey(steps: StepPayload[], awaitingApproval: boolean): string | null {
  if (awaitingApproval) return "root_cause->human_approval";
  if (steps.length < 2) return null;
  return `${steps[steps.length - 2].executor_id}->${steps[steps.length - 1].executor_id}`;
}

function edgeState(key: string, traveled: Set<string>, activeEdge: string | null): "pending" | "traveled" | "active" {
  if (key === activeEdge) return "active";
  if (traveled.has(key)) return "traveled";
  return "pending";
}

interface PipelineHUDProps {
  steps: StepPayload[];
  phase: Phase;
  runId: string | null;
  selectedId: ExecutorId | null;
  onSelect: (id: ExecutorId) => void;
}

export default function PipelineHUD({ steps, phase, runId, selectedId, onSelect }: PipelineHUDProps) {
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

  const activeEdge = running || awaitingApproval ? activeEdgeKey(steps, awaitingApproval) : null;

  const mainVisitedCount = MAIN_ORDER.filter((id) => visited.has(id)).length;
  const progressPct = (mainVisitedCount / MAIN_ORDER.length) * 100;

  const readout = phaseReadout(phase, activeId);

  return (
    <div className="pipeline-hud">
      <div className="pipeline-hud__frame">
        <div className="pipeline-hud__readout">
          <span className="pipeline-hud__readout-label">Pipeline Status</span>
          <span className={`pipeline-hud__readout-value${readout.alert ? " pipeline-hud__readout-value--alert" : ""}`}>
            {readout.text}
          </span>
          {runId && <span className="pipeline-hud__readout-run">RUN {runId.slice(0, 8)}</span>}
        </div>

        <svg
          className="pipeline-hud__svg"
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          role="img"
          aria-label="Agent orchestration pipeline"
        >
          <defs>
            <linearGradient id="pipeline-scan-active" x1="-60%" y1="0" x2="40%" y2="0">
              <stop offset="0%" stopColor="var(--primary)" stopOpacity="0" />
              <stop offset="50%" stopColor="var(--primary)" stopOpacity="0.85" />
              <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
              <animate attributeName="x1" values="-60%;160%" dur="1.4s" repeatCount="indefinite" />
              <animate attributeName="x2" values="40%;260%" dur="1.4s" repeatCount="indefinite" />
            </linearGradient>
            <linearGradient id="pipeline-scan-alert" x1="-60%" y1="0" x2="40%" y2="0">
              <stop offset="0%" stopColor="var(--alert)" stopOpacity="0" />
              <stop offset="50%" stopColor="var(--alert)" stopOpacity="0.85" />
              <stop offset="100%" stopColor="var(--alert)" stopOpacity="0" />
              <animate attributeName="x1" values="-60%;160%" dur="0.9s" repeatCount="indefinite" />
              <animate attributeName="x2" values="40%;260%" dur="0.9s" repeatCount="indefinite" />
            </linearGradient>
          </defs>

          {MAIN_EDGES.map(([from, to]) => {
            const a = NODE_BY_ID.get(from)!;
            const b = NODE_BY_ID.get(to)!;
            const key = `${from}->${to}`;
            const state = edgeState(key, traveled, activeEdge);
            return (
              <line
                key={key}
                className={`pipeline-edge pipeline-edge--${state}`}
                x1={a.x + halfWidth(a.shape)}
                y1={MAIN_Y}
                x2={b.x - halfWidth(b.shape)}
                y2={MAIN_Y}
              />
            );
          })}

          {LOOP_EDGES.map(({ key, d }) => {
            const state = edgeState(key, traveled, activeEdge);
            return <path key={key} className={`pipeline-edge pipeline-edge--loop pipeline-edge--${state}`} d={d} />;
          })}

          {NODES.map((node) => {
            const isVisited = visited.has(node.id);
            const isActive = node.id === activeId;
            const isSelected = node.id === selectedId;
            const isAlert = isActive && awaitingApproval;
            const stateClass = isAlert
              ? "pipeline-node--alert"
              : isActive
                ? "pipeline-node--active"
                : isVisited
                  ? "pipeline-node--visited"
                  : "pipeline-node--pending";
            const clickable = withData.has(node.id);

            return (
              <g
                key={node.id}
                className={`pipeline-node ${stateClass}${isSelected ? " pipeline-node--selected" : ""}`}
                transform={`translate(${node.x}, ${node.y})`}
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
                <NodeShapeEl shape={node.shape} className="pipeline-node__shape" />
                {(isActive || isAlert) && (
                  <NodeShapeEl
                    shape={node.shape}
                    className="pipeline-node__scan"
                    fill={isAlert ? "url(#pipeline-scan-alert)" : "url(#pipeline-scan-active)"}
                  />
                )}
                <text
                  className={`pipeline-node__code${node.code.length > 2 ? " pipeline-node__code--sm" : ""}`}
                  textAnchor="middle"
                  dy={node.code.length > 2 ? "5" : "7"}
                >
                  {node.code}
                </text>
                <text className="pipeline-node__label" textAnchor="middle" y={labelDy(node.shape)}>
                  {node.label}
                </text>
              </g>
            );
          })}
        </svg>

        <div className="pipeline-hud__progress">
          <div
            className={`pipeline-hud__progress-fill${phase === "error" ? " pipeline-hud__progress-fill--alert" : ""}`}
            style={{ width: `${progressPct}%` }}
          />
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
