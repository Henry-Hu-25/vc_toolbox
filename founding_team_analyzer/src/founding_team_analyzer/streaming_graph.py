"""Run the LangGraph pipeline while emitting SSE-friendly progress events."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from .events import NODE_LABELS, Event, label_for
from .graph import build_graph
from .schemas import CostLedger
from .state import AnalyzerState

log = logging.getLogger(__name__)


async def stream_analysis(raw_input: str) -> AsyncIterator[Event]:
    """Yield Event objects as the graph executes node-by-node.

    Strategy: kick off the full graph in a background thread, and tail
    progress via LangGraph's `astream` (state updates by node). When the
    background invocation completes, emit a `done` event with the slug so
    the UI can navigate to the saved report.
    """
    app = build_graph()
    initial: AnalyzerState = {
        "raw_input": raw_input,
        "warnings": [],
        "cost": CostLedger(),
    }

    yield Event(
        type="run_started",
        payload={
            "input": raw_input,
            "nodes": [
                {"id": n, "label": label_for(n)}
                for n in (
                    "company_profiler",
                    "founder_finder",
                    "founder_researcher",
                    "overlap_analyzer",
                    "team_scorer",
                    "report_writer",
                )
            ],
        },
    )

    seen_started: set[str] = set()
    cumulative_cost = CostLedger()
    final_state: AnalyzerState | None = None

    try:
        async for update in app.astream(initial, stream_mode="updates"):
            # `update` is a dict {node_name: partial_state}
            for node_name, partial in update.items():
                if node_name not in NODE_LABELS:
                    continue
                if node_name not in seen_started:
                    seen_started.add(node_name)
                    yield Event(
                        type="node_started",
                        payload={"node": node_name, "label": label_for(node_name)},
                    )
                warnings = list(partial.get("warnings") or []) if isinstance(partial, dict) else []
                cost = partial.get("cost") if isinstance(partial, dict) else None
                if isinstance(cost, CostLedger):
                    cumulative_cost = cumulative_cost.merged(cost)
                yield Event(
                    type="node_finished",
                    payload={
                        "node": node_name,
                        "label": label_for(node_name),
                        "warnings": warnings,
                    },
                )
                for w in warnings:
                    yield Event(
                        type="warning",
                        payload={"node": node_name, "text": str(w)},
                    )
                yield Event(
                    type="cost_update",
                    payload=cumulative_cost.model_dump(),
                )
                if node_name == "report_writer" and isinstance(partial, dict):
                    final_state = {**(final_state or {}), **partial}
                elif isinstance(partial, dict):
                    final_state = {**(final_state or {}), **partial}
    except Exception as exc:
        log.exception("streaming pipeline failed")
        yield Event(type="error", payload={"message": str(exc)})
        return

    company = (final_state or {}).get("company")
    company_name = getattr(company, "name", None) if company else None

    yield Event(
        type="done",
        payload={
            "company_name": company_name,
            "warnings": list((final_state or {}).get("warnings") or []),
        },
    )
