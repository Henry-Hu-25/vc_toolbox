"""Endpoint tests for the registry-backed /api/runs surface.

These tests stub `stream_analysis` so they don't actually call OpenAI/Tavily.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient


def _wait_terminal_http(client: TestClient, run_id: str, timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body.get("status") in {"completed", "failed", "cancelled"}:
            return body
        time.sleep(0.02)
    return client.get(f"/api/runs/{run_id}").json()

os.environ.setdefault("OPENAI_API_KEY", "test-openai")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily")


class FakeEvent:
    def __init__(self, type_: str, payload: dict) -> None:
        self.type = type_
        self._payload = payload

    def to_dict(self) -> dict:
        return {"type": self.type, "ts": "2026-01-01T00:00:00+00:00", "payload": dict(self._payload)}


@pytest.fixture()
def app_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FTA_OUTPUT_DIR", str(tmp_path))
    from founding_team_analyzer import config as cfg

    cfg.SETTINGS = cfg.Settings.load()

    from founding_team_analyzer import runs as runs_module

    runs_module.REGISTRY = runs_module.RunRegistry()

    from founding_team_analyzer import server as server_module
    from founding_team_analyzer import streaming_graph as sg

    server_module.REGISTRY = runs_module.REGISTRY

    async def fake_stream(raw_input: str, *, no_self_critique: bool = False) -> AsyncIterator[FakeEvent]:
        yield FakeEvent("run_started", {"input": raw_input, "nodes": []})
        yield FakeEvent("node_started", {"node": "company_profiler", "label": "x"})
        yield FakeEvent("node_finished", {"node": "company_profiler", "label": "x", "warnings": []})
        yield FakeEvent("done", {"company_name": "Acme", "warnings": []})

    monkeypatch.setattr(sg, "stream_analysis", fake_stream)
    monkeypatch.setattr(server_module, "stream_analysis", fake_stream)

    app = server_module.create_app()
    client = TestClient(app)
    return client, tmp_path, runs_module.REGISTRY


def test_post_analyze_returns_run_id(app_env):
    client, _, registry = app_env
    r = client.post("/api/analyze", json={"input": "Acme"})
    assert r.status_code == 200
    body = r.json()
    assert "run_id" in body
    assert body["status"] in ("pending", "running")

    final = _wait_terminal_http(client, body["run_id"])
    assert final["status"] == "completed"
    rec = registry.get(body["run_id"])
    assert rec is not None and rec.status == "completed"


def test_get_run_returns_status_and_report(app_env, tmp_path: Path):
    client, _, _ = app_env
    run_id = client.post("/api/analyze", json={"input": "Acme"}).json()["run_id"]
    _wait_terminal_http(client, run_id)

    # Without an on-disk report we just get summary.
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["run_id"] == run_id
    assert detail["status"] == "completed"
    assert detail["report_slug"] == "acme"

    # Write an on-disk report and confirm /api/runs/{slug} works too.
    run_dir = tmp_path / "acme"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "raw_input": "Acme",
                "company": {"name": "Acme"},
                "founders": [],
                "overlaps": None,
                "score": {
                    "criteria": [],
                    "overall_0_100": 80.0,
                    "tier": "Strong",
                    "top_strengths": [],
                    "top_risks": [],
                    "open_questions": [],
                },
                "warnings": [],
                "cost": None,
            }
        )
    )
    (run_dir / "report.md").write_text("# Acme")
    by_slug = client.get("/api/runs/acme").json()
    assert by_slug["slug"] == "acme"
    assert by_slug["report"]["company"]["name"] == "Acme"


def test_events_stream_replays_buffered_events(app_env):
    client, _, _ = app_env
    run_id = client.post("/api/analyze", json={"input": "Acme"}).json()["run_id"]
    _wait_terminal_http(client, run_id)

    with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    # We expect at least run_started, node_started, node_finished, done.
    assert "event: run_started" in body
    assert "event: done" in body


def test_list_runs_merges_inflight_and_disk(app_env, tmp_path: Path):
    client, _, registry = app_env
    # On-disk run.
    run_dir = tmp_path / "acme"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "raw_input": "Acme",
                "company": {"name": "Acme"},
                "founders": [],
                "overlaps": None,
                "score": {
                    "criteria": [],
                    "overall_0_100": 80.0,
                    "tier": "Strong",
                    "top_strengths": [],
                    "top_risks": [],
                    "open_questions": [],
                },
                "warnings": [],
                "cost": None,
            }
        )
    )
    # In-flight (non-terminal) registry-only run.
    rec = registry.create("Beta Inc")
    registry.publish(rec.id, {"type": "run_started", "payload": {}})

    body = client.get("/api/runs").json()
    items = body["items"]
    slugs = [it.get("slug") for it in items]
    statuses = {it["status"] for it in items}
    assert "acme" in slugs
    assert "running" in statuses
    assert any(it.get("run_id") == rec.id for it in items)


def test_delete_endpoint_routes_to_registry(app_env):
    """DELETE on a registry-resident, non-terminal run cancels it.

    We seed the registry directly (rather than via POST /api/analyze) so the
    run's task lives in the test thread, sidestepping TestClient's
    per-request event loop.
    """
    client, _, registry = app_env
    rec = registry.create("Beta")
    registry.publish(rec.id, {"type": "run_started", "payload": {}})
    assert rec.status == "running"

    r = client.delete(f"/api/runs/{rec.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == rec.id
    assert body["cancelled"] is True
    assert registry.get(rec.id).status == "cancelled"


def test_delete_unknown_run_returns_404(app_env):
    client, _, _ = app_env
    r = client.delete("/api/runs/00000000-0000-4000-8000-000000000000")
    assert r.status_code == 404 or r.json().get("cancelled") is False
