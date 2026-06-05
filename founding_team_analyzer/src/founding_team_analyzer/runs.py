"""In-process registry for analyzer runs.

Decouples the lifetime of a run from any single HTTP/SSE connection.
The worker coroutine pushes events into the registry; any number of
subscribers can attach via `subscribe(...)` and receive a replay of
buffered events followed by live ones until the run reaches a terminal
state.

Limitations (documented non-goals):
    * No persistence across server restarts -- in-flight runs are lost.
    * Single-process only (no Redis / multi-worker fanout).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Literal, Optional

log = logging.getLogger(__name__)


RunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
TERMINAL_STATUSES: set[str] = {"completed", "failed", "cancelled"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunRecord:
    id: str
    input: str
    status: RunStatus = "pending"
    events: list[dict[str, Any]] = field(default_factory=list)
    report_slug: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    task: Optional[asyncio.Task] = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        return {
            "run_id": self.id,
            "input": self.input,
            "status": self.status,
            "report_slug": self.report_slug,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class RunRegistry:
    """Thread-unsafe but asyncio-safe registry of in-flight runs."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    # ----- lifecycle -----

    def create(
        self,
        input: str,
        task: Optional[asyncio.Task] = None,
        run_id: Optional[str] = None,
    ) -> RunRecord:
        if run_id is None:
            run_id = str(uuid.uuid4())
        record = RunRecord(id=run_id, input=input, task=task)
        self._runs[run_id] = record
        return record

    def get(self, run_id: str) -> Optional[RunRecord]:
        return self._runs.get(run_id)

    def list_running(self) -> list[RunRecord]:
        return [r for r in self._runs.values() if r.status not in TERMINAL_STATUSES]

    def list_all(self) -> list[RunRecord]:
        return list(self._runs.values())

    def attach_task(self, run_id: str, task: asyncio.Task) -> None:
        rec = self._runs.get(run_id)
        if rec is not None:
            rec.task = task
            # If the run was already cancelled before the task was attached,
            # cancel the task immediately so it doesn't run to completion.
            if rec.status in TERMINAL_STATUSES and not task.done():
                task.cancel()

    # ----- pub/sub -----

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        """Append event to buffer and fan out to all live subscribers.

        Also updates status/slug/error based on event type so polling
        consumers can see consistent state without parsing the buffer.
        """
        rec = self._runs.get(run_id)
        if rec is None:
            return
        rec.events.append(event)
        rec.updated_at = _now_iso()

        etype = event.get("type")
        payload = event.get("payload") or {}
        if etype == "run_started" and rec.status == "pending":
            rec.status = "running"
        elif etype == "done":
            slug = payload.get("slug")
            if slug:
                rec.report_slug = str(slug)
            if rec.status not in TERMINAL_STATUSES:
                rec.status = "completed"
        elif etype == "error":
            rec.error = str(payload.get("message") or "unknown error")
            if rec.status not in TERMINAL_STATUSES:
                rec.status = "failed"

        for q in list(rec.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - unbounded queues
                log.warning("dropping event for run %s: subscriber queue full", run_id)

    def mark_failed(self, run_id: str, message: str) -> None:
        rec = self._runs.get(run_id)
        if rec is None:
            return
        if rec.status in TERMINAL_STATUSES:
            return
        rec.error = message
        rec.status = "failed"
        rec.updated_at = _now_iso()
        self.publish(run_id, {"type": "error", "payload": {"message": message}})

    def mark_cancelled(self, run_id: str) -> None:
        rec = self._runs.get(run_id)
        if rec is None:
            return
        if rec.status in TERMINAL_STATUSES:
            return
        rec.status = "cancelled"
        rec.updated_at = _now_iso()
        self.publish(
            run_id,
            {"type": "error", "payload": {"message": "Run cancelled by user."}},
        )

    async def subscribe(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """Replay buffered events, then yield live ones until terminal.

        After yielding the final buffered event for a terminal run, the
        iterator ends. While the run is in-flight, the iterator blocks
        on the per-subscriber queue.
        """
        rec = self._runs.get(run_id)
        if rec is None:
            return

        replay_len = len(rec.events)
        terminal_at_attach = rec.status in TERMINAL_STATUSES

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        if not terminal_at_attach:
            rec.subscribers.append(queue)

        try:
            for evt in rec.events[:replay_len]:
                yield evt

            if terminal_at_attach:
                return

            while True:
                evt = await queue.get()
                yield evt
                if rec.status in TERMINAL_STATUSES and queue.empty():
                    return
        finally:
            if queue in rec.subscribers:
                rec.subscribers.remove(queue)

    def cancel(self, run_id: str) -> bool:
        """Cancel the underlying task (if any) and mark the run cancelled.

        Returns True if a run was found and a cancellation initiated,
        False if the run is unknown or already terminal.

        This method is **non-blocking**: it calls task.cancel() and
        marks the run cancelled immediately, without awaiting the task.
        The worker coroutine will handle CancelledError asynchronously
        and finalize any cleanup (mark_cancelled from the worker is a
        no-op since the status is already terminal).
        """
        rec = self._runs.get(run_id)
        if rec is None or rec.status in TERMINAL_STATUSES:
            return False
        task = rec.task
        if task is not None and not task.done():
            task.cancel()
        self.mark_cancelled(run_id)
        return True


REGISTRY = RunRegistry()
