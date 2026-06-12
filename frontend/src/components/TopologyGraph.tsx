import type { ExecutorId, StepPayload } from "../types";

// Topologie miroir de `src/orchestrator/graph.py` :
//
//   LogAnalyzer -> IncidentExtractor -> KBSearch -> RootCause --[switch]--+
//                        ^                                                |
//                        | confiance < seuil ET loop_count < max          | sinon
//                        +---------------- GatherEvidence <---------------+
//                                                                          v
//                                                             HumanApproval (HITL)
//                                                                          | approuve
//                                                                          v
//                                                         Remediation -> Summary

interface NodeDef {
  id: ExecutorId;
  label: string;
  sub: string;
  x: number;
  y: number;
}

const NODE_W = 150;
const NODE_H = 56;

const NODES: NodeDef[] = [
  { id: "log_analyzer", label: "Log Analyzer", sub: "agent 1/6", x: 20, y: 20 },
  { id: "incident_extractor", label: "Incident Extractor", sub: "agent 2/6", x: 200, y: 20 },
  { id: "kb_search", label: "KB Search", sub: "agent 3/6", x: 380, y: 20 },
  { id: "root_cause", label: "Root Cause", sub: "agent 4/6", x: 560, y: 20 },
  { id: "human_approval", label: "Validation humaine", sub: "HITL", x: 740, y: 20 },
  { id: "remediation", label: "Remediation", sub: "agent 5/6", x: 920, y: 20 },
  { id: "summary", label: "Summary", sub: "agent 6/6", x: 1100, y: 20 },
  { id: "gather_evidence", label: "Gather Evidence", sub: "reflexion", x: 560, y: 150 },
];

const VIEWBOX_W = 1270;
const VIEWBOX_H = 230;

const NODE_BY_ID = new Map(NODES.map((node) => [node.id, node]));

interface EdgeDef {
  from: ExecutorId;
  to: ExecutorId;
  path: string;
}

function rightCenter(node: NodeDef): [number, number] {
  return [node.x + NODE_W, node.y + NODE_H / 2];
}

function leftCenter(node: NodeDef): [number, number] {
  return [node.x, node.y + NODE_H / 2];
}

const logAnalyzer = NODE_BY_ID.get("log_analyzer")!;
const incidentExtractor = NODE_BY_ID.get("incident_extractor")!;
const kbSearch = NODE_BY_ID.get("kb_search")!;
const rootCause = NODE_BY_ID.get("root_cause")!;
const humanApproval = NODE_BY_ID.get("human_approval")!;
const remediation = NODE_BY_ID.get("remediation")!;
const summary = NODE_BY_ID.get("summary")!;
const gatherEvidence = NODE_BY_ID.get("gather_evidence")!;

const EDGES: EdgeDef[] = [
  { from: "log_analyzer", to: "incident_extractor", path: straight(logAnalyzer, incidentExtractor) },
  { from: "incident_extractor", to: "kb_search", path: straight(incidentExtractor, kbSearch) },
  { from: "kb_search", to: "root_cause", path: straight(kbSearch, rootCause) },
  { from: "root_cause", to: "human_approval", path: straight(rootCause, humanApproval) },
  { from: "human_approval", to: "remediation", path: straight(humanApproval, remediation) },
  { from: "remediation", to: "summary", path: straight(remediation, summary) },
  {
    from: "root_cause",
    to: "gather_evidence",
    path: `M ${rootCause.x + NODE_W / 2 - 24} ${rootCause.y + NODE_H} V ${gatherEvidence.y}`,
  },
  {
    from: "gather_evidence",
    to: "root_cause",
    path: `M ${gatherEvidence.x + NODE_W / 2 + 24} ${gatherEvidence.y} V ${rootCause.y + NODE_H}`,
  },
];

function straight(from: NodeDef, to: NodeDef): string {
  const [x1, y1] = rightCenter(from);
  const [x2] = leftCenter(to);
  return `M ${x1} ${y1} H ${x2}`;
}

/** Paires d'evenements `step` consecutifs, dans l'ordre d'execution. */
function consecutivePairs(steps: StepPayload[]): Set<string> {
  const pairs = new Set<string>();
  for (let i = 1; i < steps.length; i++) {
    pairs.add(`${steps[i - 1].executor_id}->${steps[i].executor_id}`);
  }
  return pairs;
}

/**
 * `HumanApprovalExecutor` ne produit un `step` (executor_id="human_approval")
 * qu'en cas de refus (src/orchestrator/executors.py) : en cas d'approbation,
 * il transmet directement a `remediation` sans `yield_output`. On en deduit
 * le passage par la porte HITL et l'arete `root_cause -> human_approval`.
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

interface TopologyGraphProps {
  steps: StepPayload[];
  running: boolean;
  awaitingApproval: boolean;
}

export default function TopologyGraph({ steps, running, awaitingApproval }: TopologyGraphProps) {
  const visited = visitedIds(steps);
  const traveled = traveledEdges(steps);
  const activeId: ExecutorId | null = awaitingApproval
    ? "human_approval"
    : running && steps.length > 0
      ? steps[steps.length - 1].executor_id
      : null;

  return (
    <svg
      className="topology"
      viewBox={`0 0 ${VIEWBOX_W} ${VIEWBOX_H}`}
      role="img"
      aria-label="Graphe d'orchestration des agents"
    >
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
        </marker>
      </defs>

      {EDGES.map((edge) => {
        const key = `${edge.from}->${edge.to}`;
        const isTraveled = traveled.has(key);
        return (
          <path
            key={key}
            d={edge.path}
            className={`topology-edge${isTraveled ? " topology-edge--traveled" : ""}`}
            markerEnd="url(#arrow)"
          />
        );
      })}

      {NODES.map((node) => {
        const isVisited = visited.has(node.id);
        const isActive = node.id === activeId;
        const stateClass = isActive
          ? "topology-node--active"
          : isVisited
            ? "topology-node--visited"
            : "topology-node--pending";
        return (
          <g key={node.id} className={`topology-node ${stateClass}`} transform={`translate(${node.x}, ${node.y})`}>
            <rect width={NODE_W} height={NODE_H} rx={10} />
            <text x={NODE_W / 2} y={22} textAnchor="middle" className="topology-node__label">
              {node.label}
            </text>
            <text x={NODE_W / 2} y={40} textAnchor="middle" className="topology-node__sub">
              {node.sub}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
