import type { ReportPayload, RunStatus, RunSummary, StreamEvent } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

export async function getHealth(): Promise<Record<string, unknown>> {
  const r = await fetch(`${API_BASE}/api/health`, { cache: "no-store" });
  if (!r.ok) throw new Error(`Health check failed: ${r.status}`);
  return r.json();
}

export async function listRuns(): Promise<RunSummary[]> {
  const r = await fetch(`${API_BASE}/api/runs`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listRuns: ${r.status}`);
  const data = (await r.json()) as { items: RunSummary[] };
  return data.items;
}

export async function getRun(
  slug: string,
): Promise<{ slug: string; report: ReportPayload; markdown: string }> {
  const r = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(slug)}`, {
    cache: "no-store",
  });
  if (!r.ok) {
    if (r.status === 404) throw new Error("Run not found.");
    throw new Error(`getRun: ${r.status}`);
  }
  return r.json();
}

export interface StartAnalyzeResponse {
  run_id: string;
  status: RunStatus;
}

export async function startAnalyze(
  input: string,
  opts?: { no_self_critique?: boolean },
): Promise<StartAnalyzeResponse> {
  const r = await fetch(`${API_BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      input,
      no_self_critique: opts?.no_self_critique ?? false,
    }),
  });
  if (!r.ok) throw new Error(`startAnalyze: ${r.status}`);
  return r.json();
}

export interface RunStatusResponse {
  run_id: string;
  input: string;
  status: RunStatus;
  report_slug: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  slug?: string;
  report?: ReportPayload;
  markdown?: string;
}

export async function getRunStatus(runId: string): Promise<RunStatusResponse> {
  const r = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(runId)}`, {
    cache: "no-store",
  });
  if (!r.ok) {
    if (r.status === 404) throw new Error("Run not found.");
    throw new Error(`getRunStatus: ${r.status}`);
  }
  return r.json();
}

export async function cancelRun(runId: string): Promise<void> {
  const r = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
  if (!r.ok && r.status !== 404) {
    throw new Error(`cancelRun: ${r.status}`);
  }
}

export function subscribeRunEvents(
  runId: string,
  onEvent: (e: StreamEvent) => void,
  opts?: { signal?: AbortSignal; onError?: (err: Error) => void },
): () => void {
  const ctrl = new AbortController();
  if (opts?.signal) {
    if (opts.signal.aborted) ctrl.abort();
    else opts.signal.addEventListener("abort", () => ctrl.abort());
  }

  (async () => {
    try {
      const resp = await fetch(
        `${API_BASE}/api/runs/${encodeURIComponent(runId)}/events`,
        {
          headers: { Accept: "text/event-stream" },
          signal: ctrl.signal,
          cache: "no-store",
        },
      );
      if (!resp.ok || !resp.body) {
        throw new Error(`subscribeRunEvents: ${resp.status}`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const chunk = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const parsed = parseSseChunk(chunk);
          if (parsed) onEvent(parsed);
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      opts?.onError?.(err as Error);
    }
  })();

  return () => ctrl.abort();
}

function parseSseChunk(chunk: string): StreamEvent | null {
  const lines = chunk.split("\n");
  let data = "";
  for (const line of lines) {
    if (line.startsWith("data:")) {
      data += line.slice(5).trim();
    }
  }
  if (!data) return null;
  try {
    const obj = JSON.parse(data) as StreamEvent;
    return obj;
  } catch {
    return null;
  }
}
