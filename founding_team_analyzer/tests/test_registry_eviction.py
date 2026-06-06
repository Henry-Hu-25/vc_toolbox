"""Tests for RunRegistry eviction: cap at configurable max, evict oldest terminal runs."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from founding_team_analyzer.runs import RunRegistry, TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_terminal(reg: RunRegistry, run_id: str, status: str = "completed") -> None:
    """Push the run through to a terminal state via publish."""
    reg.publish(run_id, {"type": "run_started", "payload": {}})
    if status == "completed":
        reg.publish(run_id, {"type": "done", "payload": {"slug": run_id[:8]}})
    elif status == "failed":
        reg.mark_failed(run_id, "test failure")
    elif status == "cancelled":
        reg.mark_cancelled(run_id)


# ---------------------------------------------------------------------------
# VAL-BE-015: Terminal-run population is bounded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_caps_at_max_and_evicts_oldest_terminal():
    """After exceeding max_runs, oldest terminal runs are evicted."""
    cap = 5
    reg = RunRegistry(max_runs=cap)

    # Create cap + 5 terminal runs
    ids = []
    for i in range(cap + 5):
        rec = reg.create(f"Company-{i}")
        ids.append(rec.id)
        _make_terminal(reg, rec.id, "completed")

    # Registry size should be at most cap
    all_runs = reg.list_all()
    assert len(all_runs) <= cap

    # The oldest terminal runs (first ones created) should be evicted
    # Only the most recent `cap` terminal runs should remain
    remaining_ids = {r.id for r in all_runs}
    # First 5 runs should be evicted (they were created first)
    for old_id in ids[:5]:
        assert reg.get(old_id) is None, f"Run {old_id} should have been evicted"
    # Last 5 runs should remain
    for new_id in ids[5:]:
        assert reg.get(new_id) is not None, f"Run {new_id} should still be present"


@pytest.mark.asyncio
async def test_eviction_prefers_oldest_by_updated_at():
    """When evicting, the terminal run with the oldest updated_at is removed first."""
    cap = 3
    reg = RunRegistry(max_runs=cap)

    # Create 3 terminal runs to fill the cap
    r1 = reg.create("Old")
    _make_terminal(reg, r1.id, "completed")

    r2 = reg.create("Middle")
    _make_terminal(reg, r2.id, "failed")

    r3 = reg.create("Recent")
    _make_terminal(reg, r3.id, "completed")

    # Now create a 4th terminal run, which should trigger eviction of r1 (oldest)
    r4 = reg.create("Newest")
    _make_terminal(reg, r4.id, "completed")

    assert reg.get(r1.id) is None, "Oldest terminal run should be evicted"
    assert reg.get(r2.id) is not None
    assert reg.get(r3.id) is not None
    assert reg.get(r4.id) is not None


# ---------------------------------------------------------------------------
# VAL-BE-016: In-flight runs are not evicted by the cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_flight_runs_not_evicted():
    """In-flight (non-terminal) runs are never evicted, even when cap is exceeded."""
    cap = 3
    reg = RunRegistry(max_runs=cap)

    # Create 1 in-flight run (never pushed to terminal)
    inflight = reg.create("InFlight")
    reg.publish(inflight.id, {"type": "run_started", "payload": {}})
    assert inflight.status == "running"

    # Create cap terminal runs to exceed the limit
    for i in range(cap):
        rec = reg.create(f"Terminal-{i}")
        _make_terminal(reg, rec.id, "completed")

    # In-flight run must still be present
    assert reg.get(inflight.id) is not None, "In-flight run should not be evicted"
    assert reg.get(inflight.id).status == "running"

    # Total runs = in-flight + up-to-cap terminal runs
    all_runs = reg.list_all()
    # We have 1 in-flight + cap terminal, but some terminal may be evicted
    # The in-flight one must always be there
    inflight_found = any(r.id == inflight.id for r in all_runs)
    assert inflight_found, "In-flight run must appear in list_all()"


@pytest.mark.asyncio
async def test_all_in_flight_runs_preserved_when_all_terminal_evicted():
    """Even if all terminal runs must be evicted to make room, in-flight runs stay."""
    cap = 2
    reg = RunRegistry(max_runs=cap)

    # Fill cap with in-flight runs
    inf1 = reg.create("Inf1")
    reg.publish(inf1.id, {"type": "run_started", "payload": {}})
    inf2 = reg.create("Inf2")
    reg.publish(inf2.id, {"type": "run_started", "payload": {}})

    # Now add terminal runs beyond the cap
    for i in range(5):
        rec = reg.create(f"Terminal-{i}")
        _make_terminal(reg, rec.id, "completed")

    # Both in-flight runs must still be present
    assert reg.get(inf1.id) is not None
    assert reg.get(inf2.id) is not None
    assert reg.get(inf1.id).status == "running"
    assert reg.get(inf2.id).status == "running"


# ---------------------------------------------------------------------------
# Evicted run returns 404 via get()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evicted_run_returns_none_on_get():
    """An evicted run_id returns None from get(), which should result in a 404."""
    cap = 2
    reg = RunRegistry(max_runs=cap)

    rec1 = reg.create("Evicted")
    _make_terminal(reg, rec1.id, "completed")

    rec2 = reg.create("Survivor")
    _make_terminal(reg, rec2.id, "completed")

    # rec1 should still be here
    assert reg.get(rec1.id) is not None

    # Now push past the cap
    rec3 = reg.create("Newcomer")
    _make_terminal(reg, rec3.id, "completed")

    # rec1 (oldest terminal) should be evicted
    assert reg.get(rec1.id) is None
    # Others should remain
    assert reg.get(rec2.id) is not None
    assert reg.get(rec3.id) is not None


# ---------------------------------------------------------------------------
# Default max_runs is 100
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_max_runs_is_100():
    """The default RunRegistry uses max_runs=100."""
    reg = RunRegistry()
    assert reg._max_runs == 100


# ---------------------------------------------------------------------------
# Config integration: FTA_MAX_REGISTRY_RUNS env var
# ---------------------------------------------------------------------------


def test_settings_max_registry_runs_default(monkeypatch):
    """Settings has max_registry_runs with a default of 100."""
    monkeypatch.delenv("FTA_MAX_REGISTRY_RUNS", raising=False)
    from founding_team_analyzer.config import Settings
    s = Settings.load()
    assert s.max_registry_runs == 100


def test_settings_max_registry_runs_from_env(monkeypatch):
    """FTA_MAX_REGISTRY_RUNS env var is honored."""
    monkeypatch.setenv("FTA_MAX_REGISTRY_RUNS", "50")
    from founding_team_analyzer.config import Settings
    s = Settings.load()
    assert s.max_registry_runs == 50
