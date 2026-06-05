# Founding Team Analyzer

LangGraph multi-agent tool that analyzes a startup founding team from a single input
(URL, LinkedIn URL, or company name) and emits a markdown + JSON report.

## Install

```bash
cd vc_toolbox/founding_team_analyzer
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env  # then fill OPENAI_API_KEY and TAVILY_API_KEY
```

## Run

```bash
python -m founding_team_analyzer analyze "https://acme.ai"
python -m founding_team_analyzer analyze "Acme Robotics"
python -m founding_team_analyzer analyze "https://www.linkedin.com/company/acme-robotics" --out ./out/
```

### Flags

| Flag | Default | Notes |
|------|---------|-------|
| `--out PATH` | `./out` | Output directory root |
| `--max-founders INT` | 5 | Caps researcher fan-out |
| `--model NAME` | `gpt-4o` | Override the reasoning model |
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

## Architecture

See [`founding-team-analyzer-spec.md`](../founding-team-analyzer-spec.md) at the repo root
for the full design: 6 LangGraph nodes (CompanyProfiler -> FounderFinder -> Researcher fan-out
-> OverlapAnalyzer -> TeamScorer -> ReportWriter), rubric, schemas, and guardrails.
