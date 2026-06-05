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

# Nodes that fan out via LangGraph Send and therefore produce multiple
# astream updates for the same node name.  The streaming layer must
# coalesce these into a single node_started / node_finished pair.
_FAN_OUT_NODES: frozenset[str] = frozenset({"founder_researcher"})


async def stream_analysis(raw_input: str, *, no_self_critique: bool = False) -> AsyncIterator[Event]:
    """Yield Event objects as the graph executes node-by-node.

    Strategy: kick off the full graph in a background thread, and tail
    progress via LangGraph's `astream` (state updates by node). When the
    background invocation completes, emit a `done` event with the slug so
    the UI can navigate to the saved report.

    Per-run state (self_critique_disabled) is initialized from the
    no_self_critique kwarg so concurrent runs have independent flags.

    Event-ordering guarantees:
    - Exactly one ``node_started`` and one ``node_finished`` per logical
      node, including fan-out nodes like ``founder_researcher``.
    - The ``done`` event's ``warnings`` is the union of warnings from all
      nodes (not just the last node's shallow merge).
    - The ``done`` event's ``cost`` is the accumulated total across all
      nodes.
    """
    app = build_graph()
    initial: AnalyzerState = {
        "raw_input": raw_input,
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": no_self_critique,
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
    cumulative_warnings: list[str] = []
    final_state: AnalyzerState | None = None

    # Buffer for fan-out nodes: track that a fan-out is in progress so
    # we emit exactly one coalesced node_finished after all sub-invocations
    # complete.  Individual warning and cost_update events are emitted
    # immediately per sub-invocation so the UI sees real-time progress.
    active_fan_out: str | None = None  # name of the fan-out node currently being buffered
    fan_out_warnings: list[str] = []  # accumulated warnings for the coalesced node_finished

    def _flush_fan_out() -> None:
        """Emit a single coalesced node_finished for the buffered fan-out node."""
        nonlocal active_fan_out, fan_out_warnings
        if active_fan_out is None:
            return
        yield_from_inner(
            Event(
                type="node_finished",
                payload={
                    "node": active_fan_out,
                    "label": label_for(active_fan_out),
                    "warnings": list(fan_out_warnings),
                },
            )
        )
        active_fan_out = None
        fan_out_warnings = []

    # We need an inner yield mechanism because _flush_fan_out cannot yield
    # directly from a helper.  Instead, we collect flushed events into a
    # list and yield them in the main loop.
    _pending_events: list[Event] = []

    def yield_from_inner(event: Event) -> None:
        _pending_events.append(event)

    try:
        async for update in app.astream(initial, stream_mode="updates"):
            # `update` is a dict {node_name: partial_state}
            for node_name, partial in update.items():
                if node_name not in NODE_LABELS:
                    continue

                warnings = list(partial.get("warnings") or []) if isinstance(partial, dict) else []
                cost = partial.get("cost") if isinstance(partial, dict) else None

                # Accumulate warnings and cost into the global trackers
                # so the done event carries the union across all nodes.
                for w in warnings:
                    if w not in cumulative_warnings:
                        cumulative_warnings.append(w)
                if isinstance(cost, CostLedger):
                    cumulative_cost = cumulative_cost.merged(cost)

                is_fan_out = node_name in _FAN_OUT_NODES

                # If we were buffering a fan-out node and a different node
                # appeared, flush the buffered node_finished FIRST so the
                # event ordering stays correct (fan-out finishes before the
                # next node starts).
                if active_fan_out is not None and node_name != active_fan_out:
                    _flush_fan_out()
                    for evt in _pending_events:
                        yield evt
                    _pending_events.clear()

                if is_fan_out:
                    # For fan-out nodes: emit node_started only once, emit
                    # warning and cost_update per sub-invocation for real-time
                    # UI feedback, but buffer node_finished until all
                    # sub-invocations are done.
                    if node_name not in seen_started:
                        seen_started.add(node_name)
                        yield Event(
                            type="node_started",
                            payload={"node": node_name, "label": label_for(node_name)},
                        )
                    # Emit individual warning events immediately
                    for w in warnings:
                        yield Event(
                            type="warning",
                            payload={"node": node_name, "text": str(w)},
                        )
                    # Emit cost_update immediately for real-time feedback
                    yield Event(
                        type="cost_update",
                        payload=cumulative_cost.model_dump(),
                    )
                    # Buffer warnings for the final coalesced node_finished
                    fan_out_warnings.extend(warnings)
                    active_fan_out = node_name
                else:
                    # Regular (non-fan-out) node: emit events immediately.
                    if node_name not in seen_started:
                        seen_started.add(node_name)
                        yield Event(
                            type="node_started",
                            payload={"node": node_name, "label": label_for(node_name)},
                        )
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

                if isinstance(partial, dict):
                    final_state = {**(final_state or {}), **partial}

        # After the stream ends, flush any remaining fan-out buffer
        if active_fan_out is not None:
            _flush_fan_out()
            for evt in _pending_events:
                yield evt
            _pending_events.clear()

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
            "warnings": cumulative_warnings,
            "cost": cumulative_cost.model_dump(),
        },
    )
