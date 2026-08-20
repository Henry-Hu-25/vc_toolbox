# Dependency Readiness Report

## Summary
- Status: READY
- Blockers (if any): none

## Python toolchain
- Python version: 3.13.2 (`.venv/bin/python` -> python3.13)
- pytest collect: 52 tests collected (no errors)
- pytest baseline: PASS (52 passed, 0 failed) in 0.56s
- Installed deps verified: yes (all present via `importlib.metadata`)
  - fastapi=0.136.3
  - uvicorn=0.48.0
  - langgraph=1.2.2
  - langchain-openai=1.2.2
  - tavily-python=0.7.24
  - httpx=0.28.1
  - trafilatura=2.0.0
  - tenacity=9.1.4
  - pydantic=2.13.4
  - typer=0.26.1
  - rich=15.0.0
  - python-dotenv=1.2.2
  - structlog=25.5.0
  - pytest=9.0.3
  - pytest-asyncio=1.4.0

## Node toolchain
- Node version: v24.5.0, npm version: 11.5.1
- next + zustand present: yes (`web/node_modules/next` and `web/node_modules/zustand` both exist)
- tsc --noEmit: PASS (exit 0, no errors)
- next build: PASS (Next.js 15.5.18, compiled successfully in 1795ms, 5 static pages generated, exit 0)

## Services / credentials
- .env keys present: OPENAI_API_KEY (yes, non-empty), TAVILY_API_KEY (yes, non-empty)
- Backend health (8000): reachable, HTTP 200
  - Response body: `{"status":"ok","model_reasoning":"gpt-5.5","model_extract":"gpt-5.5","reasoning_effort":"medium","max_llm_calls":200,"openai_configured":true,"tavily_configured":true}`
- Frontend (3000): reachable, HTTP 200
- LLM/Tavily real call: skipped (not exercised in this readiness check to avoid spend; both providers report `*_configured: true` via /api/health)

## Open issues
- None observed. All mission-critical tooling, deps, services, and credentials are functional and ready for the bug-fix + UI mission.
