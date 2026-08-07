# AGENTS.md

Instructions for AI coding agents working in this repository.

## Repository layout

```
vc_toolbox/
├── founding-team-analyzer-spec.md      # Canonical design doc — read before non-trivial edits
├── founding_team_analyzer/             # Python: LangGraph pipeline + FastAPI server
│   ├── pyproject.toml                  # Package + optional extras: [dev], [server]
│   ├── .env / .env.example             # OPENAI_API_KEY, TAVILY_API_KEY, FTA_* tuning knobs
│   ├── src/founding_team_analyzer/
│   │   ├── cli.py                      # Typer entrypoint (`python -m founding_team_analyzer`)
│   │   ├── server.py                   # FastAPI app — registry-backed run endpoints
│   │   ├── runs.py                     # In-process RunRegistry (pub/sub, replay, cancel)
│   │   ├── streaming_graph.py          # `stream_analysis()` → Event iterator
│   │   ├── graph.py                    # LangGraph node wiring
│   │   ├── nodes/                      # 6 LangGraph nodes (profiler → report_writer)
│   │   ├── tools/                      # search/fetch/normalize helpers
│   │   ├── prompts/                    # Markdown prompt templates
│   │   ├── schemas.py                  # Pydantic v2 models (also used as LLM output schemas)
│   │   ├── llm.py                      # ChatOpenAI factory + global call counter / budget
│   │   ├── scoring.py                  # Deterministic rubric weights & tier thresholds
│   │   └── events.py                   # SSE Event dataclass + node label map
│   ├── tests/                          # pytest (asyncio_mode = auto)
│   └── out/<slug>/                     # Generated reports (report.md + report.json)
└── web/                                # Next.js 15 (App Router) + Zustand UI
    ├── package.json                    # npm scripts: dev, build, start, lint
    ├── app/                            # layout.tsx mounts <RunHydrator/>
    ├── components/                     # analyze-form, progress-stepper, in-progress-pill, …
    └── lib/
        ├── api.ts                      # fetch wrappers + SSE parser
        ├── run-store.ts                # Zustand store w/ localStorage persistence
        └── types.ts                    # Mirrors Python Pydantic schemas
```

## Architecture, in two paragraphs

**Backend.** `POST /api/analyze` registers a run in the in-process `RunRegistry`
(`runs.py`), spawns `asyncio.create_task(_execute_run(...))`, and returns
`{run_id, status}` immediately — no SSE on the POST. The worker iterates
`stream_analysis()` (which drives the LangGraph in `graph.py`) and pipes events
into `registry.publish(...)`, which both buffers them for replay and fans them
out to live subscribers. SSE lives on `GET /api/runs/{id}/events`, so client
disconnects never cancel the task. Other endpoints: `DELETE /api/runs/{id}`
cancels the asyncio task, `GET /api/runs/{id}` returns status (plus the on-disk
report once a slug is set), and `GET /api/runs` merges in-flight registry runs
with on-disk reports in `out/`. The registry is in-memory only — in-flight runs
are lost on server restart (documented non-goal).

**Frontend.** All run state lives in the Zustand store in `lib/run-store.ts`,
persisted to `localStorage` so it survives tab closes. The store owns the SSE
subscription — components never open EventSources directly. `AnalyzeForm` calls
`startRun(input)`, which POSTs `/api/analyze` and then calls `subscribe(runId)`.
`<RunHydrator/>` mounts once in `app/layout.tsx` and, on app load, calls
`store.hydrate()` to re-fetch status and resubscribe if a previously-stored
`runId` is still running (or gracefully clear on 404). The home page's
`AnalyzeForm` shows the empty form when the persisted state is a "stale"
completion (see `staleSlugRef` for the exact rule that avoids redirect loops
on logo clicks).

## Run, test, build

| Task | Command |
|---|---|
| Backend deps | `cd founding_team_analyzer && python -m venv .venv && .venv/bin/pip install -e ".[dev,server]"` |
| Backend tests | `cd founding_team_analyzer && .venv/bin/python -m pytest` |
| Backend dev server | `cd founding_team_analyzer && .venv/bin/python -m uvicorn founding_team_analyzer.server:app --host 127.0.0.1 --port 8000` |
| Frontend deps | `cd web && npm install` |
| Frontend dev | `cd web && npm run dev` (http://localhost:3000) |
| Frontend typecheck | `cd web && npx tsc --noEmit` |
| Frontend build | `cd web && npm run build` |
| Frontend lint | `cd web && npm run lint` |

**Always** run the relevant test/typecheck/build before declaring a task done.
Pytest config lives in `founding_team_analyzer/pyproject.toml`
(`asyncio_mode = "auto"`, `testpaths = ["tests"]`).

## Environment

Backend reads `founding_team_analyzer/.env`. Required keys:

- `OPENAI_API_KEY`
- `TAVILY_API_KEY`

Tuning knobs (defaults in `config.py`):

- `FTA_MODEL_REASONING`, `FTA_MODEL_EXTRACT`
- `FTA_REASONING_EFFORT` (`none | low | medium | high | xhigh`)
- `FTA_MAX_FOUNDERS` — caps researcher fan-out
- `FTA_MAX_TAVILY_PER_FOUNDER`, `FTA_MAX_EXTRACTS_PER_FOUNDER`
- `FTA_MAX_LLM_CALLS` — global per-run circuit breaker. If the budget is
  exhausted before `TeamScorer` runs, the run fails with "TeamScore requires
  fields with no defaults." Raise this knob (not the model) to fix.
- `FTA_MAX_REGISTRY_RUNS` — max in-flight + terminal runs kept in the
  in-memory registry (default 100). Oldest terminal runs are evicted when
  the cap is exceeded.
- `FTA_CORS_ORIGINS` — comma-separated CORS allowed origins. Defaults to
  `http://localhost:3000,http://127.0.0.1:3000`.
- `FTA_OUTPUT_DIR` (default `./out`)

Frontend reads `NEXT_PUBLIC_API_BASE` (default `http://127.0.0.1:8000`).

## Conventions

### Python
- Python 3.11+. Use `from __future__ import annotations` in new modules.
- Pydantic v2 for any structured data. Schemas in `schemas.py` are
  double-duty: they're also `.with_structured_output(...)` targets for the
  LLM, so every required field must be obtainable from prompts or the run
  fails as in the budget case above.
- All direct network I/O goes through `tenacity` + an `httpx` timeout. The
  Tavily client is an exception — it wraps `requests` internally, so
  `search.py` catches `requests.exceptions.*` instead. Never raise out of a
  node — append a string to `state["warnings"]` and degrade.
- LLM calls must go through `llm.py` so the per-run counter / budget applies.
- Config must be accessed dynamically: use `from . import config as
  config_module` and read `config_module.SETTINGS` at call time — never
  `from .config import SETTINGS` which captures at import time and breaks
  CLI overrides.
- Logging via `structlog` (already configured); do not add `print()`.
- New endpoints belong on the FastAPI app in `server.py`. Long-lived work
  must register a run via `REGISTRY.create(...)` and publish events through
  `REGISTRY.publish(...)` — never stream directly from a request handler.

### TypeScript / React
- Next.js App Router, React 19, server components by default. Anything that
  touches the store, SSE, or `localStorage` must be `"use client"`.
- The Zustand store in `lib/run-store.ts` is the single source of truth for
  run state. **Components never open SSE themselves** — call
  `store.subscribe(runId)`. Unmounting a component must not cancel the run;
  only the store's own unsubscribe (called on `reset()` / `cancelRun()` /
  before a new `subscribe`) tears down the EventSource.
- New persisted fields must be added to the `partialize` allowlist; the
  `_unsubscribe` function reference must stay out of it.
- When performing async operations in the Zustand store that may race with
  user actions, use a transient boolean flag (underscore-prefixed, excluded
  from `partialize`) to guard against stale mutations. The `_hydrating`
  flag is an example: `hydrate()` sets it true; `startRun()` sets it false
  to signal it won the race.
- Tailwind classes follow the existing `cn(...)` + `clsx` convention
  (`lib/utils.ts`). Reuse primitives from `components/ui/*`.
- `lib/types.ts` mirrors `schemas.py`. When you change a Pydantic model that
  crosses the wire, update the matching TS interface in the same PR.

### Both
- Don't add new dependencies unless they're already used in the project or
  the user asked for them. Check `pyproject.toml` / `package.json` first.
- No emojis in code, comments, or commit messages.
- No README / docs updates unless the user explicitly asks.

## Things that are easy to get wrong

1. **Run registry is in-memory.** Restarting `uvicorn` discards in-flight
   runs. The frontend handles this via 404 → store reset. Don't add code
   that assumes restart-survival.
2. **`GET /api/runs/{id}` is overloaded.** UUIDs hit the registry; anything
   else is treated as a slug and looked up on disk. Use `_is_uuid()` if you
   need to discriminate.
3. **TestClient + asyncio tasks.** FastAPI `TestClient` runs each request in
   its own event loop, so a task started by `POST /api/analyze` will not
   survive a follow-up `DELETE` if it's still awaiting. For tests that need
   to exercise cancellation against a long-running task, seed the registry
   directly (see `test_delete_endpoint_routes_to_registry`).
4. **`_FAN_OUT_NODES` frozenset.** The `_FAN_OUT_NODES` frozenset in
   `streaming_graph.py` must be manually kept in sync with `graph.py`
   topology. Adding or removing fan-out nodes without updating this set
   silently breaks the event-ordering invariant.
5. **Atomic create-with-task.** `RunRegistry.create()` now accepts the
   asyncio task and run_id atomically — there is no longer a separate
   `attach_task()` step or race window between create and attach.
6. **`AnalyzeForm` redirect logic.** On mount, if the persisted store is in
   a `completed` state, the form treats that as "stale" and renders the
   empty form (no redirect). The `staleSlugRef` is cleared the moment a new
   run goes `pending`/`running`, so fresh completions still auto-redirect.
   If you change this logic, regression-test the "click logo → back to /"
   flow manually.
7. **LLM budget vs. required schema fields.** Reducing `FTA_MAX_LLM_CALLS`
   below what `TeamScorer` needs will surface as the "fields with no
   defaults" error. The graph can degrade other nodes via warnings, but
   `TeamScore` cannot be partial.

## Where to look first when…

| Symptom | File |
|---|---|
| SSE not streaming to the UI | `server.py::stream_run_events`, `lib/api.ts::subscribeRunEvents`, `lib/run-store.ts::subscribe` |
| Run completes but UI doesn't redirect | `components/analyze-form.tsx` (redirect effect + `staleSlugRef`) |
| Two tabs out of sync | `runs.py::RunRegistry.publish` (queue fanout), per-tab `subscribe()` |
| New event type not visible in UI | Add to `events.py` `EventType`, mirror in `lib/types.ts`, handle in `run-store.ts::_applyEvent` |
| Score / tier wrong | `scoring.py` (deterministic) + `nodes/team_scorer.py` (LLM rubric) |
| New on-disk report not in History | `server.py::_list_disk_runs` |
