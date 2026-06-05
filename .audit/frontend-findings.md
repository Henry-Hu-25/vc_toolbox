# Frontend Bug Audit

## Summary
- 0 critical, 5 high, 9 medium, 8 low

## Findings

### [HIGH] [F-FE-001] `hydrate()` races with `startRun()`, can hijack a fresh subscription
- File: web/lib/run-store.ts:139-167 (also 96-111, 113-125)
- Description: `hydrate()` reads `runId` at line 140, then awaits `getRunStatus(runId)` (line 143). If the user clicks Analyze while that GET is in flight, `startRun()` mutates the store (`set({...INITIAL, status: "pending", input, ...})` then `set({ runId: <new>, status: ... })`), and `subscribe(<new>)` opens an SSE for the new run. When `getRunStatus` finally resolves, hydrate calls `set({ status, input, slug })` for the OLD run and then `get().subscribe(<old runId>)` (line 161). `subscribe` unconditionally tears down the previous unsubscribe (the new run's SSE) and opens an SSE for the OLD runId. Net effect: the new run's stream is silently killed and the store is bound to the old run.
- Why it matters: Users can start a fresh analysis on page load (when hydrate happens to be slow) and end up with the previous run streaming into the UI; the new run continues in the backend with no UI feedback. The only recovery is a hard reload or `reset()`.
- Reproduction / reasoning: Throttle `/api/runs/{id}` to 2s, persist a stale runId in localStorage, refresh the page, then click an example chip immediately after first paint. `_applyEvent` will receive events for two runIds and the second `subscribe` call from hydrate will close the new SSE.
- Suggested fix direction: Capture the runId hydrate started with, and after the await re-check `get().runId` is unchanged before mutating state or subscribing. Alternatively flag hydrate as "in-flight" and short-circuit `startRun` until it completes (or vice-versa).

### [HIGH] [F-FE-002] `startRun` failure leaves the store stuck in `pending`
- File: web/components/analyze-form.tsx:43-51 ; web/lib/run-store.ts:96-111
- Description: `analyze-form.tsx` only `console.error`s and clears `submitting`. `startRun` itself sets `status: "pending"` BEFORE awaiting `startAnalyze`. If the POST throws (network error, 503 from missing API keys, 422, etc.), the throw bubbles to the form's catch but the store is left with `status: "pending"`, `input: <user input>`, and a stale `_unsubscribe = null`. `showRunPanel` is `running || ...` which is `true`, so the run panel is rendered indefinitely with a spinning stepper and no error UI.
- Why it matters: A failed POST silently produces a bricked UI — no toast, no error message, no path back to the form except clicking "Cancel" (which calls `apiCancelRun(undefined runId?)` — see F-FE-003) or manually clearing storage. This is the most user-visible failure mode for misconfigured backends.
- Reproduction / reasoning: Stop the backend → click Analyze. Status stays `pending`, error stays `null`, the "Cancel" button appears and the user is stuck.
- Suggested fix direction: In `startRun`, wrap `startAnalyze` in try/catch and on failure `set({ status: "failed", error: (err as Error).message })`; rethrow so the form's catch can also show inline feedback. Alternatively, expose a `failedReason` and reset to idle.

### [HIGH] [F-FE-003] `cancelRun()` doesn't tear down SSE before awaiting DELETE → "failed" status flicker + stale error
- File: web/lib/run-store.ts:127-137
- Description: `cancelRun()` calls `await apiCancelRun(runId)` BEFORE invoking the previous unsubscribe. Backend `RunRegistry.cancel()` cancels the task, then calls `mark_cancelled()`, which publishes an `error` event with payload `{message: "Run cancelled by user."}` (runs.py:121-129). That event reaches the still-open SSE stream and is forwarded to `_applyEvent`, which sets `status: "failed"` and `error: "Run cancelled by user."` (run-store.ts:194-196). After the DELETE resolves, `cancelRun` overwrites with `status: "cancelled"` but does not clear `error`. The store now reads `status === "cancelled"` AND `error === "Run cancelled by user."`, so the run panel still shows the red "Run failed" box (analyze-form.tsx:178-189) and offers "Try again" alongside "New run".
- Why it matters: Cancellation is presented to the user as a failure. Repeated cancellations also leak status churn (`pending → running → failed → cancelled`) into any component subscribed to status.
- Reproduction / reasoning: Start a run, click Cancel before completion. Observe the rose error block while status is "cancelled".
- Suggested fix direction: Tear down the subscription BEFORE awaiting DELETE, or filter `error` events when `status === "cancelled"` in `_applyEvent`. Also clear `error` in cancelRun's final `set`.

### [HIGH] [F-FE-004] SSE parser only splits on `\n\n`, breaks behind any CRLF-normalizing proxy
- File: web/lib/api.ts:103-118
- Description: `subscribeRunEvents` accumulates the decoded body and uses `buffer.indexOf("\n\n")` as the message delimiter. Many HTTP intermediaries (Cloudflare, AWS ALB, certain Nginx configs) and HTTP/1.x clients normalise SSE line endings to CRLF (`\r\n\r\n`). When that happens, `\n\n` is never found and `buffer` grows unboundedly while no events are dispatched. The `parseSseChunk` `.trim()` per `data:` line masks the `\r` only inside lines, not at the boundary.
- Why it matters: A deployment behind a default-configured reverse proxy will appear to hang on the analyse screen indefinitely with no events surfacing, even though the backend is publishing correctly. Memory growth in long sessions.
- Reproduction / reasoning: Run the app behind any HTTP proxy that normalises to CRLF, or simulate by injecting `\r` into the response in a fetch interceptor.
- Suggested fix direction: Replace `indexOf("\n\n")` with a regex `/\r?\n\r?\n/` and slice using its match index/length. Also handle leading `\uFEFF` BOM per spec.

### [HIGH] [F-FE-005] Zustand `persist` hydration mismatch on SSR (no `skipHydration`, no gating)
- File: web/lib/run-store.ts:84-235 ; web/app/layout.tsx:14-22 ; web/components/in-progress-pill.tsx:7-23
- Description: The persist middleware uses `createJSONStorage(() => localStorage)` with no `skipHydration: true` and no gating on `useRunStore.persist.hasHydrated()`. On the server, localStorage is unavailable so the store renders with `INITIAL` state. On the client, persist applies the persisted state synchronously during the first store read, BEFORE React hydration. Components that depend on store state (e.g., `InProgressPill` which returns `null` for `idle` but a `<Link>` for `running`/`pending`, and `AnalyzeForm` whose `showRunPanel` depends on persisted status) will mount with a different DOM tree than the server-rendered HTML.
- Why it matters: Hydration mismatch warnings in dev, possible mis-mounting in prod, and a one-frame visual flicker on reload when a run is in-flight or recently completed. Also makes `staleSlugRef` semantics unstable (see F-FE-016).
- Reproduction / reasoning: Persist a `running` runId, hard-refresh the page, observe the React hydration warning in console (or visually a flicker between empty header and the in-progress pill).
- Suggested fix direction: Add `skipHydration: true` and call `useRunStore.persist.rehydrate()` from `RunHydrator` after mount, OR gate state-dependent UI on a `mounted` flag.

### [MEDIUM] [F-FE-006] `parseSseChunk` concatenates multi-line `data:` payloads without newlines
- File: web/lib/api.ts:121-135
- Description: SSE spec says when an event has multiple `data:` fields they MUST be joined with `\n` and a trailing newline is removed. Current loop is `data += line.slice(5).trim()` — fields are concatenated with no separator and per-field trimmed. The current backend (`server.py::_format_sse`) emits a single-line JSON so today the parser works, but any future change (e.g., pretty-printed JSON for debugging, or any LLM-emitted text containing newlines) will silently produce malformed JSON and dropped events.
- Why it matters: Latent breakage, easy to introduce by switching to `json.dumps(..., indent=2)` server-side.
- Reproduction / reasoning: Set the server to emit `data: {\n  "type": ... }` over multiple lines; the client's `parseSseChunk` will collapse to `{"type": ...}` etc. but lose intra-string newlines.
- Suggested fix direction: Build `data` as an array, push `line.slice(line.startsWith("data: ") ? 6 : 5)` per line (without trim), then `data.join("\n").replace(/\n$/, "")` per spec. Treat `:` lines as comments and skip explicitly.

### [MEDIUM] [F-FE-007] No SSE reconnection / retry; a single network blip permanently severs the stream
- File: web/lib/api.ts:86-119
- Description: `subscribeRunEvents` issues one `fetch` and reads to EOF. Any transient disconnect (proxy idle timeout, brief network drop, server worker restart) ends the stream. The reader either errors (calls `opts?.onError`) or hits `done=true` cleanly. Either way the EventSource-style `retry:` field and automatic reconnection are not implemented. Because the registry is replay-capable (runs.py:131-159), reconnect is safe and idempotent.
- Why it matters: Long-running analyses (60-90s with a flaky proxy) lose live progress and eventually appear stuck. The user sees the last event and never receives `done` even though the backend completed.
- Reproduction / reasoning: Kill and restart a forwarding proxy mid-run; observe stream never recovers.
- Suggested fix direction: On transient errors / clean EOF before terminal status, reconnect to `/api/runs/{id}/events` with exponential backoff. The replay buffer will redeliver events.

### [MEDIUM] [F-FE-008] Example-chip buttons aren't disabled while a run is in progress
- File: web/components/analyze-form.tsx:121-138
- Description: The chip buttons gate their visual disabled style on `submitting && "opacity-50 pointer-events-none"`. They do NOT consider `running`. Once a run is in flight, `submitting` is `false` (it's only true during the synchronous startRun). `handleSubmit` correctly short-circuits via `if (!target || running || submitting) return`, but the chips look fully interactive — clicking does nothing.
- Why it matters: Confusing UX. Users repeatedly click and assume the app is broken.
- Reproduction / reasoning: Click "Analyze", then click an example chip while progress is showing. No-op without feedback. Note: the run panel is rendered at this point, replacing the form, so the chips are not visible — BUT they ARE visible if the persist hydration races and shows the form before status loads. Still defensive coding for the AnimatePresence transition.
- Suggested fix direction: `(submitting || running) && "opacity-50 pointer-events-none"`. Apply the same to the Analyze submit button.

### [MEDIUM] [F-FE-009] Progress stepper conveys state primarily by color/icon; screen reader announcement is impoverished
- File: web/components/progress-stepper.tsx:18-57
- Description: The `<ol>` is `aria-live="polite"` so changes are announced, but each step's state is communicated via the icon (`Check`, `Loader2`, `AlertTriangle`, `Circle`) and color. The label text is constant ("Resolving company" etc.) — only "Working..." is appended for the running state. A screen reader hearing "Resolving company" cannot tell whether it's pending, running, done, or warning. Color-only signaling for pending vs done.
- Why it matters: WCAG 1.4.1 (Use of Color) and 1.3.1 (Info and Relationships). Users with screen readers or color-blindness cannot follow run progress.
- Reproduction / reasoning: Run with VoiceOver/NVDA active. Compare announcements across states.
- Suggested fix direction: Add visually-hidden state text (e.g., `<span className="sr-only">{state}</span>`) inside each `<li>`, and `aria-current="step"` on the running one. Add hatched/diagonal pattern fallback for pending vs done if you also want non-color visual differentiation.

### [MEDIUM] [F-FE-010] `cost-ledger.tsx` icon/label mismatch ("HTTP" labeled with `Coins` icon)
- File: web/components/cost-ledger.tsx:31-35
- Description: The fourth stat shows `c.http_fetches` with the `Coins` icon. The "Coins" icon implies cost/dollars, not HTTP traffic. None of the other three icons (`Cpu`, `Search`, `FileText`) communicate cost either, so users may infer `http_fetches` is the dollar count.
- Why it matters: Misleading at a glance; muddles trust in the cost panel.
- Reproduction / reasoning: Review the rendered ledger.
- Suggested fix direction: Use `Globe` or `Network` for HTTP; reserve `Coins` for an actual cost row if added later.

### [MEDIUM] [F-FE-011] `useParams` slug not guarded for undefined / array shapes
- File: web/app/runs/[slug]/page.tsx:24-31
- Description: `const { slug } = useParams<{ slug: string }>();` casts away the fact that Next.js `useParams` returns `string | string[] | undefined` per param. The effect calls `getRun(slug)` with whatever value is there. If the route ever changes to support catch-all `[...slug]` or arrives with no slug (e.g., during a transition), `getRun(undefined as any)` will be called and `encodeURIComponent(undefined)` produces the literal string "undefined" — backend returns 404 with a confusing error.
- Why it matters: Defensive guard missing; future-proofing.
- Reproduction / reasoning: Force `slug = undefined` via dev tools. Observe `/api/runs/undefined` request.
- Suggested fix direction: Early return or skeleton when `typeof slug !== "string"`.

### [MEDIUM] [F-FE-012] `RunSummary` keys collide for in-flight runs sharing input
- File: web/app/runs/page.tsx:99-101 (`const key = it.slug || it.run_id || it.company_name`)
- Description: For disk runs, `slug` is set. For in-flight runs from the registry, `slug` is null and `run_id` is the UUID. So `it.slug || it.run_id` produces a unique key. **However**: the registry summary uses `company_name: rec.input` (server.py:139), so two simultaneous runs of "Vellum AI" would produce two rows. Their keys are distinct (different run_ids), good. The fallback `it.company_name` is reachable only if both `slug` and `run_id` are null (shouldn't happen). Mostly defensive but the fallback to `company_name` is a footgun if backend ever omits both.
- Why it matters: React reconciliation correctness if backend shape drifts.
- Reproduction / reasoning: Code reading.
- Suggested fix direction: Always require `run_id || slug` and assert in dev; drop the company_name fallback.

### [MEDIUM] [F-FE-013] Polling on `/runs` page and the "force-refresh on terminal transition" effect race
- File: web/app/runs/page.tsx:34-47
- Description: Two effects manage refresh:
  1. interval refresh every 3s while local store status ∈ {running, pending} (line 34-39).
  2. On transition from running→terminal, force a refresh (line 41-47).
  When the local run completes mid-poll, both fire: the interval clears on rerender (after status changes), and the second effect dispatches an extra `refresh()`. If the first poll's response arrives AFTER the forced refresh, `setItems` overwrites with the older snapshot — list may briefly show the in-flight row even though the new disk row is now present.
- Why it matters: Cosmetic flicker / momentary stale list.
- Reproduction / reasoning: Read both effects; the response ordering is not guaranteed.
- Suggested fix direction: Track an `inFlightId` per request and ignore responses whose id is older than the latest dispatched fetch.

### [MEDIUM] [F-FE-014] `cancelRun()` is callable when there's no runId mid-error, but error UI shows "Try again" and "New run" without clearly different affordances
- File: web/components/analyze-form.tsx:147-156, 178-189
- Description: When status === "failed" the panel shows a "Try again" button (calls `reset`) and the top-right shows "New run" (also calls `reset`). Two buttons, same handler, different labels. Confusing, and not differentiated for keyboard users (no separator/grouping).
- Why it matters: Minor UX redundancy.
- Reproduction / reasoning: Force a failure (kill backend mid-run); observe both buttons.
- Suggested fix direction: Show only one terminal action; or differentiate (`Retry` resubmits the same input, `New run` clears).

### [LOW] [F-FE-015] `staleSlugRef` initializer captures only the first render's snapshot
- File: web/components/analyze-form.tsx:34-38
- Description: `React.useRef(status === "completed" ? slug : null)` runs once. If the persist middleware hydrates state between mount and the first commit (see F-FE-005), the ref stores `null` even for a persisted-completed run. On the next render, `isStaleCompletion = status === "completed" && slug !== null && slug === staleSlugRef.current` is false, so the redirect effect fires and pushes to `/runs/<slug>` — defeating the entire "stale completion stays on home" rule.
- Why it matters: Logo-click → home flow can re-redirect to the report under hydration timing pressure.
- Reproduction / reasoning: With persist hydration deferred (e.g., `skipHydration: true`), this regresses immediately.
- Suggested fix direction: Compute `isStale` from a `mounted` snapshot inside an effect rather than initializer; or store the "this completion is stale" decision in the store itself.

### [LOW] [F-FE-016] `markdown-report.tsx` defaults missing href to `"#"`, opens new tab targeting nothing
- File: web/components/markdown-report.tsx:7-15
- Description: `<a href={href ?? "#"} target="_blank" rel="...">` — for malformed markdown links, the rendered anchor opens a blank tab pointing at `#`.
- Why it matters: Trivial UX wart.
- Reproduction / reasoning: Render a markdown report with `[click](missing url)` — react-markdown passes `href: undefined`; the anchor opens about:blank#.
- Suggested fix direction: If `href` is falsy, render a `<span>` instead.

### [LOW] [F-FE-017] `ThemeToggle` icon shows initial state (sun vs moon) before `mounted`, can flash
- File: web/components/theme-toggle.tsx:8-25
- Description: Click is gated on `mounted`, but the rendered icon is computed from `current = resolvedTheme || theme || "light"`. Before mount, `resolvedTheme` is undefined and `theme` is undefined, so it falls back to `"light"` (renders Moon = "switch to dark"). On hydration, the actual theme may flip and the icon swaps.
- Why it matters: Brief visual flicker on first paint.
- Reproduction / reasoning: System dark mode + reload. Observe icon flip.
- Suggested fix direction: Render a placeholder (`<Skeleton/>` or invisible icon) until `mounted`.

### [LOW] [F-FE-018] In-progress pill uses `title={"Analyzing " + input}` only; no aria-live for status changes
- File: web/components/in-progress-pill.tsx:18-22
- Description: Pill appears/disappears based on status but is not announced to screen readers. The text inside is fine, but the appearance/disappearance is not announced.
- Why it matters: Screen-reader users navigating to `/runs` history page won't know a run is still in progress.
- Reproduction / reasoning: VoiceOver / NVDA test.
- Suggested fix direction: Wrap pill region in `aria-live="polite"` at a stable parent (e.g., site header), or render an sr-only status announcement.

### [LOW] [F-FE-019] `RunHydrator` ranRef pattern is fine, but `hydrate()` doesn't `await` and there's no error surface
- File: web/components/run-hydrator.tsx:8-15 ; web/lib/run-store.ts:139-167
- Description: `void hydrate()` swallows any unexpected error not caught inside (currently caught). If hydrate throws (e.g., new endpoint shape), nothing surfaces and the user sees stale persisted state with no indication.
- Why it matters: Latent failure mode for evolving backend.
- Reproduction / reasoning: Force `getRunStatus` to throw a non-404 error; observe silent persistence of stale state.
- Suggested fix direction: Have hydrate set `error` on unexpected failures.

### [LOW] [F-FE-020] `OverlapTable` narrative list uses array index `i` as React key on a filtered subset
- File: web/components/overlap-table.tsx:54-62
- Description: `overlap.pairs.filter((p) => p.narrative).map((p, i) => <li key={i}>...)`. If the source `pairs` mutates between renders (it doesn't currently, but the report page swaps when navigating via `setData`), keys may collide with stale state during transitions.
- Why it matters: React reconciliation correctness when more dynamic data flows are added later.
- Reproduction / reasoning: Static today; future hot-swap of overlaps would re-mount.
- Suggested fix direction: Use a stable composite key like `${p.founder_a}-${p.founder_b}`.

### [LOW] [F-FE-021] `reset()` does not clear runId in localStorage immediately if storage write is async
- File: web/lib/run-store.ts:91-95 ; partialize block at 217-230
- Description: `reset` calls `set({ ...INITIAL, ... })` which spreads `runId: null`. With sync localStorage and zustand persist this is fine. But the partialize allowlist persists `runId` which means a tab opened after reset but before localStorage write completes could see stale runId. Likely a non-issue with sync storage.
- Why it matters: Multi-tab sync edge case.
- Reproduction / reasoning: Tab A reset, Tab B reload with cached storage event lag.
- Suggested fix direction: None unless multi-tab sync becomes a goal; consider `BroadcastChannel` for cross-tab.

### [LOW] [F-FE-022] `getRunStatus` response interface declares `report?` and `markdown?` on the run-id branch only; `slug` is also reused
- File: web/lib/api.ts:53-65 ; backend server.py:225-243
- Description: Backend returns `body = rec.to_summary()` with `report_slug`, then conditionally adds `report`, `markdown`, `slug`. Frontend `RunStatusResponse` does include all fields as optional, but `hydrate` only consumes `status`, `input`, `report_slug`/`slug`, `error`. The full report is fetched separately by `/runs/[slug]/page.tsx` via `getRun(slug)`. Slight wastefulness — the `/api/runs/{run_id}` already returned the report, but the client refetches by slug.
- Why it matters: Extra round trip after redirect.
- Reproduction / reasoning: Network tab during completion redirect.
- Suggested fix direction: Pass the report through the store on `done` event, or short-circuit on the run-detail page if the store has the report.

## Type/build issues (if any)

- `npx tsc --noEmit` exits 0 (no errors). The project has no ESLint config; `npm run lint` blocks on an interactive prompt and was not pursued.
- `npm run build` was not invoked (would require backend keys / network and is out of scope for static checks). Recommend running it in CI.

## Test gaps

- No tests at all in `web/` (no `__tests__` / `*.test.*` files; `package.json` has no `test` script). High-leverage missing tests:
  - `lib/run-store.ts`: hydrate-vs-startRun race (F-FE-001), startRun failure path (F-FE-002), cancelRun event ordering (F-FE-003), `_applyEvent` per event type, persistence shape stability.
  - `lib/api.ts`: `parseSseChunk` (LF-only chunks, CRLF chunks, multi-`data:` lines, comment lines, BOMs, partial JSON across reads — F-FE-004, F-FE-006).
  - `components/analyze-form.tsx`: `staleSlugRef` semantics across reload (F-FE-015), redirect timing.
  - `components/run-hydrator.tsx`: StrictMode double-effect, 404 reset path.
  - `app/runs/page.tsx`: polling cleanup, in-flight + on-disk merge ordering (F-FE-013).
- Backend has pytest infra; the frontend has none. Even a minimal Vitest + React Testing Library setup would cover the highest-risk store logic.

## Notes / open questions

- `RunStatusResponse.input` is typed `string` (web/lib/api.ts:55). Backend always includes `input` for run-id requests but the slug branch returns `_report_payload(...)` which does NOT include `input` (server.py:241). `getRunStatus` is currently only called with run-ids by the store, so this drift is dormant — but would surface if anyone called `getRunStatus(slug)`.
- `RunSummary.tier` uses `Tier | null`; backend `_list_disk_runs` reads `score.get("tier")` which can be any value (literal string like "Strong" or unexpected). No runtime validation, so a corrupted on-disk report could send an unknown tier and `TierBadge` would crash on `meta = TIER_META[tier]` (`meta` is undefined, `Icon = ICONS[undefined]` is undefined, `<undefined ... />` throws). Not currently exploitable but worth a defensive lookup.
- `score-gauge.tsx` clamps to `[0, 100]` but does not handle non-finite (NaN/Infinity) values; `useTransform(mv, (v) => Math.round(v))` would render NaN. Backend always returns a number, but defensive coercion in `tierFromScore` and the gauge would harden against bad reports.
- `analyze-form.tsx` redirect uses `setTimeout(900ms)` then `router.push`. There's no cleanup if the component unmounts during the timeout (e.g., Next.js page change for another reason). The effect's return clears the timeout — verified — so this is fine.
- The `<RunHydrator/>` is mounted inside `<ThemeProvider/>` which is fine; no ordering hazard.
