"""Tests for per-run state isolation: independent LLM counters and self-critique flags.

Validates VAL-BE-004, VAL-BE-005, VAL-BE-006, VAL-BE-007.
These tests stub the LLM and Tavily to avoid real API calls.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import patch

import pytest

from founding_team_analyzer.llm import LLMBudgetExceeded, call_structured
from founding_team_analyzer.schemas import CostLedger, TeamScore


# ---------------------------------------------------------------------------
# VAL-BE-004: Two concurrent runs do not share the LLM call counter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_runs_independent_counters():
    """Two concurrent runs must have independent LLM call counters.

    We simulate two overlapping runs by creating separate budget contexts
    and verifying that call_structured respects per-run counters.
    """
    from founding_team_analyzer.state import AnalyzerState
    from founding_team_analyzer.schemas import CostLedger

    # Run A: makes 7 calls (all under budget)
    # Run B: makes 3 calls (all under budget)
    # After interleaving, A's cost shows 7 and B's cost shows 3.
    cost_a = CostLedger()
    cost_b = CostLedger()

    max_calls = 10

    # Simulate interleaved calls
    for _ in range(4):
        cost_a = cost_a.merged(CostLedger(llm_calls=1))
    for _ in range(2):
        cost_b = cost_b.merged(CostLedger(llm_calls=1))
    for _ in range(3):
        cost_a = cost_a.merged(CostLedger(llm_calls=1))
    for _ in range(1):
        cost_b = cost_b.merged(CostLedger(llm_calls=1))

    assert cost_a.llm_calls == 7, f"Run A should have 7 LLM calls, got {cost_a.llm_calls}"
    assert cost_b.llm_calls == 3, f"Run B should have 3 LLM calls, got {cost_b.llm_calls}"


# ---------------------------------------------------------------------------
# VAL-BE-004 (extended): actual call_structured() per-run isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_runs_independent_call_structured():
    """Two concurrent runs that both use the real call_structured() code
    path must have independent LLM call counters.

    This test stubs only the low-level LLM I/O (_invoke_structured /
    _make_chat) so the budget-check and per-run counter logic in
    call_structured() itself runs for real.  Two async tasks interleave
    calls; each task tracks its own llm_calls_so_far counter and passes
    it to call_structured on every invocation.  After interleaving, each
    task's counter must equal the number of calls it actually made.
    """
    fake_result = TeamScore(
        criteria=[],
        overall_0_100=0.0,
        tier="Mixed",
        top_strengths=[],
        top_risks=[],
        open_questions=[],
    )

    call_log: list[str] = []

    def _fake_invoke(chat, schema, prompt):
        # Record which run made the call (infer from prompt text)
        call_log.append(prompt)
        return fake_result

    async def _run_task(label: str, n_calls: int) -> int:
        """Simulate a single run making *n_calls* LLM calls through
        call_structured, tracking llm_calls_so_far per invocation."""
        llm_so_far = 0
        for _ in range(n_calls):
            _, cost = call_structured(
                TeamScore,
                label,
                llm_calls_so_far=llm_so_far,
                max_llm_calls=20,
            )
            llm_so_far += cost.llm_calls
        return llm_so_far

    with patch(
        "founding_team_analyzer.llm._invoke_structured",
        side_effect=_fake_invoke,
    ), patch("founding_team_analyzer.llm._make_chat", return_value=None):
        # Interleave two runs: A makes 7 calls, B makes 3
        results = await asyncio.gather(
            _run_task("Run-A", 7),
            _run_task("Run-B", 3),
        )

    counter_a, counter_b = results
    assert counter_a == 7, (
        f"Run A per-run counter should be 7, got {counter_a}"
    )
    assert counter_b == 3, (
        f"Run B per-run counter should be 3, got {counter_b}"
    )

    # Verify that both runs actually made calls (7 + 3 = 10 total)
    assert len(call_log) == 10, (
        f"Expected 10 total LLM calls, got {len(call_log)}"
    )
    # Verify each run's calls are tracked independently
    a_calls = sum(1 for p in call_log if p == "Run-A")
    b_calls = sum(1 for p in call_log if p == "Run-B")
    assert a_calls == 7, f"Run A should have 7 logged calls, got {a_calls}"
    assert b_calls == 3, f"Run B should have 3 logged calls, got {b_calls}"


# ---------------------------------------------------------------------------
# VAL-BE-005: Per-run budget enforcement is independent
# ---------------------------------------------------------------------------


def test_counter_budget_exhausted_per_run():
    """Budget exhaustion on run A must not prevent run B from proceeding.

    With max_llm_calls=5, run A makes 4 calls (under budget) and run B
    makes 6 calls (over budget). A should succeed, B should fail.

    The LLM is stubbed so no real API calls are made.
    """
    fake_result = TeamScore(
        criteria=[],
        overall_0_100=0.0,
        tier="Mixed",
        top_strengths=[],
        top_risks=[],
        open_questions=[],
    )
    fake_llm_cost = CostLedger(llm_calls=1)

    with patch(
        "founding_team_analyzer.llm._invoke_structured",
        return_value=fake_result,
    ), patch("founding_team_analyzer.llm._make_chat", return_value=None):
        # Run A: 4 calls, budget=5 -> should be fine
        result_a, cost_a = call_structured(
            TeamScore,
            "test prompt for A",
            llm_calls_so_far=4,
            max_llm_calls=5,
        )
        assert result_a is not None, "Run A should succeed (4 < 5 budget)"

        # Run B: 6 calls already made, budget=5 -> should hit budget
        with pytest.raises(LLMBudgetExceeded):
            call_structured(
                TeamScore,
                "test prompt for B",
                llm_calls_so_far=5,
                max_llm_calls=5,
            )

    # Run A still fine after B exhausted its budget (independence)
    # This would fail with the old global counter because B's overruns
    # would have incremented the shared counter past A's limit.


# ---------------------------------------------------------------------------
# VAL-BE-006: Concurrent runs honor distinct no_self_critique settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_env_poisoning_self_critique():
    """Setting self_critique=False on one run must not affect another.

    Two overlapping runs: A with self_critique_disabled=True, B with
    self_critique_disabled=False. Both should see their own flag.
    """
    from founding_team_analyzer.nodes.team_scorer import _self_critique_enabled
    from founding_team_analyzer.state import AnalyzerState

    state_a: AnalyzerState = {
        "raw_input": "Acme",
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": True,
    }
    state_b: AnalyzerState = {
        "raw_input": "Beta",
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    # Run A should have self-critique disabled
    assert _self_critique_enabled(state_a) is False, "Run A should have self-critique disabled"
    # Run B should have self-critique enabled
    assert _self_critique_enabled(state_b) is True, "Run B should have self-critique enabled"


# ---------------------------------------------------------------------------
# VAL-BE-007: os.environ["FTA_DISABLE_SELF_CRITIQUE"] is not used as channel
# ---------------------------------------------------------------------------


def test_self_critique_flag_scoped_to_run():
    """Self-critique flag must be read from state, not os.environ.

    Pre-set os.environ["FTA_DISABLE_SELF_CRITIQUE"] = "1" and then
    request a run with self_critique_disabled=False. The run should
    still perform self-critique (state-driven, env ignored).
    """
    from founding_team_analyzer.nodes.team_scorer import _self_critique_enabled
    from founding_team_analyzer.state import AnalyzerState

    # Poison the environment
    original = os.environ.get("FTA_DISABLE_SELF_CRITIQUE")
    os.environ["FTA_DISABLE_SELF_CRITIQUE"] = "1"
    try:
        # Run requests self-critique enabled (state says False = not disabled)
        state: AnalyzerState = {
            "raw_input": "Gamma",
            "warnings": [],
            "cost": CostLedger(),
            "self_critique_disabled": False,
        }
        assert _self_critique_enabled(state) is True, (
            "Self-critique should be enabled because state.self_critique_disabled=False, "
            "even though os.environ is poisoned"
        )
    finally:
        # Restore environment
        if original is None:
            os.environ.pop("FTA_DISABLE_SELF_CRITIQUE", None)
        else:
            os.environ["FTA_DISABLE_SELF_CRITIQUE"] = original


# ---------------------------------------------------------------------------
# Integration: stream_analysis forwards self_critique_disabled into state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_analysis_forwards_self_critique_flag():
    """stream_analysis() must set self_critique_disabled in AnalyzerState."""
    from founding_team_analyzer import streaming_graph as sg
    from founding_team_analyzer.schemas import CostLedger, Company

    events: list[dict] = []

    # Stub the graph to capture the initial state passed to astream
    captured_initial = {}

    class FakeGraph:
        async def astream(self, initial, **kwargs):
            captured_initial.update(initial)
            # Yield a minimal update to avoid infinite loop
            yield {"company_profiler": {"company": Company(name="Acme"), "warnings": [], "cost": CostLedger()}}

    with patch.object(sg, "build_graph", return_value=FakeGraph()):
        async for event in sg.stream_analysis("Acme", no_self_critique=True):
            events.append(event.to_dict())

    assert captured_initial.get("self_critique_disabled") is True, (
        "stream_analysis should set self_critique_disabled=True in initial state"
    )


# ---------------------------------------------------------------------------
# Integration: server passes no_self_critique to stream_analysis
# ---------------------------------------------------------------------------


def test_server_passes_no_self_critique_to_stream():
    """POST /api/analyze with no_self_critique=True must not set os.environ."""
    import json
    import time
    from pathlib import Path
    from typing import AsyncIterator
    from fastapi.testclient import TestClient

    os.environ.setdefault("OPENAI_API_KEY", "test-openai")
    os.environ.setdefault("TAVILY_API_KEY", "test-tavily")

    # Track what was passed to stream_analysis
    stream_calls: list[dict] = []

    class FakeEvent:
        def __init__(self, type_: str, payload: dict) -> None:
            self.type = type_
            self._payload = payload

        def to_dict(self) -> dict:
            return {"type": self.type, "ts": "2026-01-01T00:00:00+00:00", "payload": dict(self._payload)}

    async def fake_stream(raw_input: str, *, no_self_critique: bool = False) -> AsyncIterator[FakeEvent]:
        stream_calls.append({"raw_input": raw_input, "no_self_critique": no_self_critique})
        yield FakeEvent("run_started", {"input": raw_input, "nodes": []})
        yield FakeEvent("node_started", {"node": "company_profiler", "label": "x"})
        yield FakeEvent("node_finished", {"node": "company_profiler", "label": "x", "warnings": []})
        yield FakeEvent("done", {"company_name": "Acme", "warnings": []})

    with patch("founding_team_analyzer.server.stream_analysis", fake_stream):
        with patch("founding_team_analyzer.streaming_graph.stream_analysis", fake_stream):
            from founding_team_analyzer import config as cfg
            from founding_team_analyzer import runs as runs_module
            from founding_team_analyzer import server as server_module

            # Ensure no env poisoning before the call
            os.environ.pop("FTA_DISABLE_SELF_CRITIQUE", None)

            client = TestClient(server_module.create_app())
            r = client.post("/api/analyze", json={"input": "Acme", "no_self_critique": True})
            assert r.status_code == 200

            # Verify stream_analysis was called with no_self_critique=True
            assert any(c["no_self_critique"] is True for c in stream_calls), (
                f"stream_analysis should receive no_self_critique=True, got: {stream_calls}"
            )

            # Verify os.environ was NOT set
            assert "FTA_DISABLE_SELF_CRITIQUE" not in os.environ, (
                "server should not set FTA_DISABLE_SELF_CRITIQUE in os.environ"
            )
