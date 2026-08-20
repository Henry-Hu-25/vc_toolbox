# VC Toolbox — Founding Team Analyzer

LangGraph multi-agent tool that analyzes a startup founding team from a single
input (URL, LinkedIn URL, or company name) and emits a markdown + JSON report.

## Quick Start

```bash
# Backend
cd founding_team_analyzer
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,server]"
cp .env.example .env   # fill OPENAI_API_KEY and TAVILY_API_KEY

# Frontend
cd ../web
npm install

# Run both services (two terminals)
cd founding_team_analyzer && .venv/bin/python -m uvicorn founding_team_analyzer.server:app --host 127.0.0.1 --port 8000
cd web && npm run dev   # http://localhost:3000
```

## Architecture

**Backend** (`founding_team_analyzer/`) — FastAPI + LangGraph. Six-node pipeline:
CompanyProfiler -> FounderFinder -> Researcher fan-out -> OverlapAnalyzer ->
TeamScorer -> ReportWriter. Runs are managed by an in-process `RunRegistry`
with pub/sub, replay, and cancellation.

**Frontend** (`web/`) — Next.js 15 App Router + Zustand. All run state lives in
a persisted Zustand store; components never open SSE directly. The store owns
the subscription lifecycle.

See [`founding-team-analyzer-spec.md`](founding-team-analyzer-spec.md) for the
full design doc.

## CLI

```bash
python -m founding_team_analyzer analyze "Acme Robotics"
python -m founding_team_analyzer analyze "https://acme.ai" --out ./out/
```

| Flag | Default | Notes |
|------|---------|-------|
| `--out PATH` | `./out` | Output directory root |
| `--max-founders INT` | 5 | Caps researcher fan-out |
| `--model NAME` | `gpt-5.5` | Override the reasoning model |
| `--no-self-critique` | off | Skip TeamScorer self-critique pass |
| `--verbose` | off | Pretty structlog mode |
| `--save-state PATH` | unset | Dump full AnalyzerState to JSON |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/analyze` | Start a run, returns `{run_id, status}` immediately |
| GET | `/api/runs/{id}/events` | SSE stream of run events |
| GET | `/api/runs/{id}` | Run status (UUID = registry, slug = disk) |
| DELETE | `/api/runs/{id}` | Cancel a running task (non-blocking) |
| GET | `/api/runs` | List all runs (in-flight + on-disk) |
| GET | `/api/health` | Health check with model info |

## Environment

Backend reads `founding_team_analyzer/.env`:

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `OPENAI_API_KEY` | yes | — | LLM provider key |
| `TAVILY_API_KEY` | yes | — | Web search key |
| `FTA_MODEL_REASONING` | no | `gpt-5.5` | Reasoning model |
| `FTA_MODEL_EXTRACT` | no | `gpt-4o-mini` | Extraction model |
| `FTA_REASONING_EFFORT` | no | `medium` | none/low/medium/high/xhigh |
| `FTA_MAX_FOUNDERS` | no | 5 | Caps researcher fan-out |
| `FTA_MAX_TAVILY_PER_FOUNDER` | no | 5 | Search calls per founder |
| `FTA_MAX_EXTRACTS_PER_FOUNDER` | no | 3 | Page extracts per founder |
| `FTA_MAX_LLM_CALLS` | no | 200 | Per-run circuit breaker |
| `FTA_MAX_REGISTRY_RUNS` | no | 100 | Max runs in memory |
| `FTA_CORS_ORIGINS` | no | localhost:3000,127.0.0.1:3000 | Comma-separated |
| `FTA_OUTPUT_DIR` | no | `./out` | Report output directory |

Frontend reads `NEXT_PUBLIC_API_BASE` (default `http://127.0.0.1:8000`).

## Testing

```bash
cd founding_team_analyzer && .venv/bin/python -m pytest    # 175 backend tests
cd web && npx tsc --noEmit                                  # TypeScript typecheck
```
