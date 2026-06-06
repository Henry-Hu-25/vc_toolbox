"""Concurrent-run isolation invariants tested at the registry / server level.

Ensures that two simultaneous runs do not share or corrupt each other's
state: events, warnings, cost, and status.

These tests use the FastAPI TestClient with stream_analysis monkey-patched
to deterministic fake events.
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


os.environ.setdefault("OPENAI_API_KEY", "test-openai")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily")


class FakeEvent:
    def __init__(self, type_: str, payload: dict) -> None:
        self.type = type_
        self._payload = payload

    def to_dict(self) -> dict:
        return {"type": self.type, "ts": "2026-01-01T00:00:00+00:00", "payload": dict(self._payload)}


# ---------------------------------------------------------------------------
# VAL-BE-024: Concurrent runs via the server do not cross-contaminate
#              events or warnings
# ---------------------------------------------------------------------------


def test_concurrent_post_runs_have_independent_events():
    """POST /api/analyze for two different inputs. Each run_id's
    event stream must contain only events for that run, no cross-talk."""
    from founding_team_analyzer import config as cfg
    from founding_team_analyzer import runs as runs_module
    from founding_team_analyzer import server as server_module
    from founding_team_analyzer import streaming_graph as sg

    cfg.SETTINGS = cfg.Settings.load()
    runs_module.REGISTRY = runs_module.RunRegistry()
    server_module.REGISTRY = runs_module.REGISTRY

    call_count = 0

    async def fake_stream_a(raw_input: str, *, no_self_critique: bool = False) -> AsyncIterator[FakeEvent]:
        nonlocal call_count
        call_count += 1
        is_run_a = raw_input == "Company A"
        warning_set = ["a1", "a2"] if is_run_a else ["b1", "b2", "b3"]
        yield FakeEvent("run_started", {"input": raw_input, "nodes": []})
        yield FakeEvent("node_started", {"node": "company_profiler", "label": "x"})
        yield FakeEvent(
            "node_finished",
            {"node": "company_profiler", "label": "x", "warnings": warning_set},
        )
        yield FakeEvent(
            "done",
            {
                "company_name": raw_input,
                "warnings": warning_set,
                "cost": {"llm_calls": 3 if is_run_a else 5, "tavily_searches": 1 if is_run_a else 2},
            },
        )

    with patch.object(sg, "stream_analysis", fake_stream_a), patch.object(
        server_module, "stream_analysis", fake_stream_a
    ):
        app = server_module.create_app()
        client = TestClient(app)

        # Submit two runs
        r_a = client.post("/api/analyze", json={"input": "Company A"})
        r_b = client.post("/api/analyze", json={"input": "Company B"})
        assert r_a.status_code == 200
        assert r_b.status_code == 200

        id_a = r_a.json()["run_id"]
        id_b = r_b.json()["run_id"]
        assert id_a != id_b

        # Wait for both runs to complete
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            s_a = client.get(f"/api/runs/{id_a}").json().get("status")
            s_b = client.get(f"/api/runs/{id_b}").json().get("status")
            if s_a in {"completed", "failed", "cancelled"} and s_b in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)

        # Verify each run completed with its own status
        detail_a = client.get(f"/api/runs/{id_a}").json()
        detail_b = client.get(f"/api/runs/{id_b}").json()
        assert detail_a["status"] == "completed", f"Run A status: {detail_a['status']}"
        assert detail_b["status"] == "completed", f"Run B status: {detail_b['status']}"

        # Verify events for each run contain only that run's data
        # (replay from the registry buffer)
        rec_a = runs_module.REGISTRY.get(id_a)
        rec_b = runs_module.REGISTRY.get(id_b)
        assert rec_a is not None and rec_b is not None

        # Check that run A's events don't contain run B data and vice versa
        for evt in rec_a.events:
            payload = evt.get("payload", {})
            # done event must have Company A warnings
            if evt.get("type") == "done":
                warnings = set(payload.get("warnings", []))
                assert warnings == {"a1", "a2"}, (
                    f"Run A done warnings should be {{a1, a2}}, got {warnings}"
                )
                cost = payload.get("cost", {})
                assert cost.get("llm_calls") == 3, f"Run A cost.llm_calls should be 3, got {cost.get('llm_calls')}"

        for evt in rec_b.events:
            payload = evt.get("payload", {})
            if evt.get("type") == "done":
                warnings = set(payload.get("warnings", []))
                assert warnings == {"b1", "b2", "b3"}, (
                    f"Run B done warnings should be {{b1, b2, b3}}, got {warnings}"
                )
                cost = payload.get("cost", {})
                assert cost.get("llm_calls") == 5, f"Run B cost.llm_calls should be 5, got {cost.get('llm_calls')}"


def test_concurrent_runs_independent_status_transitions():
    """Two runs in the registry must have independent status transitions.
    Cancelling one must not affect the other's status.

    We seed the registry directly (rather than via POST /api/analyze) so
    the runs' tasks live in the test thread, sidestepping TestClient's
    per-request event loop isolation.
    """
    from founding_team_analyzer import runs as runs_module

    registry = runs_module.RunRegistry()

    # Create two runs and mark them running
    rec_a = registry.create("Company A")
    rec_b = registry.create("Company B")

    registry.publish(rec_a.id, {"type": "run_started", "payload": {"input": "Company A"}})
    registry.publish(rec_b.id, {"type": "run_started", "payload": {"input": "Company B"}})

    assert rec_a.status == "running"
    assert rec_b.status == "running"

    # Cancel run A
    cancelled = registry.cancel(rec_a.id)
    assert cancelled is True, "Run A should be cancellable"
    assert rec_a.status == "cancelled", f"Run A should be cancelled, got {rec_a.status}"

    # Run B should still be running (not affected by cancelling A)
    assert rec_b.status == "running", (
        f"Run B should still be running after cancelling A, got {rec_b.status}"
    )

    # Complete run B
    registry.publish(rec_b.id, {"type": "done", "payload": {"company_name": "B", "warnings": []}})
    assert rec_b.status == "completed", (
        f"Run B should complete normally, got {rec_b.status}"
    )

    # Run A is still cancelled
    assert rec_a.status == "cancelled"


def test_concurrent_runs_event_buffers_are_independent():
    """Each run's event replay buffer in the registry must contain only
    that run's events.  Subscribing to one run must never yield events
    from another."""
    from founding_team_analyzer import runs as runs_module

    registry = runs_module.RunRegistry()

    # Create two runs
    rec_a = registry.create("Company A")
    rec_b = registry.create("Company B")

    # Publish distinct events for each run
    registry.publish(rec_a.id, {"type": "run_started", "payload": {"input": "Company A"}})
    registry.publish(rec_b.id, {"type": "run_started", "payload": {"input": "Company B"}})

    registry.publish(
        rec_a.id,
        {"type": "node_started", "payload": {"node": "company_profiler", "label": "x"}},
    )
    registry.publish(
        rec_b.id,
        {"type": "node_started", "payload": {"node": "company_profiler", "label": "x"}},
    )

    registry.publish(
        rec_a.id,
        {"type": "done", "payload": {"company_name": "A", "warnings": ["a1"], "cost": {"llm_calls": 3, "tavily_searches": 1}}},
    )
    registry.publish(
        rec_b.id,
        {"type": "done", "payload": {"company_name": "B", "warnings": ["b1", "b2"], "cost": {"llm_calls": 5, "tavily_searches": 2}}},
    )

    # Verify event counts
    assert len(rec_a.events) == 3, f"Run A should have 3 events, got {len(rec_a.events)}"
    assert len(rec_b.events) == 3, f"Run B should have 3 events, got {len(rec_b.events)}"

    # Verify run A's events are all for Company A
    for evt in rec_a.events:
        payload = evt.get("payload", {})
        if "input" in payload:
            assert payload["input"] == "Company A"
        if "company_name" in payload:
            assert payload["company_name"] == "A"
        if "warnings" in payload:
            assert set(payload["warnings"]) == {"a1"}

    # Verify run B's events are all for Company B
    for evt in rec_b.events:
        payload = evt.get("payload", {})
        if "input" in payload:
            assert payload["input"] == "Company B"
        if "company_name" in payload:
            assert payload["company_name"] == "B"
        if "warnings" in payload:
            assert set(payload["warnings"]) == {"b1", "b2"}


def test_concurrent_runs_subscribe_receives_only_own_events():
    """asyncio subscribe to a run must yield only that run's events,
    even when multiple runs are publishing concurrently."""
    from founding_team_analyzer import runs as runs_module

    registry = runs_module.RunRegistry()

    rec_a = registry.create("Company A")
    rec_b = registry.create("Company B")

    # Publish events for run A
    registry.publish(rec_a.id, {"type": "run_started", "payload": {"input": "A"}})
    registry.publish(rec_a.id, {"type": "done", "payload": {"warnings": ["a1"]}})

    # Publish events for run B
    registry.publish(rec_b.id, {"type": "run_started", "payload": {"input": "B"}})
    registry.publish(rec_b.id, {"type": "done", "payload": {"warnings": ["b1", "b2"]}})

    # Subscribe to run A and collect events
    async def _collect_a():
        events = []
        async for evt in registry.subscribe(rec_a.id):
            events.append(evt)
        return events

    loop = asyncio.new_event_loop()
    try:
        events_a = loop.run_until_complete(_collect_a())
    finally:
        loop.close()

    # Run A's subscriber should have received only run A's events
    assert len(events_a) == 2, f"Expected 2 events for run A, got {len(events_a)}"
    assert events_a[0]["payload"]["input"] == "A"
    assert events_a[1]["payload"]["warnings"] == ["a1"]


# ---------------------------------------------------------------------------
# Import for patching
# ---------------------------------------------------------------------------

from unittest.mock import patch
