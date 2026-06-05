"""Tests for event ordering fixes: done-event warnings/cost aggregation and
researcher fan-out event shape.

Validates VAL-BE-009, VAL-BE-010, VAL-BE-011, VAL-BE-012.

These tests stub the LangGraph to avoid real LLM/Tavily API calls.
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import patch

import pytest

from founding_team_analyzer.events import Event, NODE_LABELS
from founding_team_analyzer.schemas import Company, CostLedger, Founder, TeamOverlap
from founding_team_analyzer import streaming_graph as sg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _events_by_type(events: list[Event], etype: str) -> list[Event]:
    return [e for e in events if e.type == etype]


def _events_for_node(events: list[Event], etype: str, node: str) -> list[Event]:
    return [
        e
        for e in events
        if e.type == etype and e.payload.get("node") == node
    ]


# ---------------------------------------------------------------------------
# Fake graph builders
# ---------------------------------------------------------------------------


class _SequentialFakeGraph:
    """Simulates a graph where each node runs sequentially with no fan-out.

    Each node appends its own warning and cost increment.
    """

    def __init__(self, node_updates: list[dict[str, Any]]) -> None:
        self._updates = node_updates

    async def astream(self, initial, **kwargs):
        for upd in self._updates:
            yield upd


class _FanOutFakeGraph:
    """Simulates a graph with researcher fan-out: one founder_researcher
    update per founder, then overlap_analyzer.

    The researcher sub-updates each carry a partial profile + cost.
    """

    def __init__(self, founder_count: int) -> None:
        self._founder_count = founder_count

    async def astream(self, initial, **kwargs):
        # company_profiler
        yield {
            "company_profiler": {
                "company": Company(name="TestCo"),
                "warnings": ["W1: profiler warning"],
                "cost": CostLedger(llm_calls=2, tavily_searches=1),
            }
        }
        # founder_finder
        yield {
            "founder_finder": {
                "founders": [Founder(name=f"Founder {i}") for i in range(self._founder_count)],
                "warnings": ["W2: finder warning"],
                "cost": CostLedger(llm_calls=1),
            }
        }
        # researcher fan-out: one update per founder
        for i in range(self._founder_count):
            yield {
                "founder_researcher": {
                    "profiles": [{"name": f"Founder {i}"}],
                    "warnings": [f"W3-{i}: researcher warning for founder {i}"],
                    "cost": CostLedger(llm_calls=2, tavily_searches=2),
                }
            }
        # overlap_analyzer
        yield {
            "overlap_analyzer": {
                "overlaps": TeamOverlap(),
                "warnings": ["W4: overlap warning"],
                "cost": CostLedger(llm_calls=1),
            }
        }
        # team_scorer
        yield {
            "team_scorer": {
                "score": {"overall_0_100": 50},
                "warnings": ["W5: scorer warning"],
                "cost": CostLedger(llm_calls=3),
            }
        }
        # report_writer (no warnings)
        yield {
            "report_writer": {
                "report_md": "# Report",
                "warnings": [],
                "cost": CostLedger(),
            }
        }


# ---------------------------------------------------------------------------
# VAL-BE-009: done.cost reflects accumulated cost across all nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_done_cost_accumulates_across_all_nodes():
    """done.payload['cost'] must reflect the sum of costs from every node."""
    graph = _SequentialFakeGraph([
        {"company_profiler": {"company": Company(name="A"), "warnings": [], "cost": CostLedger(llm_calls=2, tavily_searches=1)}},
        {"founder_finder": {"founders": [], "warnings": [], "cost": CostLedger(llm_calls=1)}},
        {"overlap_analyzer": {"overlaps": TeamOverlap(), "warnings": [], "cost": CostLedger(llm_calls=1)}},
        {"team_scorer": {"score": {"overall_0_100": 50}, "warnings": [], "cost": CostLedger(llm_calls=4)}},
        {"report_writer": {"report_md": "# R", "warnings": [], "cost": CostLedger()}},
    ])

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    done_events = _events_by_type(events, "done")
    assert len(done_events) == 1, f"Expected exactly 1 done event, got {len(done_events)}"
    done = done_events[0]

    cost = done.payload.get("cost")
    assert cost is not None, "done event must include a 'cost' field"
    assert cost["llm_calls"] == 8, f"Expected llm_calls=8, got {cost['llm_calls']}"
    assert cost["tavily_searches"] == 1, f"Expected tavily_searches=1, got {cost['tavily_searches']}"


# ---------------------------------------------------------------------------
# VAL-BE-012 (part of this feature): done.warnings contains union of all nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_done_warnings_contains_union_from_all_nodes():
    """done.payload['warnings'] must contain warnings from every node, not
    just the last one.

    Validates F-BE-004: three nodes each append a distinct warning;
    the done event must contain the union {W1, W2, W3}.
    """
    graph = _SequentialFakeGraph([
        {"company_profiler": {"company": Company(name="A"), "warnings": ["W1"], "cost": CostLedger()}},
        {"founder_finder": {"founders": [], "warnings": ["W2"], "cost": CostLedger()}},
        {"overlap_analyzer": {"overlaps": TeamOverlap(), "warnings": ["W3"], "cost": CostLedger()}},
        {"team_scorer": {"score": {"overall_0_100": 50}, "warnings": [], "cost": CostLedger()}},
        {"report_writer": {"report_md": "# R", "warnings": [], "cost": CostLedger()}},
    ])

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    done_events = _events_by_type(events, "done")
    assert len(done_events) == 1
    done = done_events[0]

    warnings = done.payload.get("warnings", [])
    assert set(warnings) == {"W1", "W2", "W3"}, (
        f"done.warnings should be union {{W1, W2, W3}}, got {warnings}"
    )


# ---------------------------------------------------------------------------
# VAL-BE-010: Fan-out emits exactly one node_started for founder_researcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fan_out_emits_exactly_one_node_started():
    """With a fan-out of 4 founders, exactly 1 node_started event for
    founder_researcher must be emitted."""
    graph = _FanOutFakeGraph(founder_count=4)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    started = _events_for_node(events, "node_started", "founder_researcher")
    assert len(started) == 1, (
        f"Expected exactly 1 node_started for founder_researcher, got {len(started)}"
    )


# ---------------------------------------------------------------------------
# VAL-BE-011: Fan-out emits exactly one node_finished for founder_researcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fan_out_emits_exactly_one_node_finished():
    """With a fan-out of 4 founders, exactly 1 node_finished event for
    founder_researcher must be emitted (after all per-founder work completes)."""
    graph = _FanOutFakeGraph(founder_count=4)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    finished = _events_for_node(events, "node_finished", "founder_researcher")
    assert len(finished) == 1, (
        f"Expected exactly 1 node_finished for founder_researcher, got {len(finished)}"
    )


# ---------------------------------------------------------------------------
# Combined: fan-out produces strictly monotonic sequence per node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fan_out_monotonic_sequence_per_node():
    """For every node, node_started index < node_finished index, and no
    node has more than one pair."""
    graph = _FanOutFakeGraph(founder_count=3)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    # Build index maps
    started_at: dict[str, int] = {}
    finished_at: dict[str, int] = {}
    for i, e in enumerate(events):
        node = e.payload.get("node")
        if not node:
            continue
        if e.type == "node_started":
            assert node not in started_at, f"Duplicate node_started for {node}"
            started_at[node] = i
        elif e.type == "node_finished":
            assert node not in finished_at, f"Duplicate node_finished for {node}"
            finished_at[node] = i

    for node in started_at:
        assert node in finished_at, f"node_started but no node_finished for {node}"
        assert started_at[node] < finished_at[node], (
            f"node_started({started_at[node]}) must precede node_finished({finished_at[node]}) for {node}"
        )


# ---------------------------------------------------------------------------
# Fan-out done.warnings includes researcher warnings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fan_out_done_warnings_includes_researcher_warnings():
    """When researcher fan-out produces per-founder warnings, the done event
    must include all of them in its union."""
    graph = _FanOutFakeGraph(founder_count=3)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    done_events = _events_by_type(events, "done")
    assert len(done_events) == 1
    done = done_events[0]

    warnings = done.payload.get("warnings", [])
    # Should have warnings from all nodes including the 3 researcher sub-nodes
    assert "W1: profiler warning" in warnings
    assert "W2: finder warning" in warnings
    assert "W4: overlap warning" in warnings
    assert "W5: scorer warning" in warnings
    # All 3 researcher warnings should be present
    for i in range(3):
        assert f"W3-{i}: researcher warning for founder {i}" in warnings


# ---------------------------------------------------------------------------
# Fan-out done.cost accumulates researcher costs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fan_out_done_cost_accumulates_researcher_costs():
    """When researcher fan-out runs multiple sub-nodes, the done event cost
    must sum all their individual costs."""
    graph = _FanOutFakeGraph(founder_count=3)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    done_events = _events_by_type(events, "done")
    assert len(done_events) == 1
    done = done_events[0]

    cost = done.payload.get("cost")
    assert cost is not None
    # profiler: 2 llm, 1 tavily
    # finder: 1 llm
    # 3x researcher: 3*2=6 llm, 3*2=6 tavily
    # overlap: 1 llm
    # scorer: 3 llm
    # Total: 2+1+6+1+3 = 13 llm, 1+6 = 7 tavily
    assert cost["llm_calls"] == 13, f"Expected llm_calls=13, got {cost['llm_calls']}"
    assert cost["tavily_searches"] == 7, f"Expected tavily_searches=7, got {cost['tavily_searches']}"


# ---------------------------------------------------------------------------
# Fan-out emits intermediate cost_update events during fan-out phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fan_out_emits_intermediate_cost_updates():
    """During researcher fan-out, cost_update events should be emitted after
    each sub-invocation so the UI shows live cost feedback."""
    graph = _FanOutFakeGraph(founder_count=3)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    # Collect cost_update events that occur between researcher node_started
    # and researcher node_finished
    researcher_started = False
    researcher_finished = False
    intermediate_cost_updates = []

    for e in events:
        if e.type == "node_started" and e.payload.get("node") == "founder_researcher":
            researcher_started = True
        elif e.type == "node_finished" and e.payload.get("node") == "founder_researcher":
            researcher_finished = True
        elif researcher_started and not researcher_finished and e.type == "cost_update":
            intermediate_cost_updates.append(e)

    assert len(intermediate_cost_updates) >= 3, (
        f"Expected at least 3 intermediate cost_updates during fan-out, got {len(intermediate_cost_updates)}"
    )

    # Each intermediate cost_update should show increasing llm_calls
    llm_calls_seq = [cu.payload["llm_calls"] for cu in intermediate_cost_updates]
    # At least the first should reflect researcher progress
    assert llm_calls_seq[-1] > llm_calls_seq[0], (
        f"Intermediate cost_updates should show increasing cost: {llm_calls_seq}"
    )


# ---------------------------------------------------------------------------
# Fan-out emits individual warning events during fan-out phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fan_out_emits_intermediate_warning_events():
    """During researcher fan-out, individual warning events should be emitted
    per sub-invocation so the UI shows warnings in real-time."""
    graph = _FanOutFakeGraph(founder_count=3)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    # Collect warning events that occur between researcher node_started
    # and researcher node_finished
    researcher_started = False
    researcher_finished = False
    intermediate_warnings = []

    for e in events:
        if e.type == "node_started" and e.payload.get("node") == "founder_researcher":
            researcher_started = True
        elif e.type == "node_finished" and e.payload.get("node") == "founder_researcher":
            researcher_finished = True
        elif researcher_started and not researcher_finished and e.type == "warning":
            intermediate_warnings.append(e)

    assert len(intermediate_warnings) == 3, (
        f"Expected 3 intermediate warning events during fan-out, got {len(intermediate_warnings)}"
    )


# ---------------------------------------------------------------------------
# Event ordering: run_started is first, done is last
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_ordering_run_started_first_done_last():
    """run_started must be the first event and done must be the last."""
    graph = _SequentialFakeGraph([
        {"company_profiler": {"company": Company(name="A"), "warnings": [], "cost": CostLedger()}},
        {"report_writer": {"report_md": "# R", "warnings": [], "cost": CostLedger()}},
    ])

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    assert events[0].type == "run_started", f"First event should be run_started, got {events[0].type}"
    assert events[-1].type == "done", f"Last event should be done, got {events[-1].type}"
