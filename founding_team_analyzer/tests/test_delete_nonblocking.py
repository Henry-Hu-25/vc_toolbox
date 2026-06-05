"""Tests for DELETE /api/runs/{id} non-blocking behavior (F-BE-007).

Verifies:
- DELETE returns immediately even when the worker task is mid-flight
- The run is marked cancelled before the task actually stops
- Cancel-before-await race is safe: no window between create_task and attach_task
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-openai")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeEvent:
    def __init__(self, type_: str, payload: dict) -> None:
        self.type = type_
        self._payload = payload

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "ts": "2026-01-01T00:00:00+00:00",
            "payload": dict(self._payload),
        }


@pytest.fixture()
def app_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FTA_OUTPUT_DIR", str(tmp_path))
    from founding_team_analyzer import config as cfg

    cfg.SETTINGS = cfg.Settings.load()

    from founding_team_analyzer import runs as runs_module
    from founding_team_analyzer import server as server_module
    from founding_team_analyzer import streaming_graph as sg

    runs_module.REGISTRY = runs_module.RunRegistry()
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


# ---------------------------------------------------------------------------
# VAL-BE-013: DELETE returns within 1s even when the task is mid-LLM call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_returns_within_1s_with_long_running_task():
    """Cancel() must return immediately without awaiting the worker task."""
    from founding_team_analyzer.runs import RunRegistry

    reg = RunRegistry()
    rec = reg.create("Acme")

    started = asyncio.Event()

    async def slow_worker():
        started.set()
        # Simulate a long in-flight LLM call — sleeps for 30s
        await asyncio.sleep(30)

    task = asyncio.create_task(slow_worker())
    reg.attach_task(rec.id, task)
    await started.wait()

    t0 = time.monotonic()
    # cancel() must return within 1 second
    ok = reg.cancel(rec.id)
    elapsed = time.monotonic() - t0

    assert ok is True, "cancel should return True for an in-flight run"
    assert elapsed < 1.0, f"cancel took {elapsed:.2f}s, should be < 1s"
    assert rec.status == "cancelled", "run should be marked cancelled immediately"

    # Clean up: cancel the task so it doesn't linger
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass


@pytest.mark.asyncio
async def test_delete_nonblocking_via_testclient(app_env):
    """DELETE /api/runs/{id} returns quickly even with a long-running task.

    We seed the registry directly with a long-running task (bypassing
    TestClient's per-request event loop issue) and then hit DELETE.
    """
    client, _, registry = app_env
    rec = registry.create("Acme")

    started = asyncio.Event()

    async def slow_worker():
        started.set()
        await asyncio.sleep(30)

    # Need to create the task in the test's event loop, not TestClient's
    task = asyncio.create_task(slow_worker())
    registry.attach_task(rec.id, task)
    await started.wait()

    t0 = time.monotonic()
    r = client.delete(f"/api/runs/{rec.id}")
    elapsed = time.monotonic() - t0

    assert r.status_code == 200
    body = r.json()
    assert body["cancelled"] is True
    assert elapsed < 1.0, f"DELETE took {elapsed:.2f}s, should be < 1s"

    # Clean up
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass


# ---------------------------------------------------------------------------
# VAL-BE-021: Cancel-before-await race is safe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_immediately_after_create_stops_task():
    """Cancel arriving in the same event-loop tick as run creation
    must stop the task — no window between create_task and attach_task."""
    from founding_team_analyzer.runs import RunRegistry

    reg = RunRegistry()

    # The task records whether it got past the first await.
    worker_ran = asyncio.Event()

    async def worker():
        worker_ran.set()
        await asyncio.sleep(10)

    # Simulate the new atomic create-with-task pattern.
    task = asyncio.create_task(worker())
    rec = reg.create("Acme", task=task)

    # Cancel immediately, before any await that would yield control.
    ok = reg.cancel(rec.id)

    assert ok is True
    assert rec.status == "cancelled"

    # Now yield control so the task has a chance to process CancelledError.
    await asyncio.sleep(0.05)

    # The worker should NOT have set its event — it was cancelled
    # before it could run.
    assert not worker_ran.is_set(), (
        "Task should have been cancelled before executing any work"
    )
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_cancel_before_attach_task_still_cancels():
    """Even with old-style create + attach_task, cancel called before
    attach_task should still cancel the task once it is attached.

    This tests that the registry properly handles the race window.
    """
    from founding_team_analyzer.runs import RunRegistry

    reg = RunRegistry()
    rec = reg.create("Acme")

    worker_ran = asyncio.Event()

    async def worker():
        worker_ran.set()
        await asyncio.sleep(10)

    # Cancel before attaching the task — status should be cancelled.
    ok = reg.cancel(rec.id)
    assert ok is True
    assert rec.status == "cancelled"

    # Now attach a task — it should be cancelled immediately.
    task = asyncio.create_task(worker())
    reg.attach_task(rec.id, task)

    # Yield control.
    await asyncio.sleep(0.05)

    # The worker should NOT have run — the task was attached to
    # an already-cancelled record and should be cancelled.
    assert not worker_ran.is_set(), (
        "Task attached to a cancelled run should be cancelled immediately"
    )
    assert task.cancelled() or task.done()


# ---------------------------------------------------------------------------
# Run is marked cancelled asynchronously after handler returns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_marked_cancelled_immediately_on_cancel():
    """When cancel() returns, the run record already shows cancelled status."""
    from founding_team_analyzer.runs import RunRegistry

    reg = RunRegistry()
    rec = reg.create("Acme")

    async def slow_worker():
        await asyncio.sleep(30)

    task = asyncio.create_task(slow_worker())
    reg.attach_task(rec.id, task)

    ok = reg.cancel(rec.id)
    assert ok is True
    # Status is cancelled immediately — no need to wait for task to finish.
    assert rec.status == "cancelled"

    # The task may still be in the process of winding down.
    # After a brief wait, it should be done.
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass


@pytest.mark.asyncio
async def test_cancel_publishes_cancelled_event():
    """cancel() should publish an error event with the cancellation message."""
    from founding_team_analyzer.runs import RunRegistry

    reg = RunRegistry()
    rec = reg.create("Acme")

    events: list[dict] = []

    async def collector():
        async for evt in reg.subscribe(rec.id):
            events.append(evt)
            if evt.get("type") == "error":
                return

    task = asyncio.create_task(collector())
    await asyncio.sleep(0.01)

    worker_task = asyncio.create_task(asyncio.sleep(30))
    reg.attach_task(rec.id, worker_task)

    reg.cancel(rec.id)
    await asyncio.sleep(0.05)

    assert any(
        e.get("type") == "error"
        and "cancel" in (e.get("payload", {}).get("message") or "").lower()
        for e in events
    ), "Expected an error event with cancellation message"

    # Cleanup
    worker_task.cancel()
    try:
        await asyncio.wait_for(worker_task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
