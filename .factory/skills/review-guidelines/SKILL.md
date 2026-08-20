---
name: review-guidelines
description: Repository-specific review checks for vc_toolbox (LangGraph backend + Next.js frontend). Use when reviewing a diff, pull request, or staged changes in this repository, in addition to the generic correctness review.
---

# Review guidelines for vc_toolbox

Apply these checks on top of the generic correctness review. They encode invariants
that break silently in this codebase: the tests still pass, the types still check, and
the failure only shows up at runtime or in a later refactor.

Report only what the diff actually gets wrong. A false positive here costs more than a
miss, because these rules are narrow enough that a wrong call is obviously wrong.

## Cross-boundary contracts

`founding_team_analyzer/src/founding_team_analyzer/schemas.py` and `web/lib/types.ts`
are hand-maintained mirrors. So are `events.py::EventType` and `types.ts::EventType`.
Nothing enforces the mirror at build time.

- A changed Pydantic model that crosses the wire must have its matching TypeScript
  interface updated in the same change. Check field names, optionality
  (`Optional[X]` / default vs `?`), and literal unions.
- A new `EventType` member in `events.py` must be added to `EventType` in
  `web/lib/types.ts` and handled in `run-store.ts::_applyEvent`. An unhandled event
  type is silently dropped by the store.
- `RunStatus` in `types.ts` must cover every status `runs.py` can set.

## LangGraph pipeline rules

- Nodes must never raise. Failures append a string to `state["warnings"]` and degrade.
  A bare `raise` or an uncaught call inside a node body is a finding.
- Every LLM call goes through `llm.py` so the per-run call counter and
  `FTA_MAX_LLM_CALLS` budget apply. A direct `ChatOpenAI(...)` or client call
  elsewhere bypasses the circuit breaker.
- Config must be read at call time: `from . import config as config_module` then
  `config_module.SETTINGS`. `from .config import SETTINGS` captures at import time and
  breaks CLI overrides.
- `_FAN_OUT_NODES` in `streaming_graph.py` is a manually maintained mirror of the
  fan-out topology in `graph.py`. Adding or removing a fan-out node without updating
  the frozenset breaks event ordering with no test failure.
- New required fields on `TeamScore` are a hazard: it cannot degrade partially, so a
  required field the prompt cannot reliably produce turns budget exhaustion into a
  hard run failure.
- Network I/O uses `tenacity` plus an `httpx` timeout. The Tavily client wraps
  `requests`, so `search.py` catches `requests.exceptions.*` instead.
- Logging is `structlog`. A `print()` in library code is a finding.

## Run registry and SSE

- The registry is in-memory by design. Code that assumes a run survives a server
  restart is wrong.
- Long-lived work must register via `REGISTRY.create(...)` and publish through
  `REGISTRY.publish(...)`. A request handler that streams the pipeline directly ties
  the run's lifetime to the client connection.
- `GET /api/runs/{id}` is overloaded: UUIDs hit the registry, anything else is treated
  as a slug on disk. New code that discriminates must use `_is_uuid()`.
- FastAPI `TestClient` runs each request in its own event loop, so a task started by
  `POST /api/analyze` does not survive a follow-up request while it is still awaiting.
  A new cancellation test that drives this through two `TestClient` calls is flaky by
  construction; seed the registry directly instead.

## Frontend rules

- `lib/run-store.ts` owns the SSE subscription. A component that constructs an
  `EventSource` directly is a finding.
- Unmounting a component must not cancel a run. Only the store's own unsubscribe
  (from `reset()`, `cancelRun()`, or before a new `subscribe`) may tear down the
  EventSource.
- New persisted state must be added to the `partialize` allowlist. Transient fields
  (`_unsubscribe`, `_hydrating`) must stay out of it, or a stale function reference or
  in-flight flag gets written to `localStorage`.
- Async store work that can race a user action needs a transient guard flag, checked
  after the await before mutating, in the style of `_hydrating`.
- Anything touching the store, SSE, or `localStorage` needs `"use client"`.
- `analyze-form.tsx` treats a persisted `completed` state on mount as stale and renders
  the empty form. Changes to `staleSlugRef` or the redirect effect risk a redirect loop
  on logo click.

## Validation expectations

A change that touches these areas should say how it was validated:

- Backend: `cd founding_team_analyzer && .venv/bin/python -m pytest`
- Frontend types: `cd web && npx tsc --noEmit`
- Frontend build: `cd web && npm run build`

## Out of scope

Do not report formatting, naming, import order, added comments, or "consider
extracting". Do not restate a finding the generic reviewer already posted.
