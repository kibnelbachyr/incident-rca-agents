// Client HTTP/SSE pour `src/api/*.py`. Les deux endpoints d'execution
// (`POST /api/runs` et `POST /api/runs/{id}/approval`) renvoient un flux SSE
// (`text/event-stream`) ; `EventSource` ne supportant pas les requetes POST,
// on parse le flux nous-memes via `fetch` + `ReadableStream`.

import type {
  IncidentRecord,
  IncidentRecordSummary,
  MetaResponse,
  RemediationApprovalRequest,
  ScenariosResponse,
  StepPayload,
} from "./types";

export interface RunStartedData {
  run_id: string;
}

export interface ApprovalRequiredData {
  request: RemediationApprovalRequest;
}

export interface DoneData {
  approved: boolean | null;
}

export interface ErrorData {
  message: string;
}

export interface StreamHandlers {
  onRunStarted?: (data: RunStartedData) => void;
  onStep?: (data: StepPayload) => void;
  onApprovalRequired?: (data: ApprovalRequiredData) => void;
  onDone?: (data: DoneData) => void;
  onError?: (data: ErrorData) => void;
}

/** Envoie `POST url` et dispatche chaque evenement SSE recu vers `handlers`. */
async function streamPost(url: string, body: unknown, handlers: StreamHandlers): Promise<void> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

  if (!response.ok || !response.body) {
    throw new Error(`Request ${url} failed (HTTP ${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let separator = buffer.indexOf("\n\n");
    while (separator !== -1) {
      dispatch(buffer.slice(0, separator), handlers);
      buffer = buffer.slice(separator + 2);
      separator = buffer.indexOf("\n\n");
    }
  }
}

function dispatch(rawEvent: string, handlers: StreamHandlers): void {
  let eventName = "message";
  const dataLines: string[] = [];

  for (const line of rawEvent.split("\n")) {
    if (line.startsWith("event: ")) {
      eventName = line.slice("event: ".length);
    } else if (line.startsWith("data: ")) {
      dataLines.push(line.slice("data: ".length));
    }
  }

  if (dataLines.length === 0) return;
  const data = JSON.parse(dataLines.join("\n"));

  switch (eventName) {
    case "run_started":
      handlers.onRunStarted?.(data as RunStartedData);
      break;
    case "step":
      handlers.onStep?.(data as StepPayload);
      break;
    case "approval_required":
      handlers.onApprovalRequired?.(data as ApprovalRequiredData);
      break;
    case "done":
      handlers.onDone?.(data as DoneData);
      break;
    case "error":
      handlers.onError?.(data as ErrorData);
      break;
  }
}

/** `POST /api/runs` : demarre une nouvelle execution sur le scenario choisi. */
export function startRun(scenario: string, handlers: StreamHandlers): Promise<void> {
  return streamPost("/api/runs", { scenario }, handlers);
}

/** `POST /api/runs/{runId}/approval` : reprend l'execution apres decision humaine. */
export function submitApproval(runId: string, approved: boolean, handlers: StreamHandlers): Promise<void> {
  return streamPost(`/api/runs/${runId}/approval`, { approved }, handlers);
}

export async function fetchMeta(): Promise<MetaResponse> {
  const response = await fetch("/api/meta");
  if (!response.ok) throw new Error("Configuration unavailable");
  return (await response.json()) as MetaResponse;
}

export async function fetchScenarios(): Promise<ScenariosResponse> {
  const response = await fetch("/api/scenarios");
  if (!response.ok) throw new Error("Scenarios unavailable");
  return (await response.json()) as ScenariosResponse;
}

export async function fetchHistory(limit = 20): Promise<IncidentRecordSummary[]> {
  const response = await fetch(`/api/history?limit=${limit}`);
  if (!response.ok) throw new Error("History unavailable");
  return (await response.json()) as IncidentRecordSummary[];
}

export async function fetchHistoryRecord(runId: string): Promise<IncidentRecord> {
  const response = await fetch(`/api/history/${runId}`);
  if (!response.ok) throw new Error("Run not found");
  return (await response.json()) as IncidentRecord;
}
