# Founding Team Analyzer

LangGraph multi-agent tool that analyzes a startup founding team from a single input
(URL, LinkedIn URL, or company name) and emits a markdown + JSON report.

## Install

```bash
cd vc_toolbox/founding_team_analyzer
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,server]"
cp .env.example .env  # then fill OPENAI_API_KEY and TAVILY_API_KEY
```

## Run

### CLI

```bash
python -m founding_team_analyzer analyze "https://acme.ai"
python -m founding_team_analyzer analyze "Acme Robotics"
python -m founding_team_analyzer analyze "https://www.linkedin.com/company/acme-robotics" --out ./out/
```

### Server

```bash
python -m uvicorn founding_team_analyzer.server:app --host 127.0.0.1 --port 8000
```

API endpoints:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/analyze` | Start a run, returns `{run_id, status}` immediately |
| GET | `/api/runs/{id}/events` | SSE stream of run events |
| GET | `/api/runs/{id}` | Run status (UUID = registry, slug = disk) |
| DELETE | `/api/runs/{id}` | Cancel a running task (non-blocking) |
| GET | `/api/runs` | List all runs (in-flight + on-disk) |
| GET | `/api/health` | Health check with model info |

### Flags

| Flag | Default | Notes |
|------|---------|-------|
| `--out PATH` | `./out` | Output directory root |
| `--max-founders INT` | 5 | Caps researcher fan-out |
| `--model NAME` | `gpt-5.5` | Override the reasoning model |
| `--no-self-critique` | off | Skip TeamScorer self-critique pass |
| `--verbose` | off | Pretty structlog mode |
| `--save-state PATH` | unset | Dump full AnalyzerState to JSON |

## Output

Each run writes:

- `out/<company-slug>/report.md` — human-readable report
- `out/<company-slug>/report.json` — machine-readable structured output

A worked example lives in `examples/sample_report.md`.

## Testing

```bash
pip install -e ".[dev]"
pytest
```

## Environment Variables

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

## Architecture

See [`founding-team-analyzer-spec.md`](../founding-team-analyzer-spec.md) at the repo root
for the full design: 6 LangGraph nodes (CompanyProfiler -> FounderFinder -> Researcher fan-out
-> OverlapAnalyzer -> TeamScorer -> ReportWriter), rubric, schemas, and guardrails.
