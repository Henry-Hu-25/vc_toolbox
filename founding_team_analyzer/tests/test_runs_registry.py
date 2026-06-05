"""Tests for the in-process RunRegistry pub/sub semantics."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from founding_team_analyzer.runs import RunRegistry


async def _drain_until(
    it,
    predicate,
    limit: int = 50,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    async for evt in it:
        out.append(evt)
        if predicate(evt):
            break
        if len(out) >= limit:
            break
    return out


@pytest.mark.asyncio
async def test_create_and_get():
    reg = RunRegistry()
    rec = reg.create("Acme")
    assert rec.id and len(rec.id) >= 8
    assert rec.status == "pending"
    assert reg.get(rec.id) is rec


@pytest.mark.asyncio
async def test_publish_advances_status_and_buffers():
    reg = RunRegistry()
    rec = reg.create("Acme")
    reg.publish(rec.id, {"type": "run_started", "payload": {}})
    assert rec.status == "running"
    reg.publish(rec.id, {"type": "node_started", "payload": {"node": "x"}})
    reg.publish(rec.id, {"type": "done", "payload": {"slug": "acme"}})
    assert rec.status == "completed"
    assert rec.report_slug == "acme"
    assert len(rec.events) == 3


@pytest.mark.asyncio
async def test_subscribe_replays_then_streams_live():
    reg = RunRegistry()
    rec = reg.create("Acme")
    reg.publish(rec.id, {"type": "run_started", "payload": {}})
    reg.publish(rec.id, {"type": "node_started", "payload": {"node": "a"}})

    received: list[dict[str, Any]] = []

    async def consumer():
        async for evt in reg.subscribe(rec.id):
            received.append(evt)
            if evt.get("type") == "done":
                return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.01)
    reg.publish(rec.id, {"type": "node_finished", "payload": {"node": "a"}})
    reg.publish(rec.id, {"type": "done", "payload": {"slug": "acme"}})
    await asyncio.wait_for(task, timeout=1.0)

    types = [e["type"] for e in received]
    assert types == ["run_started", "node_started", "node_finished", "done"]


@pytest.mark.asyncio
async def test_subscribe_fanout_to_multiple_consumers():
    reg = RunRegistry()
    rec = reg.create("Acme")
    reg.publish(rec.id, {"type": "run_started", "payload": {}})

    a: list[dict[str, Any]] = []
    b: list[dict[str, Any]] = []

    async def consume(target: list[dict[str, Any]]):
        async for evt in reg.subscribe(rec.id):
            target.append(evt)
            if evt.get("type") == "done":
                return

    ta = asyncio.create_task(consume(a))
    tb = asyncio.create_task(consume(b))
    await asyncio.sleep(0.01)
    reg.publish(rec.id, {"type": "node_finished", "payload": {"node": "x"}})
    reg.publish(rec.id, {"type": "done", "payload": {"slug": "acme"}})
    await asyncio.wait_for(asyncio.gather(ta, tb), timeout=1.0)
    assert [e["type"] for e in a] == ["run_started", "node_finished", "done"]
    assert [e["type"] for e in b] == ["run_started", "node_finished", "done"]


@pytest.mark.asyncio
async def test_subscribe_after_terminal_returns_buffer_and_stops():
    reg = RunRegistry()
    rec = reg.create("Acme")
    reg.publish(rec.id, {"type": "run_started", "payload": {}})
    reg.publish(rec.id, {"type": "done", "payload": {"slug": "acme"}})

    seen: list[dict[str, Any]] = []
    async for evt in reg.subscribe(rec.id):
        seen.append(evt)
    assert [e["type"] for e in seen] == ["run_started", "done"]


@pytest.mark.asyncio
async def test_mark_failed_terminates_and_pushes_error():
    reg = RunRegistry()
    rec = reg.create("Acme")
    reg.publish(rec.id, {"type": "run_started", "payload": {}})

    received: list[dict[str, Any]] = []

    async def consumer():
        async for evt in reg.subscribe(rec.id):
            received.append(evt)
            if evt.get("type") == "error":
                return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.01)
    reg.mark_failed(rec.id, "boom")
    await asyncio.wait_for(task, timeout=1.0)
    assert rec.status == "failed"
    assert rec.error == "boom"
    assert received[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_cancel_marks_cancelled_and_cancels_task():
    reg = RunRegistry()
    rec = reg.create("Acme")

    started = asyncio.Event()

    async def worker():
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(worker())
    reg.attach_task(rec.id, task)
    await started.wait()
    ok = await reg.cancel(rec.id)
    assert ok is True
    assert rec.status == "cancelled"
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_cancel_unknown_returns_false():
    reg = RunRegistry()
    assert await reg.cancel("nope") is False


@pytest.mark.asyncio
async def test_list_running_excludes_terminal():
    reg = RunRegistry()
    a = reg.create("A")
    b = reg.create("B")
    reg.publish(a.id, {"type": "done", "payload": {"slug": "a"}})
    running = reg.list_running()
    ids = {r.id for r in running}
    assert b.id in ids
    assert a.id not in ids
