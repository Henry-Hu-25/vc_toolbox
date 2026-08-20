# Validation Readiness Report

## Summary
- Status: BLOCKED (non-fatal): programmatic toolchain is fully READY; the live UI surface is degraded because the long-lived `next dev` server is now serving stale dev chunk paths after `npm run build` overwrote `web/.next/static/`. The backend HTTP / SSE surface is healthy.
- Recommended max concurrent agent-browser validators: **3** (capped by RAM headroom, not the formula's hard cap of 5)
  - Reasoning: ~2.98 GB estimated available memory, 70% headroom = ~2.14 GB. One agent-browser session with a single tab on `localhost:3000/runs` measured ~684 MB RSS (1 daemon + 7 Chrome helpers). 2.14 GB / 0.684 GB ≈ 3.13 → floor to 3. Well under the formula's cap of 5.

## Programmatic toolchain
- pytest: PASS (52 passed, 0 failed; tail: `52 passed in 1.42s`, exit 0)
- tsc (`npx tsc --noEmit`): PASS (exit 0, no output)
- next build (`npm run build`): PASS (Next.js 15.5.18, "Static" + "Dynamic" route table emitted, exit 0)

## UI surface (agent-browser)
- Backend reachable: `GET /api/health` → 200; `GET /api/runs` → 3 completed registry/disk runs (perplexity, cursor, vellum).
- Home page (`/`): loaded; title "Founding Team Analyzer"; H1 "Score a founding team in 90 seconds."; primary controls visible (textbox, disabled "Analyze" button, sample-company buttons "Vellum AI", "Cursor", "Perplexity"; "History" link in header). Initial first GET returned a transient 500 (next dev recompile), second GET 200 — typical cold-compile.
- History page (`/runs`): loaded with H1 "History" but **0 rendered rows** — the page is stuck on the skeleton placeholder (`div.skeleton ×3`). The `GET /api/runs` fetch from the page context succeeds (status 200, 3 items), but client-side hydration cannot complete because `next dev` is requesting unhashed dev chunk paths that no longer exist (see Open issues #1).
- Run detail (`/runs/perplexity`): backend `GET /api/runs/perplexity` → 200 (slug resolves on disk), but the page renders only header/footer text "Back to history" — Score Gauge / company name not visible because of the same broken-chunk issue. The render path is therefore not exercised.
- Backend events endpoint: 404 on unknown UUID confirmed: `GET /api/runs/00000000-0000-0000-0000-000000000000/events` → 404 (matches `_is_uuid` discriminator behavior in `server.py`).

## Resources
- Total RAM: 18 GB (`hw.memsize` = 19,327,352,832 bytes); free: ~0.017 GB; inactive (reclaimable): ~3.0 GB; estimated available (free + inactive + speculative): **~2.98 GB**
- CPU cores: 11 physical / 11 logical; load avg: 4.33, 4.26, 4.22 (15+ minute averages, sustained)
- next dev (PID 68645 launcher + 68646 next-server): launcher RSS ~1.5 MB; next-server RSS ~39–166 MB (volatile; ~166 MB after recent recompile attempts)
- uvicorn (PID 68733, founding_team_analyzer): RSS ~9–10 MB (idle; small because most pages are paged out under memory pressure — system shows 8.1 GB in compressor and ~272M historical swapouts)
- agent-browser session RSS overhead (1 daemon + 1 Chrome main + GPU + Network + Storage + 4 Renderer helpers, all single-tab on `/runs`): **~684 MB total** across 8 new processes (process count 129 → 137); browser closed cleanly via `agent-browser close`.
- Headroom (70% of 2.98 GB available): **~2.14 GB**
- Max concurrent agent-browser validators (using mission-planning Phase 6 formula `min(floor(headroom / per_session), 5)`): floor(2.14 / 0.684) = 3 → **3**

## Open issues
1. **`next dev` serving stale chunk paths after `npm run build`.** The long-lived dev server (uptime 4d 19h, PID 68646) is requesting unhashed dev chunks like `_next/static/chunks/main-app.js`, `app-pages-internals.js`, `app/layout.js`, `app/runs/page.js`, `app/runs/[slug]/page.js` — all return 404 because `npm run build` overwrote `web/.next/static/` with hashed production filenames (`main-app-7ddb994b8b147d5f.js`, etc.). Server-rendered HTML still loads, the API call from the page context succeeds, but client hydration / dynamic content rendering does not. **Live UI validation against the running dev server is therefore not currently usable.** Resolution: the parent agent / user must restart `next dev` (it will rebuild the dev manifest fresh). Per task constraints I did not start or modify any server or source file. As a procedural note for future readiness checks: run `next build` against a separate `.next-prod/` distDir or simply do not run `next build` against a directory whose dev server is live.
2. agent-browser was successfully exercised end-to-end (open, snapshot, get title, eval, network requests, close). No tooling blockers there.
3. SSE replay against an in-flight run was not exercised because there were no in-flight runs in the registry; the unknown-UUID 404 fallback was confirmed instead, per task instructions.
