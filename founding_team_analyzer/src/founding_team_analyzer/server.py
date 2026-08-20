"""FastAPI server exposing the analyzer over HTTP + SSE.

Endpoints:
    GET    /api/health                     -> liveness + model info
    GET    /api/rubric                     -> house rubric criteria + weights
    POST   /api/analyze                    -> register a run, return {run_id, status}
    GET    /api/runs/{run_id}/events       -> SSE stream (replay + live) for a run
    GET    /api/runs/{run_id}              -> status + (if completed) full report
    DELETE /api/runs/{run_id}              -> cancel an in-flight run
    GET    /api/runs                       -> merged in-flight + on-disk listing
    GET    /api/runs/{slug}                -> on-disk report by slug (legacy)

NOTE: `GET /api/runs/{id}` is overloaded: registry run ids are uuid4 strings,
on-disk reports use human-readable slugs. The handler tries the registry
first, then falls back to the on-disk store.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import config as config_module
from .runs import REGISTRY, RunRecord
from .scoring import RUBRIC
from .streaming_graph import stream_analysis
from .tools.normalize import slugify


def _settings():
    return config_module.SETTINGS


log = logging.getLogger(__name__)


class AnalyzeRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=500)
    no_self_critique: bool = False


def _format_sse(event_type: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {body}\n\n".encode("utf-8")


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


async def _execute_run(run_id: str, raw_input: str, no_self_critique: bool) -> None:
    """Worker coroutine: pipes stream_analysis events into REGISTRY."""
    try:
        async for event in stream_analysis(raw_input, no_self_critique=no_self_critique):
            payload = event.to_dict()
            if event.type == "done":
                company_name = payload["payload"].get("company_name")
                slug = slugify(company_name or raw_input)
                payload["payload"]["slug"] = slug
            REGISTRY.publish(run_id, payload)
    except asyncio.CancelledError:
        REGISTRY.mark_cancelled(run_id)
        raise
    except Exception as exc:
        log.exception("run %s failed", run_id)
        REGISTRY.mark_failed(run_id, str(exc))


def _report_payload(slug: str) -> dict[str, Any] | None:
    safe_slug = slugify(slug)
    run_dir = Path(_settings().output_dir) / safe_slug
    report_json = run_dir / "report.json"
    if not report_json.exists():
        return None
    report_md = run_dir / "report.md"
    try:
        data = json.loads(report_json.read_text(encoding="utf-8"))
    except Exception:
        return None
    md = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
    return {"slug": safe_slug, "report": data, "markdown": md}


def _list_disk_runs() -> list[dict[str, Any]]:
    root = Path(_settings().output_dir)
    items: list[dict[str, Any]] = []
    if not root.exists():
        return items
    for child in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not child.is_dir():
            continue
        report_json = child / "report.json"
        if not report_json.exists():
            continue
        try:
            data = json.loads(report_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        score = (data.get("score") or {}) if isinstance(data, dict) else {}
        company = (data.get("company") or {}) if isinstance(data, dict) else {}
        items.append(
            {
                "slug": child.name,
                "generated_at": data.get("generated_at"),
                "company_name": company.get("name") or child.name,
                "tier": score.get("tier"),
                "overall_0_100": score.get("overall_0_100"),
                "raw_input": data.get("raw_input"),
                "modified_at": datetime.fromtimestamp(
                    child.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                "status": "completed",
            }
        )
    return items


def _registry_summary(rec: RunRecord) -> dict[str, Any]:
    return {
        "run_id": rec.id,
        "slug": rec.report_slug,
        "generated_at": None,
        "company_name": rec.input,
        "tier": None,
        "overall_0_100": None,
        "raw_input": rec.input,
        "modified_at": rec.updated_at,
        "status": rec.status,
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="Founding Team Analyzer",
        version="0.2.0",
        description="Multi-agent founding team analysis with live progress.",
    )
    s = _settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(s.cors_origins),
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        s = _settings()
        return {
            "status": "ok",
            "model_reasoning": s.model_reasoning,
            "model_extract": s.model_extract,
            "reasoning_effort": s.reasoning_effort,
            "max_llm_calls": s.max_llm_calls,
            "openai_configured": bool(s.openai_api_key),
            "tavily_configured": bool(s.tavily_api_key),
        }

    @app.get("/api/rubric")
    async def rubric() -> dict[str, Any]:
        # The weights on a report's CriterionScore come from the LLM's
        # structured output; compute_overall prefers the rubric weight for a
        # known key, so this endpoint is the authoritative house weighting.
        return {
            "criteria": [
                {
                    "key": c.key,
                    "label": c.label,
                    "weight": c.weight,
                    "anchorLow": c.anchor_0,
                    "anchorMid": c.anchor_3,
                    "anchorHigh": c.anchor_5,
                    "evidenceHint": c.required_evidence,
                }
                for c in RUBRIC
            ]
        }

    @app.post("/api/analyze")
    async def analyze(req: AnalyzeRequest) -> dict[str, Any]:
        s = _settings()
        if not s.openai_api_key or not s.tavily_api_key:
            raise HTTPException(status_code=503, detail="API keys not configured.")

        # Create the task and record atomically so there is no window
        # between create_task and attach_task where a cancel could miss
        # the task reference.
        run_id = str(uuid.uuid4())
        task = asyncio.create_task(
            _execute_run(run_id, req.input, req.no_self_critique)
        )
        record = REGISTRY.create(req.input, task=task, run_id=run_id)
        return {"run_id": record.id, "status": record.status}

    @app.get("/api/runs/{run_id}/events")
    async def stream_run_events(run_id: str) -> StreamingResponse:
        rec = REGISTRY.get(run_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")

        async def event_stream() -> AsyncIterator[bytes]:
            async for event in REGISTRY.subscribe(run_id):
                etype = str(event.get("type", "message"))
                yield _format_sse(etype, event)
                await asyncio.sleep(0)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.delete("/api/runs/{run_id}")
    async def delete_run(run_id: str) -> dict[str, Any]:
        if not _is_uuid(run_id):
            raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
        ok = REGISTRY.cancel(run_id)
        if not ok:
            rec = REGISTRY.get(run_id)
            if rec is None:
                raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
            return {"run_id": run_id, "status": rec.status, "cancelled": False}
        rec = REGISTRY.get(run_id)
        return {
            "run_id": run_id,
            "status": rec.status if rec else "cancelled",
            "cancelled": True,
        }

    @app.get("/api/runs")
    async def list_runs() -> dict[str, Any]:
        disk_items = _list_disk_runs()
        disk_slugs = {it["slug"] for it in disk_items}

        merged: list[dict[str, Any]] = []
        for rec in sorted(
            REGISTRY.list_all(), key=lambda r: r.updated_at, reverse=True
        ):
            if rec.report_slug and rec.report_slug in disk_slugs:
                continue
            merged.append(_registry_summary(rec))
        merged.extend(disk_items)
        return {"items": merged}

    @app.get("/api/runs/{run_id_or_slug}")
    async def get_run(run_id_or_slug: str) -> dict[str, Any]:
        if _is_uuid(run_id_or_slug):
            rec = REGISTRY.get(run_id_or_slug)
            if rec is None:
                raise HTTPException(
                    status_code=404, detail=f"Unknown run: {run_id_or_slug}"
                )
            body: dict[str, Any] = rec.to_summary()
            if rec.status == "completed" and rec.report_slug:
                payload = _report_payload(rec.report_slug)
                if payload is not None:
                    body["report"] = payload["report"]
                    body["markdown"] = payload["markdown"]
                    body["slug"] = payload["slug"]
            return body

        payload = _report_payload(run_id_or_slug)
        if payload is None:
            raise HTTPException(
                status_code=404, detail=f"Run not found: {run_id_or_slug}"
            )
        return payload

    return app


app = create_app()
