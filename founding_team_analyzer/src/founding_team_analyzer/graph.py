"""LangGraph wiring: 6 nodes with Send fan-out for the per-founder researcher."""

from __future__ import annotations

from typing import Any

from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Send

from .nodes import (
    company_profiler,
    founder_finder,
    founder_researcher,
    overlap_analyzer,
    report_writer,
    team_scorer,
)
from .schemas import CostLedger
from .state import AnalyzerState


def _dispatch_researchers(state: AnalyzerState) -> list[Send]:
    founders = state.get("founders") or []
    company = state.get("company")
    base_llm_calls = (state.get("cost") or CostLedger()).llm_calls
    if not founders:
        # No founders -> skip researcher fan-out, go straight to overlap (which will no-op).
        return [Send("overlap_analyzer", state)]
    return [
        Send(
            "founder_researcher",
            {"founder": f, "company": company, "base_llm_calls": base_llm_calls},
        )
        for f in founders
    ]


def build_graph() -> Any:
    graph = StateGraph(AnalyzerState)
    graph.add_node("company_profiler", company_profiler.run)
    graph.add_node("founder_finder", founder_finder.run)
    graph.add_node("founder_researcher", founder_researcher.run)
    graph.add_node("overlap_analyzer", overlap_analyzer.run)
    graph.add_node("team_scorer", team_scorer.run)
    graph.add_node("report_writer", report_writer.run)

    graph.add_edge(START, "company_profiler")
    graph.add_edge("company_profiler", "founder_finder")
    graph.add_conditional_edges(
        "founder_finder",
        _dispatch_researchers,
        ["founder_researcher", "overlap_analyzer"],
    )
    graph.add_edge("founder_researcher", "overlap_analyzer")
    graph.add_edge("overlap_analyzer", "team_scorer")
    graph.add_edge("team_scorer", "report_writer")
    graph.add_edge("report_writer", END)

    return graph.compile()


def run_analysis(raw_input: str, *, no_self_critique: bool = False) -> AnalyzerState:
    app = build_graph()
    initial: AnalyzerState = {
        "raw_input": raw_input,
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": no_self_critique,
    }
    result = app.invoke(initial)
    return result  # type: ignore[return-value]
