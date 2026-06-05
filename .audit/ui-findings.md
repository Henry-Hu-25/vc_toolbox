# UI/UX Improvement Audit

Read-only review of `web/` (Next.js 15 + React 19 + Tailwind + shadcn-style
primitives + Zustand + framer-motion + lucide-react + react-markdown). Every
finding is anchored to real code; no fixes were applied.

## Polish findings

### [P-UI-001] Marketing copy hardcodes the wrong model
- File: web/app/page.tsx:48
- Observation: Marketing card reads "Powered by GPT-5.5" while the live model
  string in `SiteFooter` is fetched from `/api/health` and may legitimately be
  anything (`FTA_MODEL_REASONING` is configurable). The two strings can
  disagree on the same page.
- Recommendation: Drop the hard-coded "GPT-5.5" copy or replace with the
  health value (already cached in footer). Even a generic "Frontier reasoning
  with structured outputs" is safer than a versioned claim.
- Impact: medium — Effort: S

### [P-UI-002] Examples chips submit immediately, with no preview affordance
- File: web/components/analyze-form.tsx:117-131
- Observation: Clicking "Vellum AI" / "Cursor" / "Perplexity" both populates
  the input and fires `handleSubmit` synchronously. There is no way to inspect
  or tweak the example before it runs, and the chip has no `aria-label`. The
  surrounding `Sparkles` icon with "Try:" reads like a hint, but the click
  behavior is "run now".
- Recommendation: Make a single click populate the input (and focus it),
  require a second click on Analyze to start. Add `aria-label="Try
  example: <name>"`. Optionally, dedicate a smaller secondary icon button on
  each chip for the "run now" shortcut.
- Impact: medium — Effort: S

### [P-UI-003] Run input has no clear/reset affordance
- File: web/components/analyze-form.tsx:104-113 (Input)
- Observation: Long URLs (`linkedin.com/company/foo`) clutter the input and
  there is no inline "X" to clear. The `Input` primitive (web/components/ui/input.tsx)
  does not support an end-adornment.
- Recommendation: Add an inline clear button (X icon, `aria-label="Clear"`)
  that appears when `value.length > 0`. Either extend the `Input` primitive
  with optional `endAdornment` or wrap a relative container in
  `analyze-form.tsx`.
- Impact: low — Effort: S

### [P-UI-004] No latency feedback between submit and first SSE event
- File: web/components/analyze-form.tsx:38-49 (`handleSubmit`)
- Observation: The Analyze button disables on submit, but there is no inline
  spinner. Backend `POST /api/analyze` returns `{run_id, status: "pending"}`
  immediately, then the worker schedules the LangGraph; the gap before the
  first `run_started` event can be a few seconds during which the form is
  blank-looking. The store transition is `pending → running` but the UI does
  not visually distinguish.
- Recommendation: Show a spinner inside the Analyze button while
  `submitting === true`. While `status === "pending"` (post-POST, pre-first
  event), render a "Queued..." line in the run panel before the stepper
  starts ticking.
- Impact: medium — Effort: S

### [P-UI-005] Cancel button has no `aria-label`, no confirmation
- File: web/components/analyze-form.tsx:155-159
- Observation: `Cancel` is rendered as a ghost button with an `X` icon and the
  word "Cancel". Screen readers will hear "Cancel" twice (icon + text), and
  there is no confirmation despite cancellation discarding accumulated cost.
- Recommendation: Either drop the icon or hide it from AT (`aria-hidden`).
  Consider a confirm step (button changes to "Click again to confirm") since
  in-flight runs cost real LLM/Tavily money.
- Impact: low — Effort: S

### [P-UI-006] Warnings list silently truncates at 4
- File: web/components/analyze-form.tsx:177-189
- Observation: `warnings.slice(0, 4)` then `+N more...`. The remainder is only
  visible after the run completes and the user navigates to the detail page.
- Recommendation: Make the chip clickable to expand the list inline, or link
  to the in-progress full list. At minimum, show a single line "View all in
  report" once `slug` is set.
- Impact: low — Effort: S

### [P-UI-007] No elapsed-time / ETA indicator during a run
- File: web/components/analyze-form.tsx run panel (lines 142-217), web/components/progress-stepper.tsx
- Observation: A typical run takes 60-120s. The user gets no sense of progress
  beyond the discrete 6-step ladder, and steps like `founder_researcher`
  legitimately take 30+ seconds. No timestamp or per-step duration is shown.
- Recommendation: Track `run_started.ts` in the store; display
  `mm:ss` next to "Analyzing" header. Optionally per-step elapsed displayed
  in the running step's right gutter.
- Impact: medium — Effort: M

### [P-UI-008] "Stale completion" gating is invisible to the user
- File: web/components/analyze-form.tsx:30-37, 65-77
- Observation: `staleSlugRef` correctly avoids redirect loops on logo clicks,
  but the user is shown a fresh empty form with no indication that they have
  a recent completed run sitting in localStorage. The link to the report is
  buried in /runs.
- Recommendation: When `isStaleCompletion === true`, render a small banner /
  card above the form: "Last report: <company> · View" linking to
  `/runs/${slug}`. Dismissible.
- Impact: medium — Effort: S

### [P-UI-009] "New run" button is a ghost; lacks visual weight
- File: web/components/analyze-form.tsx:160-164
- Observation: After completion or failure, the only way to start a fresh
  analysis from the run panel is the small ghost-style "New run" button in
  the top-right. It is the primary action in that state but visually
  outranked by everything else.
- Recommendation: Use `variant="outline"` or `subtle` and place a primary
  "Analyze another company" button at the bottom of the panel after the
  "Report ready" card.
- Impact: low — Effort: S

### [P-UI-010] History date column header is "Generated" but the data is fallback-mixed
- File: web/app/runs/page.tsx:99 (header) and 137 (`it.generated_at || it.modified_at`)
- Observation: When `generated_at` is missing (in-flight runs, partial reports),
  the cell silently shows `modified_at`. The header gives no hint. Two rows
  with very different temporal meanings render identically.
- Recommendation: Either show two columns ("Started" and "Generated") or
  prefix the cell with a small label: "started <time>" vs "generated <time>".
  At minimum a `<title>`-attribute tooltip distinguishing the two.
- Impact: medium — Effort: S

### [P-UI-011] In-flight history rows have no quick action back to the live panel
- File: web/app/runs/page.tsx:111-118 (row anchor) + 121-126 (in-flight pill)
- Observation: When `inFlight === true`, the company cell renders as plain
  text (no link). The user must navigate back to the home page manually,
  which only works if `runId` matches what is in the persisted store.
- Recommendation: Make the in-flight pill itself a link to `/` (or render the
  whole row as a link), and add a Cancel icon button bound to the run id.
  Both surfaces consume the existing store / API. See N-UI-001 / N-UI-003.
- Impact: high — Effort: S

### [P-UI-012] Status pill styling is inconsistent across states
- File: web/app/runs/page.tsx:120-129
- Observation: `running`/`pending` get the primary tier-of-blue treatment.
  `failed`/`cancelled` fall through to the same gray-bordered chip ("border
  border-border ... text-muted-fg") used by every non-completed state. They
  should have distinct color affordance (failed = rose, cancelled = neutral).
- Recommendation: Add a small status→variant map and reuse the `Badge`
  primitive with `variant="danger"` for failed and `variant="default"` for
  cancelled. Mirrors what `analyze-form` already does for the run panel.
- Impact: medium — Effort: S

### [P-UI-013] History table is not responsive
- File: web/app/runs/page.tsx:91-149
- Observation: Plain `<table>` with no horizontal scroll wrapper, no
  responsive collapse. On <640px, four columns + raw_input + tier pill
  overflow.
- Recommendation: Wrap in `<div className="overflow-x-auto">` (matches the
  pattern in `OverlapTable`). Better: switch to a card-list layout for the
  `sm` breakpoint and below, similar to the report's founder grid.
- Impact: medium — Effort: M

### [P-UI-014] Score column reads "—" for missing or in-flight rows, with no hover-explanation
- File: web/app/runs/page.tsx:131-135
- Observation: Em-dash is overloaded: "no score yet (running)" and "score
  failed to compute" both render identically. Users without context cannot
  tell why a row has no score.
- Recommendation: Show "—" only when status is `completed` and `overall_0_100
  == null` (real failure to score). For in-flight, show a tiny shimmer or
  "..." plus title attribute "Pending".
- Impact: low — Effort: S

### [P-UI-015] Run detail header — score block drops below text on small viewports
- File: web/app/runs/[slug]/page.tsx:91-122
- Observation: `flex-col lg:flex-row` means the gauge sits below the company
  description on tablets and phones. The gauge is the main signal of the
  page; burying it costs immediate scannability.
- Recommendation: At `md:` move the gauge to the right (smaller size) so the
  page leads with score even on mid-width screens; on mobile collapse to a
  compact `tier-badge + score-number` row above the title.
- Impact: medium — Effort: M

### [P-UI-016] View toggle isn't an aria tablist
- File: web/app/runs/[slug]/page.tsx:130-141
- Observation: Three buttons styled as tabs ("Structured / Markdown / JSON")
  but no `role="tablist"`, `role="tab"`, `aria-selected`, or
  `aria-controls`. Keyboard users cannot arrow between them, and screen
  readers announce three buttons.
- Recommendation: Add tablist semantics: `role="tablist"` on the wrapper,
  `role="tab"` + `aria-selected={view === v}` + `tabIndex` management on
  each, and `role="tabpanel"` on the rendered view.
- Impact: medium — Effort: S

### [P-UI-017] JSON view has no copy-to-clipboard
- File: web/app/runs/[slug]/page.tsx:184-191
- Observation: The structured/markdown views can be inspected in browser dev
  tools but JSON is the most copy-worthy. There is a `<pre>` with no copy
  button, no syntax highlighting, no collapsible sections.
- Recommendation: Add a small "Copy" icon button (top-right of the pre,
  `navigator.clipboard.writeText`). Markdown view can get the same.
- Impact: medium — Effort: S

### [P-UI-018] Markdown report `<a>` uses `break-all`
- File: web/app/globals.css:97-99 (`.prose-report a`)
- Observation: `break-all` is applied to every link in the markdown report,
  which mangles even short anchor text mid-word. It only matters for raw URL
  text.
- Recommendation: Replace `break-all` with `break-words` on `.prose-report a`,
  or apply `break-all` only when the link content looks like a URL (e.g.,
  via the markdown component override that already exists).
- Impact: low — Effort: S

### [P-UI-019] `.prose-report em` always muted
- File: web/app/globals.css:107-109
- Observation: Italics in the markdown report are styled as
  `text-muted-fg`, which means model-emphasized clauses fade into the
  surrounding paragraph (which is also `text-muted-fg`). They become
  invisible.
- Recommendation: Drop the rule; let italics use the default `text-fg` color
  but keep the slant for emphasis.
- Impact: low — Effort: S

### [P-UI-020] Score-bar is solid primary regardless of value
- File: web/app/runs/[slug]/page.tsx:240-252 (`ScoreBar`)
- Observation: Each criterion score (1-5) is shown as a flat purple bar at a
  proportional width. The visual quality of "5/5 vs 1/5" is the same color,
  which makes scanning the rubric for problem areas slow.
- Recommendation: Color-tint by score (e.g., 1 → tier-weak, 3 → tier-mixed,
  5 → tier-strong). Pull from the existing `--tier-*` tokens already defined
  in globals.css.
- Impact: medium — Effort: S

### [P-UI-021] Score gauge missing a11y attributes
- File: web/components/score-gauge.tsx:30-66
- Observation: The animated SVG gauge displays the headline score but has no
  `role="meter"`, `aria-valuenow`, `aria-valuemin`, `aria-valuemax`, or
  `aria-label`. Screen readers see only the running text "100 out of 100"
  flicker as the animation runs.
- Recommendation: Wrap the SVG in `<div role="meter" aria-valuenow={clamped}
  aria-valuemin={0} aria-valuemax={100} aria-label="Team score">` and remove
  the running-during-animation announcements (e.g., set the static value text
  with `aria-hidden` and a separate `<span class="sr-only">` for the final
  number).
- Impact: medium — Effort: S

### [P-UI-022] Tier color is the only signal, label aside
- File: web/components/tier-badge.tsx, web/lib/tier.ts
- Observation: The TierBadge pairs an icon with a label, which is good, but
  the gauge color is the sole encoding for tier. Color-blind users can read
  the number but lose the qualitative grade unless they know the cutoff
  thresholds.
- Recommendation: Place the TierBadge directly inside (or just under) the
  gauge value text, and consider segmenting the gauge ring into 4 arcs (one
  per tier) so the position of the active arc is itself the signal.
- Impact: medium — Effort: M

### [P-UI-023] Pill bullets render as raw "·" text
- File: web/app/runs/[slug]/page.tsx:286 (Strengths/Risks/DD lists)
- Observation: List markers are typed as `· {it}` literal text, which loses
  hanging indent on wrapped lines and can't be styled.
- Recommendation: Use `<ul class="list-disc pl-4">` with native bullets, or
  a styled icon (lucide `Dot`/`CircleDot`/`Check`/`AlertTriangle` keyed to
  the variant).
- Impact: low — Effort: S

### [P-UI-024] Founder card never surfaces sources
- File: web/components/founder-card.tsx (entire file), web/lib/types.ts:44 (`source_urls`)
- Observation: `FounderProfile.source_urls` is always populated from the
  backend, but the founder card never renders them. Users have to flip to
  the JSON view to verify which links back the claims.
- Recommendation: Add a small collapsible "Sources (N)" footer under
  "Notable" — list of citation links, max 5, "+N more". Reuses
  `ExternalLink` icon already imported.
- Impact: high — Effort: S

### [P-UI-025] CriterionScore evidence is data without a UI
- File: web/app/runs/[slug]/page.tsx:225-238 (criteria table), web/lib/types.ts:99 (`evidence`)
- Observation: Each `CriterionScore` carries an `evidence: string[]` of
  citation snippets/URLs but only `rationale` is shown. Evidence is the
  whole point of the "evidence-first" tagline on the home page.
- Recommendation: Add an expandable "evidence" disclosure beneath each
  rationale — `<details>` with the evidence list rendered as bullet links.
- Impact: high — Effort: S

### [P-UI-026] Cost ledger doesn't communicate $ or token cost
- File: web/components/cost-ledger.tsx, web/lib/types.ts:118-121 (`input_tokens`,`output_tokens`)
- Observation: Tokens are in the schema but the four ledger tiles only show
  call/search/extract/HTTP counts. Users running multiple companies care
  about total cost; they currently must do mental math.
- Recommendation: Add a fifth tile (or a row) showing total tokens
  (`input + output`) and an estimated $ cost using a sensible per-1k-token
  default keyed to model name. Even a rough estimate is a strong UX signal.
- Impact: medium — Effort: S

### [P-UI-027] InProgressPill is small and easily missed
- File: web/components/in-progress-pill.tsx, web/components/site-header.tsx:14
- Observation: The pill sits between the wordmark and the History link with
  comparable visual weight. New users running their first analysis often miss
  that the run is still progressing in the header when they navigate away.
- Recommendation: Increase contrast (solid primary background, white text)
  while running, add a tiny pulse-dot before the spinner, and on hover show a
  small popover with the current stepper status (read store directly).
- Impact: medium — Effort: M

### [P-UI-028] InProgressPill links to "/", not the live panel
- File: web/components/in-progress-pill.tsx:14
- Observation: Clicking the pill goes home, where `AnalyzeForm` may or may
  not display the run panel depending on stale state. From `/runs/[slug]`
  this is fine; from `/runs` it can feel arbitrary.
- Recommendation: Always route home and ensure the form auto-scrolls to the
  run panel; or, better, expose a dedicated `/runs/in-flight` route that
  renders `<AnalyzeForm/>` in run-panel-only mode and is a stable target.
- Impact: medium — Effort: M

### [P-UI-029] Header has no active-page indicator
- File: web/components/site-header.tsx:14-21
- Observation: The History link styling is identical on `/` and on `/runs`.
  No `aria-current="page"`, no underline, no muted vs. emphasized state.
- Recommendation: Use `usePathname()` to compute active state; apply
  `aria-current="page"` and a subtle underline / background to the active
  link. Same treatment for any future top-level routes.
- Impact: low — Effort: S

### [P-UI-030] Mobile nav has no compressed layout
- File: web/components/site-header.tsx:9-20
- Observation: Wordmark + (pill + History + theme-toggle) all fight for
  width at <380px. The pill already hides its label on `sm:hidden`, but the
  wordmark text "Founding Team Analyzer" doesn't shrink.
- Recommendation: Hide the wordmark on `xs` (logo-only), or add an
  abbreviated "FTA" wordmark below `sm`. Consider a hamburger that pushes
  History + theme into a sheet at the very smallest sizes.
- Impact: medium — Effort: M

### [P-UI-031] Theme toggle has no system option
- File: web/components/theme-toggle.tsx:8-21
- Observation: The button cycles strictly light↔dark even though
  `ThemeProvider` is configured with `defaultTheme="system"` and
  `enableSystem`. Once the user clicks once, they're locked out of the
  system-following mode without clearing localStorage.
- Recommendation: Replace the binary toggle with a 3-state cycle (light →
  dark → system) or a small dropdown with explicit options. Use icons
  Sun/Moon/Laptop. Existing `next-themes` already supports it.
- Impact: medium — Effort: S

### [P-UI-032] Theme toggle aria-label uses unmounted state on first paint
- File: web/components/theme-toggle.tsx:11-14
- Observation: `current` defaults to `theme || "light"` before mount, so the
  aria-label and icon may briefly mismatch the user's actual resolved theme,
  causing screen readers to announce stale text.
- Recommendation: Render a placeholder icon button while `!mounted`, or
  hydrate via `suppressHydrationWarning` on the button only. Keep the
  `mounted` guard around `setTheme`.
- Impact: low — Effort: S

### [P-UI-033] ProgressStepper missing `aria-current` and per-step semantics
- File: web/components/progress-stepper.tsx:18 (`<ol aria-live="polite">`)
- Observation: `aria-live="polite"` is on the list, but the running step has
  no `aria-current="step"` and the icons (Check/Loader2/Circle) are not
  hidden from AT — screen readers announce them as graphics.
- Recommendation: Add `aria-current="step"` to the running `<li>`,
  `aria-hidden="true"` on the SVG icons, and a visually-hidden text node
  describing the state (e.g., "completed", "in progress").
- Impact: medium — Effort: S

### [P-UI-034] ProgressStepper warning is silently amber with no detail
- File: web/components/progress-stepper.tsx:34-44, 88-98
- Observation: When a node finishes with `warnings.length > 0`, the step icon
  turns amber but neither the label color (also amber) nor a descriptive
  string tells the user *why*. The store already tracks the warnings list
  separately.
- Recommendation: Surface a count under the warning step ("2 warnings") and
  scroll target into the warnings panel below on click.
- Impact: medium — Effort: S

### [P-UI-035] ProgressStepper `step.detail` is dead-coded
- File: web/components/progress-stepper.tsx:7-15 (Step type), web/lib/run-store.ts:18-38
- Observation: The component accepts `step.detail` and animates it nicely,
  but the store's `Step` type omits `detail` and no event handler ever sets
  it. The visual is wasted.
- Recommendation: Either thread per-step status text from `node_started` /
  `node_finished` events (e.g., "found 3 founders") into the step object, or
  drop the prop. Wiring it up would significantly improve the run panel.
- Impact: medium — Effort: M

### [P-UI-036] ProgressStepper running icon has no pulse
- File: web/components/progress-stepper.tsx:74-86
- Observation: The "running" ring is a static border with a spinning
  `Loader2`. The done state has a nice spring motion in; the running state is
  visually static other than the spinner.
- Recommendation: Add a soft `animate-pulse` on the ring, or a framer-motion
  `scale` loop, to reinforce that the step is live and not stuck.
- Impact: low — Effort: S

### [P-UI-037] Footer hardcodes version
- File: web/components/site-footer.tsx:24
- Observation: "founding_team_analyzer v0.1.1" is a literal string. The
  backend has no equivalent of this string in the package metadata, but
  whatever the right answer is, this drifts the moment the package version
  changes.
- Recommendation: Either pull from `getHealth()` (add `version` to
  `/api/health`) or remove the version. The model+effort line is enough.
- Impact: low — Effort: S

### [P-UI-038] Logo colors don't adapt to theme
- File: web/components/site-header.tsx:25-32
- Observation: The three circles use `hsl(var(--primary))`,
  `hsl(217 91% 60%)`, `hsl(158 64% 52%)`. The latter two are hard-coded and
  don't shift between light/dark; the first does. Result: in dark mode, two
  circles glow saturated while one is desaturated.
- Recommendation: Use the existing tier tokens (`--tier-promising`,
  `--tier-strong`) for all three circles so they stay consistent with the
  rest of the palette in both themes.
- Impact: low — Effort: S

### [P-UI-039] Warning/error backgrounds have very low contrast in dark mode
- File: web/app/globals.css:33-40 (dark vars), web/components/analyze-form.tsx:178 / 192
- Observation: `bg-amber-500/5` and `bg-rose-500/5` work on light backgrounds
  but on `--bg: 240 10% 4%` they're nearly invisible — the warnings panel
  reads like ordinary muted text. The colored border is the only signal.
- Recommendation: Bump the alpha to `/10` or `/15` in dark mode (tailwind
  `dark:bg-amber-500/15`), or define `--warning-bg` / `--danger-bg` tokens
  with separate light/dark values.
- Impact: medium — Effort: S

### [P-UI-040] Markdown report has no max-content scroll on long reports
- File: web/app/runs/[slug]/page.tsx:178-184 (Markdown view)
- Observation: JSON view caps at `max-h-[70vh]`, but Markdown view fills the
  page indefinitely. On very large reports, users lose orientation; there is
  no in-page TOC, no anchor for headings, and `prose-report h2` does not
  render `id`s.
- Recommendation: Add `id` slugs to headings via a `rehype-slug` plugin (no
  new dep beyond what react-markdown supports natively) and a small floating
  TOC sidebar at `lg:` derived from `report.markdown` headings.
- Impact: medium — Effort: M

### [P-UI-041] OverlapTable can overflow on mobile
- File: web/components/overlap-table.tsx:21-42
- Observation: 6-column table is wrapped in `overflow-x-auto`, which works
  but yields a horizontal scrollbar with no affordance. The narrative
  per-pair list below is the more digestible representation but is treated as
  secondary.
- Recommendation: At `< md` collapse the table into a stack of pair "cards"
  using the narrative + bullet lists; keep the table for `md+`.
- Impact: low — Effort: M

### [P-UI-042] No empty / null state for an analysis with zero overlap
- File: web/components/overlap-table.tsx:14-19
- Observation: When `overlap.pairs` is empty, the message defaults to "No
  pairwise overlap available." This conflates "we ran the analyzer but found
  no overlap" (a meaningful result) with "we don't have data". For a solo
  founder this fires even though it's the expected outcome.
- Recommendation: Distinguish via founder count: if there is only 1 founder
  in the report, render "Solo founder — overlap not applicable." Otherwise,
  surface `overlap.notes` more visibly.
- Impact: low — Effort: S

### [P-UI-043] Report download names use slug, not company name
- File: web/app/runs/[slug]/page.tsx:325-333 (`downloadMarkdown`)
- Observation: The file is named `${slug}.report.md`, e.g.
  `vellum-ai.report.md`. Functional but feels machine-generated. Same goes
  for the JSON link, which targets `/api/runs/<slug>` and downloads with the
  slug.
- Recommendation: `${company.name || slug}.report.md` (sanitize spaces).
- Impact: low — Effort: S

### [P-UI-044] No way to retry a failed run with the same input
- File: web/components/analyze-form.tsx:191-205 (error block)
- Observation: "Try again" calls `handleReset()`, which clears the input
  field. Users have to re-paste/re-type the original company. The store
  still has `input` available.
- Recommendation: Add a primary "Retry" button that calls
  `startRun(state.input)` directly; keep "New run" as the secondary affordance.
- Impact: medium — Effort: S

### [P-UI-045] No autofocus / focus management on view switch
- File: web/app/runs/[slug]/page.tsx:131-141 (view tabs)
- Observation: When the user switches `Structured → Markdown → JSON`, focus
  stays on the tab button, but the new content has no scroll-into-view or
  focus shift. With long reports, switching tabs is jarring.
- Recommendation: When `view` changes, `scrollIntoView` the tabpanel or set
  focus to the panel root via a ref. Pairs naturally with the tablist
  semantics in P-UI-016.
- Impact: low — Effort: S

### [P-UI-046] Skeletons don't match the eventual layout
- File: web/app/runs/[slug]/page.tsx:299-310 (`ReportSkeleton`)
- Observation: The skeleton shows two text bars and three squares. The
  eventual page has a gauge, badges, founder cards, an overlap table and a
  rubric table. Layout-shift on first load is significant.
- Recommendation: Build a more faithful skeleton that mirrors header (text
  block + circle gauge), criteria rows, and founder grid heights. Reuse the
  `Skeleton` primitive.
- Impact: low — Effort: M

### [P-UI-047] SSE failures are silent on the run panel
- File: web/lib/run-store.ts:111-121 (`subscribe.onError`)
- Observation: When the SSE stream errors mid-run, the error message is
  written to `state.error` but the run panel still displays the stepper
  without surfacing that streaming was lost. Users see steps frozen in
  "running" state with no recovery path.
- Recommendation: Add a small reconnect banner at the top of the run panel
  ("Connection lost — reconnecting...") and trigger an automatic
  `subscribe(runId)` retry with backoff.
- Impact: medium — Effort: M

### [P-UI-048] Container width is fixed at 1200px regardless of route
- File: web/tailwind.config.ts:11-15 (container 2xl: 1200px)
- Observation: Run detail uses `max-w-5xl` (~1024) inside the container, but
  the History page uses `max-w-4xl` (~896) and the home page `max-w-2xl`
  (~672). Switching pages causes the visible "page width" to jump.
- Recommendation: Pick one canonical container width per "marketing" vs
  "app" contexts. `max-w-5xl` is a fine default for History; the home page
  marketing column can keep its narrower width but center inside the wider
  shell.
- Impact: low — Effort: S

### [P-UI-049] FeatureGrid is decorative-only and unanchored
- File: web/app/page.tsx:34-58
- Observation: Three cards explain features but none link anywhere (no docs
  page exists). They claim "Powered by GPT-5.5" (see P-UI-001) and reduce
  the marketing column's actionable surface.
- Recommendation: Either link each card to a relevant section in a docs page
  or to corresponding parts of a sample report; or replace with a single
  "How it works" disclosure.
- Impact: low — Effort: M

### [P-UI-050] Founder card initials handle international names poorly
- File: web/components/founder-card.tsx:11-17
- Observation: `name.split(/\s+/).map(n => n[0]).slice(0, 2).join("")` will
  miss combining marks for Asian names ("陈" is fine, "Jean-Luc" returns "J")
  and produce a single initial for mononym names.
- Recommendation: Use `Array.from(name)[0]` per token, fallback to first 2
  graphemes of the first token when there is only one word.
- Impact: low — Effort: S

## New-feature opportunities

### [N-UI-001] Cancel an in-flight run from the History row
- Surface: web/app/runs/page.tsx, in-flight row hover state.
- Description: Right-end action button on rows where
  `inFlight === true`. Calls `DELETE /api/runs/{run_id}` and refreshes the
  list.
- Sketch: Reuse existing `cancelRun(runId)` from `lib/api.ts`. Add an
  `IconButton` (lucide `X`) in a new column or as an absolute element in the
  Status cell. After call, optimistic-update the row to `cancelled`. No new
  deps.
- Impact: high — Effort: S
- New deps: none.

### [N-UI-002] Search and filter on History
- Surface: web/app/runs/page.tsx, above the table.
- Description: Text search by `company_name` / `raw_input`, tier filter
  (4 chips), date range. Persist filter state in URL query params so links
  are shareable.
- Sketch: Local state + `useSearchParams`/`useRouter().replace`. Filter
  in-memory over `items`. Add a small toolbar above the table reusing
  `Input`, `Badge`, and existing chip styles. No virtualization needed at
  current data scale.
- Impact: high — Effort: M
- New deps: none.

### [N-UI-003] Clickable in-progress pill that returns to the live run panel
- Surface: web/components/in-progress-pill.tsx + web/components/analyze-form.tsx.
- Description: Pill click should always open the live stepper, regardless of
  current route. On home, scroll to the form; on detail/history, navigate
  home and auto-scroll.
- Sketch: Pass an anchor `#live-run` on the home page; pill href becomes
  `/#live-run`. Add a popover preview on hover (current step + elapsed) by
  reading `useRunStore` directly inside the pill.
- Impact: high — Effort: S
- New deps: none.

### [N-UI-004] Rerun / regenerate from the detail page
- Surface: web/app/runs/[slug]/page.tsx, near the "JSON / .md" toolbar.
- Description: A "Rerun" button on a completed report posts the original
  `raw_input` (or company name) back to `/api/analyze` and navigates to the
  fresh run. Useful for "we have new evidence; rescore."
- Sketch: Read `report.raw_input` (already in `ReportPayload`). Call
  `useRunStore.startRun(input)` then redirect to `/`. Confirm dialog because
  it incurs LLM/Tavily cost.
- Impact: medium — Effort: S
- New deps: none.

### [N-UI-005] Copy / share link affordance on the report
- Surface: web/app/runs/[slug]/page.tsx, in the JSON / .md toolbar.
- Description: "Copy link" button (lucide `Link2`) writes the full URL to
  clipboard. Optional toast confirms.
- Sketch: `navigator.clipboard.writeText(window.location.href)`; show a
  small inline confirmation that fades after 2s. Pairs with N-UI-011.
- Impact: medium — Effort: S
- New deps: none.

### [N-UI-006] Print / PDF-friendly report layout
- Surface: web/app/runs/[slug]/page.tsx, "Print" button next to download
  buttons.
- Description: A `@media print` stylesheet that hides nav/footer/toolbars,
  forces the structured view, expands all founder cards, and uses a serif-ish
  prose layout. Plus a `window.print()` button.
- Sketch: Add `@media print` blocks in `globals.css` (e.g., hide
  `.no-print`). Tag SiteHeader/SiteFooter/view-toggle with `no-print`. Force
  `prose-report a::after { content: " (" attr(href) ")"; }` so URLs print.
- Impact: medium — Effort: M
- New deps: none.

### [N-UI-007] Keyboard shortcuts
- Surface: global, with a small "?" overlay listing shortcuts.
- Description: Cmd/Ctrl-K to focus the home input; "g h" to go to History;
  "g i" to go to Home; Esc to dismiss modals; "/" to focus search on
  History; "1/2/3" to switch report views.
- Sketch: A global `useEffect` keydown handler in a `KeyboardShortcuts` hook
  rendered once in `app/layout.tsx`. Use `useRouter().push`. Conditionally
  ignore when typing in input/textarea. The "?" overlay can reuse `Card`.
- Impact: medium — Effort: M
- New deps: none.

### [N-UI-008] Score breakdown by criterion (radar / per-criterion bars)
- Surface: web/app/runs/[slug]/page.tsx, replacing or augmenting
  ScoreSection.
- Description: A radar chart of the 8 criteria (visual sense of skill
  balance), or a horizontal bar chart sorted by weighted contribution.
- Sketch: Build the radar in pure SVG (no chart lib needed for 8 axes); each
  axis labelled with `criteria[i].label`, ring at 0/2.5/5. Or use a
  `framer-motion` animated SVG. Render alongside the existing rubric table
  rather than replacing it.
- Impact: high — Effort: M
- New deps: none (pure SVG).

### [N-UI-009] Expandable founder card with sources inline
- Surface: web/components/founder-card.tsx.
- Description: Click anywhere on the card (or a chevron) to expand a
  "Sources" section showing the founder's `source_urls`, plus per-section
  `source_urls` from education/work entries. Closes on second click.
- Sketch: Local `useState<boolean>` per card, animated via framer-motion
  `AnimatePresence`. Reuses `ExternalLink` icon. Builds on P-UI-024.
- Impact: high — Effort: S
- New deps: none.

### [N-UI-010] Cumulative cost badge in header
- Surface: web/components/site-header.tsx, between InProgressPill and the
  History link.
- Description: Aggregate the cost ledger across all runs in `out/` and show
  a compact "$0.42 · 14 runs" badge. Click reveals a small popover.
- Sketch: Backend sum is cheaper to compute; either add `/api/cost-summary`
  or sum client-side from `listRuns()` (which currently does not include
  cost). Recommend backend endpoint that aggregates from existing report.json
  files.
- Impact: medium — Effort: M
- New deps: none.

### [N-UI-011] Toast / notification on run completion when on a different page
- Surface: global; mount toaster in app/layout.tsx.
- Description: When `status` transitions to `completed`/`failed` while
  `pathname !== "/"`, show a toast linking to the new report. Optional
  browser Notification API permission for system-level notifications.
- Sketch: Add a tiny `Toast` primitive under `components/ui/` (subscribe to
  the store, render a stack at top-right). Use `framer-motion` (already in).
  Optionally request `Notification.permission` from a settings affordance.
- Impact: high — Effort: M
- New deps: none.

### [N-UI-012] Three-state theme toggle with system detection
- Surface: web/components/theme-toggle.tsx.
- Description: Replace binary toggle with a 3-cycle (Light → Dark → System)
  button; or a small dropdown with the three options. Respects user's OS
  preference when "System" is selected.
- Sketch: Already supported by `next-themes`. Add `Laptop` icon (lucide).
  Cycle order: light → dark → system. Persist via next-themes default.
- Impact: medium — Effort: S
- New deps: none.

### [N-UI-013] Compare two runs side-by-side
- Surface: New route `/runs/compare?a=<slug>&b=<slug>`, plus a "Compare"
  toggle on the History page.
- Description: VC use-case: stack two analyses side by side, diff scores,
  highlight where one team beats the other.
- Sketch: Multi-select rows on `/runs` with a "Compare (2)" CTA. Compare
  page fetches both reports in parallel and renders mirrored sections.
  Reuses ScoreGauge, FounderCard, OverlapTable.
- Impact: medium — Effort: L
- New deps: none.

### [N-UI-014] Free-text notes / tags per run
- Surface: web/app/runs/[slug]/page.tsx, sidebar or under header.
- Description: Investor-style annotation: a textarea + tag chips persisted
  to `localStorage` keyed by slug, plus a tag filter on History.
- Sketch: New Zustand slice (or separate store) with shape
  `{ [slug]: { notes: string, tags: string[] } }`. Render an editable
  block on detail; surface tags as chips on History rows. Optional backend
  persistence as a follow-up.
- Impact: medium — Effort: M
- New deps: none.

### [N-UI-015] Star / pin runs
- Surface: web/app/runs/page.tsx + detail page.
- Description: Per-run boolean stored client-side; pinned runs sort to the
  top of History with a star icon, also accessible from a "Starred" filter.
- Sketch: Same store as N-UI-014; add a `starred: Set<slug>`. Star button
  on detail page header + History row leftmost cell.
- Impact: low — Effort: S
- New deps: none.

### [N-UI-016] Export History as CSV
- Surface: web/app/runs/page.tsx, top-right of the table.
- Description: "Export CSV" downloads the visible (filtered) rows with
  columns slug/company/tier/score/generated_at. Useful for VCs running batch
  diligence.
- Sketch: Client-side CSV builder over the in-memory `items` array; trigger
  `Blob` download (same pattern as `downloadMarkdown` in the detail page).
  Apply current N-UI-002 filters.
- Impact: medium — Effort: S
- New deps: none.

### [N-UI-017] Sortable History columns
- Surface: web/app/runs/page.tsx table header.
- Description: Click column headers to sort by company/tier/score/date.
  Indicator caret. Persist last sort in localStorage or query params.
- Sketch: Local state `{key, dir}`; `useMemo` over `items` to sort.
  `lucide-react` chevron icons indicate direction. No new deps.
- Impact: medium — Effort: S
- New deps: none.

### [N-UI-018] In-page TOC for the markdown report
- Surface: web/app/runs/[slug]/page.tsx markdown view.
- Description: A floating right-rail TOC that lists each `##` heading,
  highlights the active section as the user scrolls.
- Sketch: Parse the markdown for `## ` headings (regex), render with
  anchor links targeting heading slugs. Use `IntersectionObserver` for the
  active state. See P-UI-040.
- Impact: medium — Effort: M
- New deps: optionally `rehype-slug` (~3KB) for stable anchor IDs; can be
  done by hand instead.

### [N-UI-019] Animated cost / token counters during streaming
- Surface: web/components/cost-ledger.tsx during a live run.
- Description: When a `cost_update` event arrives, animate the numbers
  upward instead of snapping. Reinforces the live feel.
- Sketch: Reuse `useMotionValue` + `useTransform` pattern from
  `score-gauge.tsx` for each tile's value. Skip the animation when the page
  loads with a static cost (detail page).
- Impact: low — Effort: S
- New deps: none.

### [N-UI-020] System-level "Run done" notification opt-in
- Surface: Settings dropdown (new) or one-click in N-UI-011 toast.
- Description: For users running long analyses while doing other work,
  request `Notification.permission` and fire `new Notification("Run done")`
  on completion.
- Sketch: Add a small `useNotificationPermission` hook; call after the user
  starts their first run (gated). Pair with N-UI-011 so in-tab toast still
  fires.
- Impact: low — Effort: S
- New deps: none (Web Notifications API).

### [N-UI-021] "Continue where you left off" banner
- Surface: web/app/page.tsx home, above AnalyzeForm.
- Description: When a prior completed run sits in the persisted store but
  the form is showing the empty state (the "stale completion" case), surface
  a banner: "Last report: <company> — view".
- Sketch: Read store inside a small `LastReportBanner` client component
  rendered on `/`. Dismissible with a session-only flag. See P-UI-008.
- Impact: medium — Effort: S
- New deps: none.

### [N-UI-022] Per-criterion evidence drawer
- Surface: web/app/runs/[slug]/page.tsx ScoreSection.
- Description: Click a criterion row to slide-out a panel showing
  `criterion.evidence[]` with citation links. See P-UI-025.
- Sketch: Lift `selectedCriterion` state to ScoreSection; render side panel
  using framer-motion. On `lg:` it can render inline as a second column.
- Impact: high — Effort: M
- New deps: none.

## Notes / open questions

- The audit assumes the existing `lib/types.ts` already mirrors the backend
  schema. A few of the high-value features (N-UI-014 notes/tags, N-UI-013
  compare, N-UI-010 cost summary) would benefit from new backend endpoints
  rather than client-only persistence; the `runs.py` registry doesn't survive
  restarts, but `out/` does, so notes/tags should be persisted to disk via a
  small `notes.json` next to each `report.json` if you want them durable.
- Several findings (P-UI-007 elapsed time, P-UI-035 step.detail wiring,
  N-UI-019 animated counters) depend on additional metadata that the
  streaming pipeline does or does not emit today. Cross-check
  `events.py::EventType` and `streaming_graph.py` for what's available before
  designing the surface.
- A11y gaps (P-UI-016, P-UI-021, P-UI-033, P-UI-005) are individually small
  but together meaningfully affect screen-reader users; consider treating
  them as one batched accessibility pass rather than disparate tickets.
- The `prose-report` styling (P-UI-018, P-UI-019) is shared across every
  rendered markdown; small CSS changes carry global blast radius. Verify
  against existing reports in `out/` before merging.
- `_unsubscribe` is correctly excluded from the Zustand `partialize`
  allowlist; any new persisted fields added during these features must
  preserve that contract per AGENTS.md.
