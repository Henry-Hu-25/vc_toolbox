"""SSE event types emitted by the streaming pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


EventType = Literal[
    "run_started",
    "node_started",
    "node_finished",
    "warning",
    "cost_update",
    "done",
    "error",
]


NODE_LABELS: dict[str, str] = {
    "company_profiler": "Resolving company",
    "founder_finder": "Identifying founders",
    "founder_researcher": "Researching founders",
    "overlap_analyzer": "Analyzing shared history",
    "team_scorer": "Scoring against rubric",
    "report_writer": "Rendering report",
}


@dataclass
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "ts": self.ts, "payload": self.payload}


def label_for(node_id: str) -> str:
    return NODE_LABELS.get(node_id, node_id.replace("_", " ").title())
