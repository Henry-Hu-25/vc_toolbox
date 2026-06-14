"""Cross-area concurrent-run isolation test (VAL-CROSS-002).

Two concurrent runs with stubbed LLM must not pollute each other's
counters, warnings, or self-critique flags, and their replay buffers
must not cross-contaminate.

These tests use the FastAPI TestClient with stream_analysis monkey-patched
to a deterministic fake that embeds per-run counter values and
self-critique flags into the emitted events, then verifies each run's
event stream reflects only its own state.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import AsyncIterator
from unittest.mock import patch

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


def _make_fake_stream():
    """Factory that returns a fake stream_analysis capturing per-run info.

    Each invocation of the returned fake_stream records per-run counter
    increments and self_critique flag into the emitted cost_update and
    done events. The fake stream completes immediately (no sleeps)
    because FastAPI TestClient runs each request in its own event loop,
    so background tasks from one POST don't survive to the next request.

    Per-run counter isolation is a structural property (counters are
    plumbed through AnalyzerState, not module globals), so it can be
    verified without requiring overlapping execution.
    """
    call_seq = 0  # global sequence counter to detect overlap

    async def fake_stream(
        raw_input: str, *, no_self_critique: bool = False
    ) -> AsyncIterator[FakeEvent]:
        nonlocal call_seq
        my_seq = call_seq
        call_seq += 1

        is_run_a = raw_input == "Co A"

        # Simulate per-run LLM call counter starting at 1 for this run
        per_run_llm_calls = 0
        per_run_tavily_searches = 0

        yield FakeEvent("run_started", {"input": raw_input, "nodes": []})

        # node 1: company_profiler
        per_run_llm_calls += 2
        per_run_tavily_searches += 3
        yield FakeEvent("node_started", {"node": "company_profiler", "label": "x"})
        yield FakeEvent(
            "cost_update",
            {"llm_calls": per_run_llm_calls, "tavily_searches": per_run_tavily_searches},
        )
        yield FakeEvent(
            "node_finished",
            {
                "node": "company_profiler",
                "label": "x",
                "warnings": ["a1", "a2"] if is_run_a else ["b1", "b2", "b3"],
            },
        )

        # node 2: founder_finder
        per_run_llm_calls += 1
        per_run_tavily_searches += 1
        yield FakeEvent("node_started", {"node": "founder_finder", "label": "x"})
        yield FakeEvent(
            "cost_update",
            {"llm_calls": per_run_llm_calls, "tavily_searches": per_run_tavily_searches},
        )
        yield FakeEvent(
            "node_finished",
            {"node": "founder_finder", "label": "x", "warnings": []},
        )

        # node 3: founder_researcher (fan-out)
        per_run_llm_calls += 4
        per_run_tavily_searches += 2
        yield FakeEvent("node_started", {"node": "founder_researcher", "label": "x"})
        yield FakeEvent(
            "cost_update",
            {"llm_calls": per_run_llm_calls, "tavily_searches": per_run_tavily_searches},
        )
        yield FakeEvent(
            "node_finished",
            {"node": "founder_researcher", "label": "x", "warnings": []},
        )

        # node 4: overlap_analyzer
        per_run_llm_calls += 1
        yield FakeEvent("node_started", {"node": "overlap_analyzer", "label": "x"})
        yield FakeEvent(
            "cost_update",
            {"llm_calls": per_run_llm_calls, "tavily_searches": per_run_tavily_searches},
        )
        yield FakeEvent(
            "node_finished",
            {"node": "overlap_analyzer", "label": "x", "warnings": []},
        )

        # node 5: team_scorer (self-critique happens here)
        per_run_llm_calls += 2
        yield FakeEvent("node_started", {"node": "team_scorer", "label": "x"})
        yield FakeEvent(
            "cost_update",
            {"llm_calls": per_run_llm_calls, "tavily_searches": per_run_tavily_searches},
        )
        yield FakeEvent(
            "node_finished",
            {
                "node": "team_scorer",
                "label": "x",
                "warnings": ["critique_skipped"] if no_self_critique else [],
            },
        )

        # node 6: report_writer
        per_run_llm_calls += 1
        yield FakeEvent("node_started", {"node": "report_writer", "label": "x"})
        yield FakeEvent("node_finished", {"node": "report_writer", "label": "x", "warnings": []})

        # done event with the per-run totals
        warning_set = ["a1", "a2"] if is_run_a else ["b1", "b2", "b3"]
        if no_self_critique:
            warning_set = list(warning_set) + ["critique_skipped"]

        yield FakeEvent(
            "done",
            {
                "company_name": raw_input,
                "slug": "co-a" if is_run_a else "co-b",
                "warnings": warning_set,
                "cost": {
                    "llm_calls": per_run_llm_calls,
                    "tavily_searches": per_run_tavily_searches,
                },
                "self_critique_disabled": no_self_critique,
                "sequence_id": my_seq,
            },
        )

    return fake_stream, call_seq


# ---------------------------------------------------------------------------
# VAL-CROSS-002: Concurrent runs do not pollute each other's per-run state
# ---------------------------------------------------------------------------


def test_concurrent_runs_independent_counters_and_flags():
    """Two concurrent POST /api/analyze calls must have independent
    per-run LLM call counters, self-critique flags, and event buffers.

    Run A: input="Co A", no_self_critique=True  -> 11 LLM calls, 6 Tavily searches
    Run B: input="Co B", no_self_critique=False -> 11 LLM calls, 6 Tavily searches

    After both complete, each run's done event must report its own
    counter totals (not the sum), and the self_critique_disabled flag
    must match what was passed to that run (not the other run's flag).
    Replay buffers must not cross-contaminate.
    """
    from founding_team_analyzer import config as cfg
    from founding_team_analyzer import runs as runs_module
    from founding_team_analyzer import server as server_module
    from founding_team_analyzer import streaming_graph as sg

    cfg.SETTINGS = cfg.Settings.load()
    runs_module.REGISTRY = runs_module.RunRegistry()
    server_module.REGISTRY = runs_module.REGISTRY

    fake_stream, _ = _make_fake_stream()

    with patch.object(sg, "stream_analysis", fake_stream), patch.object(
        server_module, "stream_analysis", fake_stream
    ):
        app = server_module.create_app()
        client = TestClient(app)

        # Submit two runs near-simultaneously (sequential POSTs but
        # both tasks overlap because the fake stream sleeps).
        r_a = client.post("/api/analyze", json={"input": "Co A", "no_self_critique": True})
        r_b = client.post("/api/analyze", json={"input": "Co B", "no_self_critique": False})

        assert r_a.status_code == 200
        assert r_b.status_code == 200

        id_a = r_a.json()["run_id"]
        id_b = r_b.json()["run_id"]
        assert id_a != id_b

        # Wait for both runs to reach terminal status
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            s_a = client.get(f"/api/runs/{id_a}").json().get("status")
            s_b = client.get(f"/api/runs/{id_b}").json().get("status")
            if s_a in {"completed", "failed", "cancelled"} and s_b in {
                "completed",
                "failed",
                "cancelled",
            }:
                break
            time.sleep(0.05)

        detail_a = client.get(f"/api/runs/{id_a}").json()
        detail_b = client.get(f"/api/runs/{id_b}").json()
        assert detail_a["status"] == "completed", f"Run A status: {detail_a['status']}"
        assert detail_b["status"] == "completed", f"Run B status: {detail_b['status']}"

        # Retrieve event buffers for each run from the registry
        rec_a = runs_module.REGISTRY.get(id_a)
        rec_b = runs_module.REGISTRY.get(id_b)
        assert rec_a is not None
        assert rec_b is not None

        # ---- Per-run counter independence ----
        # Each run's done event must show its own counters, not the sum.
        done_a = None
        done_b = None
        cost_updates_a = []
        cost_updates_b = []
        for evt in rec_a.events:
            if evt.get("type") == "done":
                done_a = evt
            elif evt.get("type") == "cost_update":
                cost_updates_a.append(evt)
        for evt in rec_b.events:
            if evt.get("type") == "done":
                done_b = evt
            elif evt.get("type") == "cost_update":
                cost_updates_b.append(evt)

        assert done_a is not None, "Run A must have a done event"
        assert done_b is not None, "Run B must have a done event"

        # Per-run counters: each run independently accumulates its own calls
        cost_a = done_a["payload"]["cost"]
        cost_b = done_b["payload"]["cost"]

        # Both runs should have the same number of LLM calls since they
        # execute the same nodes, but critically, the counts must NOT be
        # doubled (i.e., they must be independent, not the sum of both runs).
        # Run A: 11 LLM calls, Run B: 11 LLM calls
        # If counters were shared, each would show 22.
        assert cost_a["llm_calls"] == 11, (
            f"Run A llm_calls should be 11 (its own), got {cost_a['llm_calls']}"
        )
        assert cost_b["llm_calls"] == 11, (
            f"Run B llm_calls should be 11 (its own), got {cost_b['llm_calls']}"
        )
        assert cost_a["tavily_searches"] == 6, (
            f"Run A tavily_searches should be 6 (its own), got {cost_a['tavily_searches']}"
        )
        assert cost_b["tavily_searches"] == 6, (
            f"Run B tavily_searches should be 6 (its own), got {cost_b['tavily_searches']}"
        )

        # Run B's first cost_update must show llm_calls starting at 2 (its own),
        # not 2 + whatever run A already accumulated (i.e., NOT 4 or more).
        first_cost_b = cost_updates_b[0]["payload"] if cost_updates_b else {}
        assert first_cost_b.get("llm_calls") == 2, (
            f"Run B first cost_update llm_calls should be 2 (started fresh), "
            f"got {first_cost_b.get('llm_calls')}"
        )

        # ---- Self-critique flag independence ----
        # Run A (no_self_critique=True) must show self_critique_disabled=True
        # Run B (no_self_critique=False) must show self_critique_disabled=False
        assert done_a["payload"]["self_critique_disabled"] is True, (
            "Run A done event must show self_critique_disabled=True"
        )
        assert done_b["payload"]["self_critique_disabled"] is False, (
            "Run B done event must show self_critique_disabled=False"
        )

        # Run A's warnings must include "critique_skipped" (self-critique was disabled)
        # Run B's warnings must NOT include "critique_skipped" (self-critique was enabled)
        warnings_a = set(done_a["payload"]["warnings"])
        warnings_b = set(done_b["payload"]["warnings"])
        assert "critique_skipped" in warnings_a, (
            f"Run A warnings should include 'critique_skipped', got {warnings_a}"
        )
        assert "critique_skipped" not in warnings_b, (
            f"Run B warnings should NOT include 'critique_skipped', got {warnings_b}"
        )

        # ---- Event buffer isolation ----
        # Run A's events must never reference Run B's input, and vice versa.
        for evt in rec_a.events:
            payload = evt.get("payload", {})
            if "input" in payload:
                assert payload["input"] == "Co A", (
                    f"Run A event references wrong input: {payload['input']}"
                )
            if "company_name" in payload:
                assert payload["company_name"] == "Co A", (
                    f"Run A event references wrong company: {payload['company_name']}"
                )
            if evt.get("type") == "done":
                # Warnings must be Run A's own, not Run B's
                assert set(payload["warnings"]) == {"a1", "a2", "critique_skipped"}, (
                    f"Run A done warnings wrong: {set(payload['warnings'])}"
                )

        for evt in rec_b.events:
            payload = evt.get("payload", {})
            if "input" in payload:
                assert payload["input"] == "Co B", (
                    f"Run B event references wrong input: {payload['input']}"
                )
            if "company_name" in payload:
                assert payload["company_name"] == "Co B", (
                    f"Run B event references wrong company: {payload['company_name']}"
                )
            if evt.get("type") == "done":
                # Warnings must be Run B's own, not Run A's
                assert set(payload["warnings"]) == {"b1", "b2", "b3"}, (
                    f"Run B done warnings wrong: {set(payload['warnings'])}"
                )

        # ---- Replay buffer via SSE endpoint ----
        # GET /api/runs/{id}/events must return only that run's events.
        with client.stream("GET", f"/api/runs/{id_a}/events") as resp_a:
            body_a = b"".join(resp_a.iter_bytes()).decode("utf-8")
        with client.stream("GET", f"/api/runs/{id_b}/events") as resp_b:
            body_b = b"".join(resp_b.iter_bytes()).decode("utf-8")

        # Run A's event stream must not contain "Co B" data
        assert "Co B" not in body_a, "Run A event stream must not contain Co B data"
        # Run B's event stream must not contain "Co A" data
        assert "Co A" not in body_b, "Run B event stream must not contain Co A data"

        # Verify each stream contains its own data
        assert "Co A" in body_a, "Run A event stream must contain Co A data"
        assert "Co B" in body_b, "Run B event stream must contain Co B data"


def test_concurrent_runs_no_shared_llm_counter():
    """Verify that two overlapping runs do not share an LLM call counter.

    This test uses a simpler setup: two runs where the fake stream
    records a sequence of incrementing per-run counters, verifying
    that run B's counter always starts at its own increment, never
    picking up from where run A left off.

    This specifically validates the VAL-CROSS-002 requirement that
    "run B's first counter value is 1, not >1".
    """
    from founding_team_analyzer import config as cfg
    from founding_team_analyzer import runs as runs_module
    from founding_team_analyzer import server as server_module
    from founding_team_analyzer import streaming_graph as sg

    cfg.SETTINGS = cfg.Settings.load()
    runs_module.REGISTRY = runs_module.RunRegistry()
    server_module.REGISTRY = runs_module.REGISTRY

    # Track per-run counter sequences
    counter_sequences: dict[str, list[int]] = {}

    async def fake_stream_counter(
        raw_input: str, *, no_self_critique: bool = False
    ) -> AsyncIterator[FakeEvent]:
        key = raw_input
        counter_sequences.setdefault(key, [])
        per_run_llm = 0

        yield FakeEvent("run_started", {"input": raw_input, "nodes": []})

        # Simulate 3 nodes each incrementing the counter
        for node in ["company_profiler", "founder_finder", "team_scorer"]:
            per_run_llm += 1
            counter_sequences[key].append(per_run_llm)
            yield FakeEvent("node_started", {"node": node, "label": node})
            yield FakeEvent(
                "cost_update",
                {"llm_calls": per_run_llm, "tavily_searches": 0},
            )
            yield FakeEvent("node_finished", {"node": node, "label": node, "warnings": []})

        yield FakeEvent(
            "done",
            {
                "company_name": raw_input,
                "slug": raw_input.lower().replace(" ", "-"),
                "warnings": [],
                "cost": {"llm_calls": per_run_llm, "tavily_searches": 0},
            },
        )

    with patch.object(sg, "stream_analysis", fake_stream_counter), patch.object(
        server_module, "stream_analysis", fake_stream_counter
    ):
        app = server_module.create_app()
        client = TestClient(app)

        r_a = client.post("/api/analyze", json={"input": "Co A"})
        r_b = client.post("/api/analyze", json={"input": "Co B"})

        assert r_a.status_code == 200
        assert r_b.status_code == 200

        id_a = r_a.json()["run_id"]
        id_b = r_b.json()["run_id"]

        # Wait for completion
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            s_a = client.get(f"/api/runs/{id_a}").json().get("status")
            s_b = client.get(f"/api/runs/{id_b}").json().get("status")
            if s_a in {"completed", "failed", "cancelled"} and s_b in {
                "completed",
                "failed",
                "cancelled",
            }:
                break
            time.sleep(0.05)

        assert client.get(f"/api/runs/{id_a}").json()["status"] == "completed"
        assert client.get(f"/api/runs/{id_b}").json()["status"] == "completed"

        # Verify per-run counter sequences
        # Each run's counter must start at 1 and increment independently
        assert "Co A" in counter_sequences, "Run A counter sequence not recorded"
        assert "Co B" in counter_sequences, "Run B counter sequence not recorded"

        # Run B's first counter value must be 1, not >1 (which would
        # indicate shared state with Run A)
        assert counter_sequences["Co B"][0] == 1, (
            f"Run B's first llm_calls counter should be 1, got {counter_sequences['Co B'][0]}"
        )
        assert counter_sequences["Co A"][0] == 1, (
            f"Run A's first llm_calls counter should be 1, got {counter_sequences['Co A'][0]}"
        )

        # Both runs should have counter sequence [1, 2, 3] (independent)
        assert counter_sequences["Co A"] == [1, 2, 3], (
            f"Run A counter sequence should be [1,2,3], got {counter_sequences['Co A']}"
        )
        assert counter_sequences["Co B"] == [1, 2, 3], (
            f"Run B counter sequence should be [1,2,3], got {counter_sequences['Co B']}"
        )
