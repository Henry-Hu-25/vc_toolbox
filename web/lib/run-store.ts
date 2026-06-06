"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import {
  cancelRun as apiCancelRun,
  getRunStatus,
  startAnalyze,
  subscribeRunEvents,
} from "./api";
import type {
  CostLedger,
  RunStatus,
  StreamEvent,
} from "./types";

export type StepState = "pending" | "running" | "done" | "warning";

export interface Step {
  id: string;
  label: string;
  state: StepState;
}

const NODE_ORDER = [
  "company_profiler",
  "founder_finder",
  "founder_researcher",
  "overlap_analyzer",
  "team_scorer",
  "report_writer",
] as const;

const NODE_LABELS: Record<string, string> = {
  company_profiler: "Resolving company",
  founder_finder: "Identifying founders",
  founder_researcher: "Researching founders",
  overlap_analyzer: "Analyzing shared history",
  team_scorer: "Scoring against rubric",
  report_writer: "Rendering report",
};

function initialSteps(): Step[] {
  return NODE_ORDER.map((id) => ({
    id,
    label: NODE_LABELS[id],
    state: "pending",
  }));
}

interface RunState {
  runId: string | null;
  status: RunStatus | "idle";
  input: string | null;
  steps: Step[];
  cost: CostLedger | null;
  warnings: string[];
  error: string | null;
  slug: string | null;
  _unsubscribe: (() => void) | null;
  _hydrating: boolean;
}

interface RunActions {
  startRun: (input: string, opts?: { no_self_critique?: boolean }) => Promise<string>;
  subscribe: (runId: string) => void;
  cancelRun: () => Promise<void>;
  hydrate: () => Promise<void>;
  reset: () => void;
  _applyEvent: (event: StreamEvent) => void;
}

type Store = RunState & RunActions;

const INITIAL: RunState = {
  runId: null,
  status: "idle",
  input: null,
  steps: initialSteps(),
  cost: null,
  warnings: [],
  error: null,
  slug: null,
  _unsubscribe: null,
  _hydrating: false,
};

export const useRunStore = create<Store>()(
  persist(
    (set, get) => ({
      ...INITIAL,

      reset: () => {
        const u = get()._unsubscribe;
        if (u) u();
        set({ ...INITIAL, steps: initialSteps(), _unsubscribe: null });
      },

      startRun: async (input, opts) => {
        const prev = get()._unsubscribe;
        if (prev) prev();
        set({
          ...INITIAL,
          steps: initialSteps(),
          status: "pending",
          input,
          _unsubscribe: null,
          _hydrating: false,
        });
        try {
          const resp = await startAnalyze(input, opts);
          set({ runId: resp.run_id, status: resp.status });
          get().subscribe(resp.run_id);
          return resp.run_id;
        } catch (err) {
          const msg =
            err instanceof Error
              ? err.message
              : "Failed to start analysis. Check that the backend is running.";
          set({ status: "failed", error: msg });
          throw err;
        }
      },

      subscribe: (runId) => {
        const prev = get()._unsubscribe;
        if (prev) prev();
        const unsub = subscribeRunEvents(
          runId,
          (evt) => get()._applyEvent(evt),
          {
            onError: (err) =>
              set({ error: err.message || "subscription failed" }),
          },
        );
        set({ _unsubscribe: unsub });
      },

      cancelRun: async () => {
        const { runId, _unsubscribe } = get();
        if (!runId) return;
        // Optimistic: unsubscribe and set cancelled BEFORE the DELETE round-trip
        // so the UI never flashes "Run failed" from a trailing error event.
        if (_unsubscribe) _unsubscribe();
        set({ status: "cancelled", error: null, _unsubscribe: null });
        // Fire-and-forget DELETE (best effort — UI state is already set)
        try {
          await apiCancelRun(runId);
        } catch {
          // best effort — UI state is already cancelled
        }
      },

      hydrate: async () => {
        const runId = get().runId;
        if (!runId) return;
        set({ _hydrating: true });
        try {
          const status = await getRunStatus(runId);
          // If startRun() was called while we were awaiting, it won the race.
          // Do not overwrite its state or subscribe to the stale runId.
          const current = get();
          if (!current._hydrating || current.runId !== runId) return;

          if (
            status.status === "completed" ||
            status.status === "failed" ||
            status.status === "cancelled"
          ) {
            set({
              status: status.status,
              slug: status.report_slug ?? status.slug ?? null,
              error: status.error ?? null,
              _hydrating: false,
            });
            return;
          }
          set({
            status: status.status,
            input: status.input,
            slug: status.report_slug ?? null,
            _hydrating: false,
          });
          get().subscribe(runId);
        } catch (err) {
          const msg = (err as Error).message || "";
          if (msg.includes("not found") || msg.includes("404")) {
            // Only reset if no startRun has claimed the store in the meantime.
            const current = get();
            if (current._hydrating && current.runId === runId) {
              set({ ...INITIAL, steps: initialSteps(), _unsubscribe: null, _hydrating: false });
            }
          }
        }
      },

      _applyEvent: (event) => {
        set((state) => {
          const next: Partial<RunState> = {};
          const steps = state.steps.map((s) => ({ ...s }));
          if (event.type === "run_started") {
            next.status = "running";
          } else if (event.type === "node_started") {
            const node = String(event.payload.node);
            const idx = steps.findIndex((s) => s.id === node);
            if (idx >= 0) {
              for (let i = 0; i < idx; i++) {
                if (steps[i].state === "pending") steps[i].state = "done";
              }
              steps[idx].state = "running";
            }
            next.status = "running";
          } else if (event.type === "node_finished") {
            const node = String(event.payload.node);
            const idx = steps.findIndex((s) => s.id === node);
            if (idx >= 0) {
              const warnings = (event.payload.warnings as string[]) || [];
              steps[idx].state = warnings.length > 0 ? "warning" : "done";
            }
          } else if (event.type === "warning") {
            next.warnings = [
              ...state.warnings,
              String(event.payload.text),
            ];
          } else if (event.type === "cost_update") {
            next.cost = event.payload as unknown as CostLedger;
          } else if (event.type === "done") {
            const slug = String(event.payload.slug || "");
            for (const s of steps) {
              if (s.state === "pending" || s.state === "running") {
                s.state = "done";
              }
            }
            next.status = "completed";
            next.slug = slug || null;
          } else if (event.type === "error") {
            // Ignore trailing error events from cancellation when the store
            // already says cancelled — prevents flashing "Run failed" UI.
            const msg = String(event.payload.message || "Unknown error");
            if (
              state.status === "cancelled" &&
              msg.toLowerCase().includes("cancelled")
            ) {
              // stale cancellation error — skip
            } else {
              next.status = "failed";
              next.error = msg;
            }
          }
          next.steps = steps;
          return next as RunState;
        });
      },
    }),
    {
      name: "fta:run",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        runId: state.runId,
        status: state.status,
        input: state.input,
        steps: state.steps,
        cost: state.cost,
        warnings: state.warnings,
        error: state.error,
        slug: state.slug,
      }),
    },
  ),
);

export function isTerminal(status: RunStatus | "idle"): boolean {
  return (
    status === "completed" || status === "failed" || status === "cancelled"
  );
}
