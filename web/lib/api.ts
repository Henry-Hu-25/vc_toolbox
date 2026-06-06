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
      const sepRe = /\r?\n\r?\n/;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let m: RegExpMatchArray | null;
        while ((m = buffer.match(sepRe)) !== null) {
          const chunk = buffer.slice(0, m.index!);
          buffer = buffer.slice(m.index! + m[0].length);
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
  const lines = chunk.split(/\r?\n/);
  const dataParts: string[] = [];
  for (const line of lines) {
    if (line.startsWith("data:")) {
      dataParts.push(line.slice(5).trimStart());
    }
  }
  if (dataParts.length === 0) return null;
  const data = dataParts.join("\n");
  try {
    const obj = JSON.parse(data) as StreamEvent;
    return obj;
  } catch {
    return null;
  }
}
