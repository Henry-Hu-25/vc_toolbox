"""Broadened test coverage for streaming_graph: event ordering, warnings
aggregation, concurrent-run warning isolation.

Validates VAL-BE-024 (concurrent runs see own warnings) and
VAL-BE-025 (full event ordering across all 6 nodes).

These tests stub the LangGraph to avoid real LLM/Tavily API calls.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from unittest.mock import patch

import pytest

from founding_team_analyzer.events import Event, NODE_LABELS
from founding_team_analyzer.schemas import (
    Company,
    CostLedger,
    Founder,
    FounderProfile,
    TeamOverlap,
    TeamScore,
)
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


class _AllSixNodesGraph:
    """Simulates a complete graph run through all 6 nodes sequentially,
    with no fan-out (1 founder).  Each node appends distinct warnings
    and cost increments.
    """

    def __init__(self, *, founder_count: int = 1) -> None:
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
                    "profiles": [FounderProfile(name=f"Founder {i}", current_title="CEO")],
                    "warnings": [f"W3-{i}: researcher warning"],
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
                "score": TeamScore(
                    criteria=[],
                    overall_0_100=50.0,
                    tier="Mixed",
                    top_strengths=[],
                    top_risks=[],
                    open_questions=[],
                ),
                "warnings": ["W5: scorer warning"],
                "cost": CostLedger(llm_calls=3),
            }
        }
        # report_writer (no warnings)
        yield {
            "report_writer": {
                "report_md": "# Report",
                "slug": "testco",
                "warnings": [],
                "cost": CostLedger(),
            }
        }


class _ThreeNodeWarningsGraph:
    """Three nodes that each emit a different warning; the last node
    emits no warning.  Used for warnings aggregation tests."""

    def __init__(self, *, warning_a: list[str], warning_b: list[str], warning_c: list[str]) -> None:
        self._wa = warning_a
        self._wb = warning_b
        self._wc = warning_c

    async def astream(self, initial, **kwargs):
        yield {
            "company_profiler": {
                "company": Company(name="A"),
                "warnings": self._wa,
                "cost": CostLedger(llm_calls=1),
            }
        }
        yield {
            "founder_finder": {
                "founders": [Founder(name="F1")],
                "warnings": self._wb,
                "cost": CostLedger(llm_calls=1),
            }
        }
        yield {
            "founder_researcher": {
                "profiles": [FounderProfile(name="F1", current_title="CEO")],
                "warnings": self._wc,
                "cost": CostLedger(llm_calls=1),
            }
        }
        yield {
            "overlap_analyzer": {
                "overlaps": TeamOverlap(),
                "warnings": [],
                "cost": CostLedger(),
            }
        }
        yield {
            "team_scorer": {
                "score": TeamScore(
                    criteria=[], overall_0_100=50.0, tier="Mixed",
                    top_strengths=[], top_risks=[], open_questions=[],
                ),
                "warnings": [],
                "cost": CostLedger(),
            }
        }
        yield {
            "report_writer": {
                "report_md": "# R",
                "slug": "a",
                "warnings": [],
                "cost": CostLedger(),
            }
        }


# ---------------------------------------------------------------------------
# VAL-BE-025: Full event ordering across all 6 nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_event_ordering_all_six_nodes():
    """Drive stream_analysis() against a stubbed graph executing all 6
    nodes with fan-out.  Validate:

    (a) run_started is the first event
    (b) for each node, node_started index < node_finished index
    (c) done is the last event and no node_* events follow it
    (d) no node emits two node_started or two node_finished events
    """
    graph = _AllSixNodesGraph(founder_count=3)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    # (a) run_started is the first event
    assert events[0].type == "run_started", (
        f"First event must be run_started, got {events[0].type}"
    )

    # (b) & (d): Build index maps and check for duplicates
    started_at: dict[str, list[int]] = {}
    finished_at: dict[str, list[int]] = {}
    for i, e in enumerate(events):
        node = e.payload.get("node")
        if not node:
            continue
        if e.type == "node_started":
            started_at.setdefault(node, []).append(i)
        elif e.type == "node_finished":
            finished_at.setdefault(node, []).append(i)

    # (d) No node emits two node_started or two node_finished events
    for node, indices in started_at.items():
        assert len(indices) == 1, (
            f"Node {node} emitted {len(indices)} node_started events, expected 1"
        )
    for node, indices in finished_at.items():
        assert len(indices) == 1, (
            f"Node {node} emitted {len(indices)} node_finished events, expected 1"
        )

    # (b) For each node that started, it must have also finished,
    #     and started index < finished index
    for node in started_at:
        assert node in finished_at, (
            f"Node {node} has node_started but no node_finished"
        )
        assert started_at[node][0] < finished_at[node][0], (
            f"node_started({started_at[node][0]}) must precede "
            f"node_finished({finished_at[node][0]}) for {node}"
        )

    # (c) done is the last event and no node_* events follow it
    done_events = _events_by_type(events, "done")
    assert len(done_events) == 1, f"Expected exactly 1 done event, got {len(done_events)}"
    done_index = events.index(done_events[0])
    assert done_index == len(events) - 1, (
        f"done event must be the last event (index {done_index}), "
        f"but there are {len(events) - 1 - done_index} events after it"
    )
    # Verify no node_started or node_finished after done
    post_done_events = events[done_index + 1:]
    node_post = [e for e in post_done_events if e.type in ("node_started", "node_finished")]
    assert len(node_post) == 0, (
        f"No node_* events should follow done, but found {len(node_post)}"
    )


@pytest.mark.asyncio
async def test_full_event_ordering_no_fanout():
    """Event ordering with a single founder (minimal fan-out of 1).
    All 6 nodes should still produce exactly one node_started/node_finished
    pair each, with run_started first and done last."""
    graph = _AllSixNodesGraph(founder_count=1)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    assert events[0].type == "run_started"
    assert events[-1].type == "done"

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

    # All 6 nodes must be present
    expected_nodes = set(NODE_LABELS.keys())
    assert set(started_at.keys()) == expected_nodes, (
        f"Expected node_started for {expected_nodes}, got {set(started_at.keys())}"
    )
    assert set(finished_at.keys()) == expected_nodes, (
        f"Expected node_finished for {expected_nodes}, got {set(finished_at.keys())}"
    )

    for node in started_at:
        assert started_at[node] < finished_at[node], (
            f"node_started must precede node_finished for {node}"
        )


# ---------------------------------------------------------------------------
# VAL-BE-024: Concurrent runs each see the union of their OWN warnings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_runs_see_own_warnings_only():
    """Two concurrent runs with distinct warning sets.  Each run's done
    event must contain only its own warnings — no cross-contamination.

    Run A warnings: {"a1", "a2"}
    Run B warnings: {"b1", "b2", "b3"}
    """
    graph_a = _ThreeNodeWarningsGraph(
        warning_a=["a1"], warning_b=["a2"], warning_c=[],
    )
    graph_b = _ThreeNodeWarningsGraph(
        warning_a=["b1"], warning_b=["b2"], warning_c=["b3"],
    )

    # We need to patch build_graph differently for each call.
    # Since stream_analysis calls build_graph() internally, we need
    # a way to return different graphs for different invocations.
    call_count = 0

    def _build_graph_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return graph_a
        return graph_b

    with patch.object(sg, "build_graph", side_effect=_build_graph_side_effect):
        events_a, events_b = await asyncio.gather(
            _collect_events("Company A"),
            _collect_events("Company B"),
        )

    done_a = _events_by_type(events_a, "done")
    done_b = _events_by_type(events_b, "done")
    assert len(done_a) == 1, f"Run A: expected 1 done event, got {len(done_a)}"
    assert len(done_b) == 1, f"Run B: expected 1 done event, got {len(done_b)}"

    warnings_a = set(done_a[0].payload.get("warnings", []))
    warnings_b = set(done_b[0].payload.get("warnings", []))

    assert warnings_a == {"a1", "a2"}, (
        f"Run A warnings should be {{a1, a2}}, got {warnings_a}"
    )
    assert warnings_b == {"b1", "b2", "b3"}, (
        f"Run B warnings should be {{b1, b2, b3}}, got {warnings_b}"
    )
    # Verify no cross-contamination
    assert warnings_a.isdisjoint(warnings_b), (
        f"Runs A and B have overlapping warnings: "
        f"A={warnings_a}, B={warnings_b}"
    )


@pytest.mark.asyncio
async def test_concurrent_runs_see_own_cost_only():
    """Two concurrent runs with different cost profiles.  Each run's
    done event must contain only its own cost — no cross-contamination."""
    class _HighCostGraph:
        async def astream(self, initial, **kwargs):
            yield {"company_profiler": {"company": Company(name="A"), "warnings": [], "cost": CostLedger(llm_calls=10, tavily_searches=5)}}
            yield {"founder_finder": {"founders": [Founder(name="F1")], "warnings": [], "cost": CostLedger(llm_calls=5, tavily_searches=3)}}
            yield {"founder_researcher": {"profiles": [FounderProfile(name="F1", current_title="CEO")], "warnings": [], "cost": CostLedger(llm_calls=8, tavily_searches=4)}}
            yield {"overlap_analyzer": {"overlaps": TeamOverlap(), "warnings": [], "cost": CostLedger(llm_calls=2)}}
            yield {"team_scorer": {"score": TeamScore(criteria=[], overall_0_100=50.0, tier="Mixed", top_strengths=[], top_risks=[], open_questions=[]), "warnings": [], "cost": CostLedger(llm_calls=6)}}
            yield {"report_writer": {"report_md": "# R", "slug": "a", "warnings": [], "cost": CostLedger()}}

    class _LowCostGraph:
        async def astream(self, initial, **kwargs):
            yield {"company_profiler": {"company": Company(name="B"), "warnings": [], "cost": CostLedger(llm_calls=1, tavily_searches=1)}}
            yield {"founder_finder": {"founders": [Founder(name="F1")], "warnings": [], "cost": CostLedger(llm_calls=1)}}
            yield {"founder_researcher": {"profiles": [FounderProfile(name="F1", current_title="CEO")], "warnings": [], "cost": CostLedger(llm_calls=1, tavily_searches=1)}}
            yield {"overlap_analyzer": {"overlaps": TeamOverlap(), "warnings": [], "cost": CostLedger(llm_calls=1)}}
            yield {"team_scorer": {"score": TeamScore(criteria=[], overall_0_100=50.0, tier="Mixed", top_strengths=[], top_risks=[], open_questions=[]), "warnings": [], "cost": CostLedger(llm_calls=1)}}
            yield {"report_writer": {"report_md": "# R", "slug": "b", "warnings": [], "cost": CostLedger()}}

    call_count = 0

    def _build_graph_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _HighCostGraph()
        return _LowCostGraph()

    with patch.object(sg, "build_graph", side_effect=_build_graph_side_effect):
        events_a, events_b = await asyncio.gather(
            _collect_events("Company A"),
            _collect_events("Company B"),
        )

    done_a = _events_by_type(events_a, "done")
    done_b = _events_by_type(events_b, "done")
    assert len(done_a) == 1
    assert len(done_b) == 1

    cost_a = done_a[0].payload.get("cost", {})
    cost_b = done_b[0].payload.get("cost", {})

    # High cost: 10+5+8+2+6 = 31 LLM, 5+3+4 = 12 tavily
    assert cost_a["llm_calls"] == 31, f"Run A: expected 31 llm_calls, got {cost_a['llm_calls']}"
    assert cost_a["tavily_searches"] == 12, f"Run A: expected 12 tavily_searches, got {cost_a['tavily_searches']}"

    # Low cost: 1+1+1+1+1 = 5 LLM, 1+1 = 2 tavily
    assert cost_b["llm_calls"] == 5, f"Run B: expected 5 llm_calls, got {cost_b['llm_calls']}"
    assert cost_b["tavily_searches"] == 2, f"Run B: expected 2 tavily_searches, got {cost_b['tavily_searches']}"


# ---------------------------------------------------------------------------
# Warnings aggregation: multiple warnings per node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_warnings_per_node_aggregated():
    """A single node that emits multiple warnings: all must appear in the
    done event."""
    graph = _ThreeNodeWarningsGraph(
        warning_a=["a1", "a2", "a3"],
        warning_b=["b1"],
        warning_c=["c1", "c2"],
    )

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    done = _events_by_type(events, "done")
    assert len(done) == 1
    warnings = set(done[0].payload.get("warnings", []))
    assert warnings == {"a1", "a2", "a3", "b1", "c1", "c2"}, (
        f"Expected all 6 warnings in done, got {warnings}"
    )


@pytest.mark.asyncio
async def test_no_warnings_produces_empty_list():
    """When no node emits any warnings, the done event should have an
    empty warnings list."""
    graph = _ThreeNodeWarningsGraph(
        warning_a=[], warning_b=[], warning_c=[],
    )

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    done = _events_by_type(events, "done")
    assert len(done) == 1
    warnings = done[0].payload.get("warnings", [])
    assert warnings == [], f"Expected empty warnings, got {warnings}"


# ---------------------------------------------------------------------------
# Warnings deduplication: same warning text from two nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_warning_text_not_duplicated_in_done():
    """When two nodes emit the same warning text, it should appear only
    once in the done event's warnings list (cumulative_warnings uses
    'if w not in cumulative_warnings' for dedup)."""
    graph = _ThreeNodeWarningsGraph(
        warning_a=["shared warning"],
        warning_b=["shared warning"],
        warning_c=[],
    )

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    done = _events_by_type(events, "done")
    assert len(done) == 1
    warnings = done[0].payload.get("warnings", [])
    assert warnings.count("shared warning") == 1, (
        f"Duplicate warning text should appear once, got {warnings}"
    )


# ---------------------------------------------------------------------------
# Event sequence: node order matches expected pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_started_sequence_matches_pipeline():
    """The node_started events must follow the pipeline order:
    company_profiler -> founder_finder -> founder_researcher ->
    overlap_analyzer -> team_scorer -> report_writer."""
    graph = _AllSixNodesGraph(founder_count=2)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    started_nodes = [
        e.payload["node"]
        for e in events
        if e.type == "node_started"
    ]
    expected_order = [
        "company_profiler",
        "founder_finder",
        "founder_researcher",
        "overlap_analyzer",
        "team_scorer",
        "report_writer",
    ]
    assert started_nodes == expected_order, (
        f"node_started sequence must match pipeline order. "
        f"Expected {expected_order}, got {started_nodes}"
    )


@pytest.mark.asyncio
async def test_node_finished_sequence_matches_pipeline():
    """The node_finished events must follow the same pipeline order."""
    graph = _AllSixNodesGraph(founder_count=2)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    finished_nodes = [
        e.payload["node"]
        for e in events
        if e.type == "node_finished"
    ]
    expected_order = [
        "company_profiler",
        "founder_finder",
        "founder_researcher",
        "overlap_analyzer",
        "team_scorer",
        "report_writer",
    ]
    assert finished_nodes == expected_order, (
        f"node_finished sequence must match pipeline order. "
        f"Expected {expected_order}, got {finished_nodes}"
    )


# ---------------------------------------------------------------------------
# run_started payload includes all 6 node descriptors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_started_payload_includes_all_nodes():
    """The run_started event payload must list all 6 nodes with labels."""
    graph = _AllSixNodesGraph(founder_count=1)

    with patch.object(sg, "build_graph", return_value=graph):
        events = [e async for e in sg.stream_analysis("TestCo")]

    started = _events_by_type(events, "run_started")
    assert len(started) == 1
    payload = started[0].payload
    assert payload["input"] == "TestCo"

    node_ids = [n["id"] for n in payload["nodes"]]
    assert node_ids == [
        "company_profiler",
        "founder_finder",
        "founder_researcher",
        "overlap_analyzer",
        "team_scorer",
        "report_writer",
    ]

    # Each node must have a non-empty label
    for n in payload["nodes"]:
        assert n["label"], f"Node {n['id']} has empty label"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


async def _collect_events(raw_input: str) -> list[Event]:
    """Collect all events from a single stream_analysis run."""
    return [e async for e in sg.stream_analysis(raw_input)]
