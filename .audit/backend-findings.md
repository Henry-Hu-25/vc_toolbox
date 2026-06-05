# Backend Bug Audit

## Summary
- 0 critical, 7 high, 14 medium, 7 low

## Findings

### [HIGH] [F-BE-001] CLI flag `--max-founders` / `--model` are silently ignored
- File: `founding_team_analyzer/src/founding_team_analyzer/cli.py:63-71` (analyze command)
  and every node module that does `from ..config import SETTINGS`
  (`nodes/founder_finder.py:9`, `nodes/founder_researcher.py:10`,
  `nodes/report_writer.py:11`, `tools/search.py:11`, `tools/fetch.py:11`,
  `llm.py:14`).
- Description: `cli.analyze` mutates env vars (`FTA_MAX_FOUNDERS`,
  `FTA_MODEL_REASONING`, `FTA_OUTPUT_DIR`) and then runs
  `config_module.SETTINGS = config_module.Settings.load()`. Nodes/tools/llm
  bound the name `SETTINGS` at import time via
  `from ..config import SETTINGS`. Replacing `config_module.SETTINGS` does
  not rebind those imports, so every reader continues to see the original
  Settings instance.
- Why it matters: User-facing CLI flags are silently dropped. A user who
  runs `--max-founders 2` still gets the default fan-out of 5; `--model
  gpt-4o` still calls `gpt-5.5`; `--out ./reports` still writes to `./out`.
- Reproduction / reasoning: Running `python -m founding_team_analyzer
  analyze X --max-founders 2 --model gpt-4o` then inspecting
  `founding_team_analyzer.nodes.founder_finder.SETTINGS.max_founders`
  returns the original (env or default) value, not 2.
- Suggested fix direction: Switch every reader to attribute-on-module
  access (`from .. import config; config.SETTINGS.max_founders`) — the
  pattern already used in `cli.py` and `server.py`. Alternatively expose
  a `get_settings()` accessor.

### [HIGH] [F-BE-002] Global LLM call counter is shared across concurrent runs
- File: `founding_team_analyzer/src/founding_team_analyzer/llm.py:39-46,99-104`
  (and `server.py:64` `reset_llm_counter()`)
- Description: `_call_counter = {"value": 0}` is a process-level dict.
  `reset_llm_counter()` blindly zeroes it, and `call_structured` increments
  the same counter regardless of which run is making the call. The server
  invokes `reset_llm_counter()` on every `_execute_run` start.
- Why it matters: With two concurrent runs in the FastAPI worker:
  (a) Run B starting after Run A has already made N calls resets the
  counter, letting both runs together exceed `FTA_MAX_LLM_CALLS`;
  (b) Conversely, two runs sharing the same counter can hit the cap with
  each having only ~half of `max_llm_calls`, surfacing as `TeamScorer`'s
  "fields with no defaults" failure (the documented budget-exhaustion
  symptom). The single-run CLI is fine; the server is multi-run by design.
- Reproduction / reasoning: Fire two `/api/analyze` requests back-to-back;
  log `_call_counter["value"]` from inside `call_structured`. The second
  POST resets it to 0 mid-flight of the first.
- Suggested fix direction: Per-run counter — pass a `RunContext` (or
  ContextVar bound on the asyncio task) to `call_structured` and
  increment/check it instead of the module-global dict.

### [HIGH] [F-BE-003] Self-critique flag is communicated through a global env var
- File: `founding_team_analyzer/src/founding_team_analyzer/server.py:55-62`
  and `nodes/team_scorer.py:39-44`
- Description: `_execute_run` writes/clears `os.environ
  ["FTA_DISABLE_SELF_CRITIQUE"]` on every run start; `TeamScorer.run`
  reads the same env var. There is no isolation between concurrent runs.
- Why it matters: Two concurrent runs A (no_self_critique=True) and B
  (no_self_critique=False) race on this env var. If B's `_execute_run`
  pops the var before A reaches `TeamScorer`, A runs WITH self-critique
  contrary to the user's request (and bills an extra LLM call). The
  inverse causes B to silently skip the self-critique pass.
- Reproduction / reasoning: Trace `_execute_run` lines 56-60 across two
  overlapping POSTs.
- Suggested fix direction: Pass `no_self_critique` through the LangGraph
  state (e.g., a config dict in `AnalyzerState`) and have `TeamScorer`
  read from `state` rather than `os.environ`.

### [HIGH] [F-BE-004] `done` event payload reports only the last node's warnings
- File: `founding_team_analyzer/src/founding_team_analyzer/streaming_graph.py:69-94`
- Description: `final_state` is built by `final_state = {**(final_state or
  {}), **partial}`. `app.astream(stream_mode="updates")` yields per-node
  partial dicts (NOT cumulative state), and each node returns its own
  `warnings` list. The shallow merge overwrites the previous node's
  `warnings`/`cost`. The final `done` event's `payload["warnings"]` ends
  up containing only the warnings of whichever node ran last, typically
  `report_writer` (which always returns `warnings: []`).
- Why it matters: SSE clients that surface "warnings on completion" via
  the `done` payload silently drop every CompanyProfiler / FounderFinder /
  Researcher / Scorer warning. The on-disk JSON report is fine because
  it's built from the LangGraph state (which uses `operator.add` reducer);
  only the SSE summary is misleading.
- Reproduction / reasoning: Inject a warning in `company_profiler.run`
  and `report_writer.run` returns no warnings, then observe the `done`
  event: only an empty list is shown.
- Suggested fix direction: Accumulate `warnings` (and the cost ledger)
  by extension/merge instead of overwrite, or pull the final `warnings`
  list from `cumulative_cost`-style state already maintained alongside.

### [HIGH] [F-BE-005] Researcher fan-out yields one `node_started` but N `node_finished`
- File: `founding_team_analyzer/src/founding_team_analyzer/streaming_graph.py:53-78`
- Description: `seen_started` deduplicates `node_started` events, but
  `node_finished` is emitted on every astream update. Because
  `founder_researcher` runs once per founder via `Send` fan-out,
  LangGraph emits one updates frame per completed researcher.
  Result: a single `node_started:founder_researcher` followed by
  N `node_finished:founder_researcher` events.
- Why it matters: The web UI's stepper (per AGENTS.md and
  `lib/run-store.ts::_applyEvent`) treats `node_finished` as a state
  transition; it can flip the researcher step from "running" → "finished"
  → "running" → "finished" repeatedly, or report a duplicate finish.
  Cumulative warnings/cost emitted alongside also double-count if the UI
  isn't idempotent.
- Reproduction / reasoning: Run with 3 founders; count the number of
  `event: node_finished` lines for `founder_researcher`.
- Suggested fix direction: Emit a single aggregate `node_finished` for
  fan-out nodes (e.g., gate on a `seen_finished` set, mirroring
  `seen_started`, and surface per-founder progress through a separate
  event type if needed).

### [HIGH] [F-BE-006] Cost ledger over-counts Tavily searches in CompanyProfiler
- File: `founding_team_analyzer/src/founding_team_analyzer/nodes/company_profiler.py:81-84`
- Description: After deduping, the node sets
  `tavily_searches=sum(1 for _ in sources if _.get("url"))`. This counts
  unique deduped URLs returned, not Tavily API calls actually made. For
  free-text input the node fires four search queries that can return up
  to 13 results total (4+3+3+3) — the ledger reports up to 13 searches
  when only 4 occurred.
- Why it matters: Per-run cost reporting and the global budget on Tavily
  consumption become unreliable. AGENTS.md treats the cost ledger as a
  signal for tuning `FTA_MAX_TAVILY_PER_FOUNDER` etc.; this distorts that
  baseline.
- Reproduction / reasoning: Compare the ledger value to the actual number
  of `search_tool.search(...)` calls in `_gather_sources`.
- Suggested fix direction: Increment `tavily_searches` once per
  `search_tool.search()` invocation (as the founder_finder and
  researcher nodes already do), not per result.

### [HIGH] [F-BE-007] DELETE `/api/runs/{id}` blocks the request thread for the duration of the cancelled task
- File: `founding_team_analyzer/src/founding_team_analyzer/server.py:177-194`
  and `runs.py:194-209`
- Description: `app.delete_run` calls `await REGISTRY.cancel(run_id)`,
  which calls `task.cancel(); await task` inside the request handler.
  If the worker is mid-LLM call (no `await` checkpoint), the task
  cannot honor the cancellation until the call returns; the HTTP DELETE
  blocks for that long.
- Why it matters: A mid-flight cancellation can stall the DELETE response
  for tens of seconds while the underlying LLM call drains, causing the
  UI's "Cancel" button to spin and triggering proxy/client timeouts.
  Worse: `except (asyncio.CancelledError, Exception): pass` swallows
  CancelledError raised in the outer scope (e.g., the HTTP client
  disconnecting), suppressing legitimate cancellation propagation.
- Reproduction / reasoning: Stub `_execute_run` with a long synchronous
  `time.sleep` (or a real LLM call) and DELETE while it runs.
- Suggested fix direction: Make cancel fire-and-forget — `task.cancel()`
  and return immediately; only update `mark_cancelled` from the worker's
  CancelledError handler. Drop the `await task` in the handler. Also
  re-raise `asyncio.CancelledError` in the handler instead of swallowing.

### [MEDIUM] [F-BE-008] Default model name is invalid (`gpt-5.5`)
- File: `founding_team_analyzer/src/founding_team_analyzer/config.py:42-43`
- Description: `model_reasoning=os.getenv("FTA_MODEL_REASONING", "gpt-5.5")`
  and the same default for `model_extract`. `gpt-5.5` is not a real
  OpenAI model id.
- Why it matters: Out-of-the-box (no `.env` overrides) every LLM call
  fails with a 400 "model not found", surfacing as a generic
  "TeamScorer failed: ..." warning rather than a startup config error.
- Reproduction / reasoning: Deleting `FTA_MODEL_REASONING` from `.env`
  and running any node would call `ChatOpenAI(model="gpt-5.5", ...)`.
- Suggested fix direction: Default to a known-good model (e.g.
  `gpt-4o` or `gpt-4o-mini`), or fail loudly at startup if the model
  name doesn't pass a sanity check.

### [MEDIUM] [F-BE-009] `RunRegistry` has no eviction; long-running servers leak memory
- File: `founding_team_analyzer/src/founding_team_analyzer/runs.py:55-69,89-119`
- Description: `_runs: dict[str, RunRecord]` grows monotonically. Every
  RunRecord retains its full `events` list (often dozens per run) plus
  any subscriber queues that weren't cleanly removed.
- Why it matters: A long-lived `uvicorn` process accumulates terminated
  runs forever. Memory grows linearly with cumulative run count.
- Reproduction / reasoning: Keep firing `POST /api/analyze` against a
  single server process; observe `len(REGISTRY._runs)` monotonic growth.
- Suggested fix direction: Cap retained terminal runs (e.g., last 100,
  LRU on `updated_at`) or evict after a TTL. Also periodically
  `gc`-prune `rec.subscribers` entries whose queue is idle.

### [MEDIUM] [F-BE-010] Stage-A truncation drops the tail of long sources
- File: `founding_team_analyzer/src/founding_team_analyzer/nodes/founder_researcher.py:213-220`
- Description: Stage A passes `source_content[:6000]`. Long LinkedIn
  pages, press articles, and Crunchbase HTML routinely exceed 6000 chars;
  the prompt simply drops the tail without warning.
- Why it matters: Newer entries in a chronological CV (most recent jobs
  often appear at the top OR bottom depending on the source) and
  late-page details (founders, funding) silently disappear from
  extraction. This degrades `founder_market_fit` and pedigree scoring.
- Reproduction / reasoning: Print `len(content)` for any extracted
  Crunchbase page; the cap is silently exceeded.
- Suggested fix direction: At minimum, append a sentinel (`...
  [truncated]`) so the LLM knows to mark `confidence=low`. Better,
  iterate over chunks or run a deterministic filter that keeps the
  highest-signal sections.

### [MEDIUM] [F-BE-011] `_passes_disambiguation_gate` accepts diacritic-stripped names against accented haystacks
- File: `founding_team_analyzer/src/founding_team_analyzer/nodes/founder_researcher.py:43-79`
  and the Founder normalization at `nodes/founder_finder.py:88-94`.
- Description: `_filter_and_dedupe` runs `normalize_name` which strips
  diacritics, so `Founder.name` ends up as ASCII (`Sebastian Lopez`).
  `_passes_disambiguation_gate` lowercases and substring-matches against
  raw `result.title + result.content`, which often retains diacritics
  (`Sebastián López`). The match silently fails and a legitimate URL is
  rejected.
- Why it matters: Founders with non-ASCII names get systematically
  empty researcher output (the spec's A7: English-only is a known
  limitation, but ASCII-vs-Unicode mismatch breaks even English speakers
  with accented names).
- Reproduction / reasoning: Founder name "Sebastián López" coming from
  a team page; `normalize_name` returns "Sebastian Lopez"; haystack
  contains "sebastián lópez"; `"sebastian" in "sebastián lópez"` is
  False.
- Suggested fix direction: Normalize the haystack the same way
  (`unicodedata.NFKD` + ASCII fold) before substring matching.

### [MEDIUM] [F-BE-012] `cancel()` swallows generic Exception when awaiting cancelled task
- File: `founding_team_analyzer/src/founding_team_analyzer/runs.py:201-205`
- Description: `try: await task; except (asyncio.CancelledError,
  Exception): pass`. This catches ANY exception raised by the task,
  including programming errors propagated through `_execute_run` after
  cancellation (e.g., the worker's own bug surfacing during teardown).
  It also masks `CancelledError` propagated from the surrounding scope
  (request cancellation).
- Why it matters: Loss of error context (no log lines on swallowed
  exceptions), and suppression of cooperative cancellation in the
  request handler.
- Reproduction / reasoning: Inject a `raise RuntimeError("teardown")`
  inside the worker after `mark_cancelled`; the registry never logs it.
- Suggested fix direction: Catch `CancelledError` explicitly, log
  `Exception` with `log.exception(...)`, and re-raise `CancelledError`
  if the caller's scope has been cancelled.

### [MEDIUM] [F-BE-013] `tools/search.py` retries on every Exception class (auth, schema)
- File: `founding_team_analyzer/src/founding_team_analyzer/tools/search.py:55-70`
- Description: `retry_if_exception_type(Exception)` retries on Tavily
  auth failures (401/403), JSON deserialization errors, etc. — anything
  that's deterministically not a transient network error.
- Why it matters: A misconfigured `TAVILY_API_KEY` causes 3x slowdown
  before the per-search "tavily.search failed" warning is logged. Hides
  the root cause behind exponential backoff.
- Reproduction / reasoning: Set `TAVILY_API_KEY=invalid` and run any
  node; each `search()` will retry three times.
- Suggested fix direction: Restrict `retry_if_exception_type` to
  network-class exceptions (e.g., `httpx.HTTPError`, Tavily-specific
  rate limit) and let permanent failures raise immediately.

### [MEDIUM] [F-BE-014] OverlapAnalyzer leaves pair strengths at "none" when LLM fails
- File: `founding_team_analyzer/src/founding_team_analyzer/nodes/overlap_analyzer.py:166-186`
- Description: When the polish LLM call fails, the fallback creates
  `TeamOverlap(pairs=pairs, overall_strength=_max_strength(["medium" if
  has_any_overlap else "none"]))`. Each `pair.strength` keeps its
  default `"none"`. Then the post-processing block re-evaluates
  `overall_strength` from `[p.strength for p in polished.pairs]` which
  becomes `"none"` again, contradicting the deterministic
  `has_any_overlap=True` signal.
- Why it matters: TeamScorer reads `TeamOverlap` and may underrate
  `prior_shared_history` purely due to a transient LLM failure. The
  rendered table also shows pair strength "none" alongside an
  "overall_strength: medium", which is internally inconsistent.
- Reproduction / reasoning: Force the LLM call to raise; observe
  `polished.overall_strength` after the post-processing branch.
- Suggested fix direction: When falling back, set each pair's strength
  using a deterministic rule (any shared employer or prior startup ⇒
  "medium", just shared school ⇒ "weak") and then compute overall.

### [MEDIUM] [F-BE-015] `_gap_fill` mutates Pydantic model attributes, bypassing validators
- File: `founding_team_analyzer/src/founding_team_analyzer/nodes/company_profiler.py:144-153`
- Description: `setattr(company, field, new_value)` and
  `company.source_urls = sorted(...)` are direct field assignments.
  `Company` does not set `model_config = ConfigDict(validate_assignment
  =True)`, so the `_clean_lists` `field_validator` is not invoked on
  assignment. URLs from gap-fill bypass the validator's coercion/strip
  logic.
- Why it matters: Subtle drift in stored URLs; `source_urls` may end up
  containing non-strings or whitespace-only entries that the validator
  would have stripped at construction.
- Reproduction / reasoning: Construct a Company, then set
  `company.source_urls = ["", " ", None]`. The list is accepted as-is.
- Suggested fix direction: Either build a new Company via
  `company.model_copy(update={...})` (which re-runs validators) or set
  `validate_assignment=True` on the model.

### [MEDIUM] [F-BE-016] Worker's `attach_task` happens after `create_task`; cancel() before attach is a no-op
- File: `founding_team_analyzer/src/founding_team_analyzer/server.py:170-176`
- Description: `analyze` does
  `task = asyncio.create_task(_execute_run(...)); REGISTRY.attach_task(record.id, task)`.
  Between those two statements, an event-loop tick can occur (e.g., the
  task runs synchronous setup until its first `await`). If `DELETE
  /api/runs/{id}` arrives in that window, `cancel()` reads
  `rec.task is None`, calls `mark_cancelled` only, and the task keeps
  running independently — orphan run, never cancelled.
- Why it matters: Edge case but possible under load; produces a
  "cancelled" status while the LangGraph still consumes API budget and
  writes a report file.
- Reproduction / reasoning: TestClient or threaded test that posts and
  immediately deletes; the task may already be scheduled but unattached.
- Suggested fix direction: Make registry creation also create the task
  (e.g., `REGISTRY.create_with_task(input, lambda: _execute_run(...))`)
  so the record holds the task before any await yields control.

### [MEDIUM] [F-BE-017] `error` after `done` does not flip status from completed → failed
- File: `founding_team_analyzer/src/founding_team_analyzer/runs.py:91-114`
- Description: `publish` updates `rec.status` only when current status
  is NOT terminal. If `done` arrives first (status → completed) and a
  late `error` event is published (e.g., a stray exception in
  `report_writer` after writing files), the error message ends up in
  `rec.error` because that branch is unconditional, but `rec.status`
  remains "completed". The buffer contains both events but consumers
  see a "completed" status with a non-null error string.
- Why it matters: Inconsistent state visible to `_registry_summary` and
  `to_summary()`. A "completed" run with an error can confuse the UI.
- Reproduction / reasoning: Manually call
  `reg.publish(run_id, {"type":"done",...}); reg.publish(run_id,{"type":"error","payload":{"message":"x"}})`
  → `rec.status=="completed"` and `rec.error=="x"`.
- Suggested fix direction: Only set `rec.error` when transitioning into
  the failed state (i.e., guard the assignment by the same terminal
  check used for `rec.status`).

### [MEDIUM] [F-BE-018] CORS allow-list excludes any non-localhost UI host
- File: `founding_team_analyzer/src/founding_team_analyzer/server.py:139-148`
- Description: `allow_origins=["http://localhost:3000",
  "http://127.0.0.1:3000"]` is hard-coded and not driven by env.
- Why it matters: Anyone deploying the server behind a reverse proxy or
  on a different host has SSE connections fail silently in browsers.
  Frontend devs working on a different port (e.g., Next.js fallback to
  3001 when 3000 is taken) will see CORS errors.
- Reproduction / reasoning: Run `next dev -p 3001` and hit the API.
- Suggested fix direction: Read an env var like `FTA_CORS_ORIGINS`
  (comma-separated) or accept a wildcard for dev. Document in
  `AGENTS.md`/README.

### [MEDIUM] [F-BE-019] CompanyProfiler's gap-fill does not de-duplicate `extra_sources`
- File: `founding_team_analyzer/src/founding_team_analyzer/nodes/company_profiler.py:117-138`
- Description: Unlike `_gather_sources`, `_gap_fill` collects search
  results without deduping by URL. Multiple gap-fill queries often hit
  Crunchbase / LinkedIn for the same URL; the prompt sees the same
  source enumerated several times.
- Why it matters: Wastes prompt tokens, shows the LLM the same fact
  multiple times (which can bias confidence), and produces a noisier
  `company.source_urls` list.
- Reproduction / reasoning: Trace `extra_sources` after a multi-field
  gap-fill; identical URLs appear under different field queries.
- Suggested fix direction: Apply the same `seen: set[str]` dedupe loop
  used in `_gather_sources`.

### [MEDIUM] [F-BE-020] `tools/fetch.py` is unused dead code
- File: `founding_team_analyzer/src/founding_team_analyzer/tools/fetch.py`
  (entire file)
- Description: No node imports `tools.fetch`. The spec earmarks it for
  HTTP-fallback when Tavily is missing, but nothing wires it in.
- Why it matters: Dead code attracts maintenance burden and confuses
  future contributors. It also depends on `trafilatura`, which is in
  `pyproject.toml` solely to support this unused module.
- Reproduction / reasoning: `rg "tools.fetch|fetch\\.fetch"` returns
  only egg-info / tests-not-using.
- Suggested fix direction: Either remove the module (and its
  `trafilatura` dependency) or wire it in as an actual fallback in
  `tools/search.py::extract`.

### [MEDIUM] [F-BE-021] `RunRecord.subscribers` retains queues across event loops in tests / multi-loop scenarios
- File: `founding_team_analyzer/src/founding_team_analyzer/runs.py:142-184`
- Description: `asyncio.Queue` instances are bound to the loop in which
  they're created. The TestClient pattern (each request gets its own
  event loop) exposes this: a publisher running in loop A can call
  `q.put_nowait` on a queue created in loop B; in CPython this is
  accepted but the consumer awaiting `queue.get()` in loop B does not
  wake up until that loop runs.
- Why it matters: SSE replay tests are timing-sensitive and rely on the
  publisher and subscriber sharing a loop. In production the single
  uvicorn loop avoids this, but the registry's invariant (queue + loop
  affinity) is undocumented and brittle.
- Reproduction / reasoning: `test_events_stream_replays_buffered_events`
  works because both publish and subscribe happen in the same TestClient
  request; concurrent fan-out across requests is not exercised.
- Suggested fix direction: Document the single-loop assumption, or
  implement the registry on `anyio.Event` / `asyncio.Condition` such
  that events fan out without per-subscriber Queue creation.

### [LOW] [F-BE-022] `_is_uuid` accepts UUIDs of any version, mis-routing UUID-shaped slugs
- File: `founding_team_analyzer/src/founding_team_analyzer/server.py:46-50`
- Description: `_is_uuid` returns True for any well-formed UUID string,
  including v1/v3/v5. If a user names a company whose slug happens to be
  a valid UUID, the GET handler sends them to `REGISTRY.get(...)` and
  returns 404 instead of falling through to the on-disk lookup.
- Why it matters: Extremely unlikely in practice but technically a
  silent mis-route.
- Reproduction / reasoning: Manually create a directory under `out/`
  named `00000000-0000-1000-8000-000000000000`; GET on that slug
  returns 404.
- Suggested fix direction: Restrict the check to UUIDv4 (`uuid.UUID
  (value).version == 4`) since `RunRegistry.create` uses `uuid.uuid4()`.

### [LOW] [F-BE-023] `_list_disk_runs` crashes if a run dir is removed mid-scan
- File: `founding_team_analyzer/src/founding_team_analyzer/server.py:103-125`
- Description: `sorted(root.iterdir(), key=lambda p: p.stat().st_mtime,
  ...)`. Between `iterdir()` and `stat()`, a directory deletion raises
  `FileNotFoundError` from the key function, propagating out of the
  endpoint.
- Why it matters: External cleanup processes (or another run racing on
  filesystem ops) can break the listing endpoint.
- Reproduction / reasoning: Race deletion of a child dir against the
  endpoint.
- Suggested fix direction: Wrap `child.stat()` in a try/except, or pre-
  collect dirs with a generator and skip missing ones.

### [LOW] [F-BE-024] `_list_disk_runs` returns the raw directory name as `slug`, not the canonical slug
- File: `founding_team_analyzer/src/founding_team_analyzer/server.py:124`
- Description: `child.name` is used directly. If a directory was created
  outside the pipeline (e.g., manually copied) with a non-`slugify`
  name, the listing exposes it but `GET /api/runs/{slug}` runs
  `slugify` on the user input and may miss.
- Why it matters: Minor; manual operators may see "ghost" entries that
  can't be opened.
- Reproduction / reasoning: `mkdir out/My_Manual_Folder` and call the
  list endpoint vs. detail endpoint.
- Suggested fix direction: Skip non-slug-shaped directories or
  re-slugify the name on the way out.

### [LOW] [F-BE-025] `register.publish` increments `updated_at` even when the run is unknown? (ordering nit)
- File: `founding_team_analyzer/src/founding_team_analyzer/runs.py:91-119`
- Description: When `etype not in {run_started, done, error}`, `rec
  .updated_at` is still updated; for `error` the `rec.error` is set
  unconditionally even when the status assignment is skipped (see
  F-BE-017). The combination produces a "completed" record with an
  error string and a refreshed `updated_at`, which sorts ahead of
  earlier successful runs in the listing.
- Why it matters: Confusing ordering for `_list_disk_runs` /
  `_registry_summary` when late events arrive.
- Reproduction / reasoning: See F-BE-017 plus subsequent listing.
- Suggested fix direction: Only set `rec.error` inside the same status-
  transition branch.

### [LOW] [F-BE-026] `effort=None` resolution falls to reasoning_effort when extract == reasoning model
- File: `founding_team_analyzer/src/founding_team_analyzer/llm.py:111-117`
- Description: `if chosen_model == SETTINGS.model_extract and chosen_model
  != SETTINGS.model_reasoning: effort = SETTINGS.extract_effort`. The
  `!=` clause means: when both env vars point to the same model (the
  current default `gpt-5.5` / `gpt-5.5`), every call uses
  `reasoning_effort` even for cheap extraction.
- Why it matters: Operators tuning `FTA_EXTRACT_EFFORT=low` are silently
  ignored unless they also differentiate `FTA_MODEL_EXTRACT` from
  `FTA_MODEL_REASONING`. Doubles the cost of stage A / founder_finder.
- Reproduction / reasoning: Print `effort` from `_make_chat` for an
  extraction-only call when both model env vars match.
- Suggested fix direction: Use the caller-supplied tag (e.g., a new
  `purpose: Literal["reasoning","extract"]` arg) rather than inferring
  from model identity.

### [LOW] [F-BE-027] `_VALID_EFFORTS` includes `xhigh` and `none` which are not standard OpenAI values
- File: `founding_team_analyzer/src/founding_team_analyzer/config.py:21-26`
- Description: OpenAI's `reasoning_effort` accepts a discrete set
  (`minimal`, `low`, `medium`, `high` for the gpt-5 family). `xhigh`
  and `none` will be silently rejected by the API or ignored by
  langchain-openai.
- Why it matters: Operators reading the config may set
  `FTA_REASONING_EFFORT=xhigh` expecting deeper reasoning and get
  silent failures.
- Reproduction / reasoning: Set `FTA_REASONING_EFFORT=xhigh`; observe
  ChatOpenAI 400 from the OpenAI SDK.
- Suggested fix direction: Match OpenAI's allowed list and add a
  startup validation log.

### [LOW] [F-BE-028] `Founder.name` is rewritten to title-case via `normalize_name`, losing original casing
- File: `founding_team_analyzer/src/founding_team_analyzer/nodes/founder_finder.py:88-94`
- Description: `name=normalized` always overrides, even when the LLM
  returned `"deepak K. Singh"` and `normalize_name` produces
  `"Deepak K. Singh"`. Generally fine, but for names with intentional
  lowercase / Unicode (`"bell hooks"`, `"Mariam Ait Chibane"`) the
  rewrite is wrong.
- Why it matters: Cosmetic, but the title-cased name is what's used as
  the disambiguation token (which is then case-insensitive, so no
  filtering effect) AND what appears in the report card.
- Suggested fix direction: Title-case only when the input looks
  ALL-LOWER or ALL-UPPER; preserve mixed case otherwise.

## Test gaps

- **No node-level integration test for the full graph.** Only `tests/`
  exercise individual helpers, schemas, and the registry. There is no
  test that wires `build_graph()` end-to-end against stubbed LLM/Tavily
  layers; regressions in `_dispatch_researchers`, the operator.add
  reducer, or warning aggregation would not be caught. Suggested name:
  `test_graph_smoke_with_fakes`.
- **No test for streaming_graph event ordering.** `streaming_graph
  .stream_analysis` has non-trivial logic (per-node `seen_started`,
  cumulative cost, final state assembly, exception capture) but no
  test asserts the sequence and shape of emitted Events. Suggested
  names: `test_stream_analysis_emits_run_started_and_done`,
  `test_stream_analysis_aggregates_warnings_across_nodes`,
  `test_stream_analysis_yields_error_event_on_node_failure`.
- **No test that the LLM budget cap surfaces as a TeamScorer-required-
  fields failure.** The "fields with no defaults" failure mode is
  documented in AGENTS.md but uncovered. Suggested name:
  `test_call_structured_raises_budget_exceeded_for_required_schema`.
- **No test for concurrent runs sharing global counter / env var
  state.** F-BE-002 and F-BE-003 are reproducible only with concurrent
  runs. Suggested names:
  `test_concurrent_runs_do_not_share_call_counter`,
  `test_concurrent_runs_isolate_self_critique_flag`.
- **No test for cancellation of a long-running task** (i.e. behaviour
  of DELETE while task is awaiting an LLM call). Current
  `test_cancel_marks_cancelled_and_cancels_task` uses a trivial
  `asyncio.sleep(10)` worker; doesn't exercise F-BE-007.
- **No test for `_execute_run` failure path** (Exception raised by
  `stream_analysis`). The error event publish + `mark_failed` chain is
  uncovered. Suggested name:
  `test_execute_run_failure_marks_run_failed_and_publishes_error`.
- **No test for company profiler `_gap_fill` mutating Pydantic model**.
  F-BE-015 is silent without a regression test. Suggested name:
  `test_gap_fill_strips_dirty_source_urls`.
- **No test for placeholder-name scrubbing in the founder researcher**
  end-to-end (the schema test covers `FounderProfile` validators but
  not the call chain). Suggested name:
  `test_founder_researcher_drops_placeholder_education_in_stage_b`.
- **No test for `_passes_disambiguation_gate` against accented names**
  (F-BE-011 unhit). Suggested name:
  `test_disambiguation_handles_diacritic_haystack`.
- **No test for `OverlapAnalyzer` LLM-fallback path** (F-BE-014).
  Suggested name:
  `test_overlap_falls_back_to_deterministic_strengths_on_llm_failure`.
- **No test for the `done` event payload's warnings aggregation**
  (F-BE-004). Suggested name:
  `test_done_event_includes_warnings_from_every_node`.
- **No test for fan-out node_finished deduplication** (F-BE-005).
  Suggested name:
  `test_streaming_graph_emits_one_node_finished_per_node`.
- **No coverage for `tools/search.py` retry/cache behaviour** (auth
  retry storm in F-BE-013, cache hit semantics).
- **No coverage for the `cli` module** beyond what `import` exercises.
  CLI flag plumbing (F-BE-001) is unverified.

## Notes / open questions

- The `Founder.linkedin_url` carve-out in
  `_passes_disambiguation_gate` only fires for slug-equal LinkedIn URLs.
  Is it intentional that an authoritative LinkedIn URL doesn't also
  exempt the page from the company-mention requirement (F-BE-011 fix
  hint)? Re-checking after diacritic normalization may render this
  branch unnecessary.
- The spec (Section 1.A6) earmarks ~30-60 LLM calls per run; the
  default `FTA_MAX_LLM_CALLS=30` is at the low end and routinely
  surfaces as TeamScorer's "required fields" failure (per AGENTS.md).
  Worth confirming whether the orchestrator wants the audit to flag
  the default itself as a config bug or only the failure mode.
- `cli.py` rebinds `config_module.SETTINGS` and assumes downstream
  modules read through the module object — but only `cli.py` and
  `server.py` follow that pattern; nodes import the symbol directly.
  Open question for the orchestrator: is the import-time binding
  intentional (for performance) and CLI flags expected to be ignored,
  or is this a regression we should plan to fix?
- `_self_critique_enabled(state)` accepts `state` but ignores it. Is
  this leftover refactor work, or is the eventual plan to read from
  state? (Same fix would resolve F-BE-003.)
- `tools/fetch.py` may be the planned home for an HTTP-only fallback
  path. Confirm with the orchestrator whether we should treat it as
  dead code (delete) or unfinished work (build out).
