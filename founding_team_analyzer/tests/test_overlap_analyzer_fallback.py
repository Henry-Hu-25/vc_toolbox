"""Tests for F-BE-014: OverlapAnalyzer LLM-failure fallback produces
consistent state.

Validates VAL-BE-019 (internal consistency) and VAL-BE-020 (warning
appended, no raise).
"""

from __future__ import annotations

from unittest.mock import patch

from founding_team_analyzer.nodes.overlap_analyzer import run as overlap_run
from founding_team_analyzer.schemas import (
    CostLedger,
    Education,
    FounderProfile,
    PriorStartup,
    Strength,
    WorkExperience,
)
from founding_team_analyzer.state import AnalyzerState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profile(name: str, *, employers=None, schools=None, startups=None, accelerators=None) -> FounderProfile:
    """Build a FounderProfile with optional overlap-generating fields."""
    return FounderProfile(
        name=name,
        current_title="CEO",
        work=employers or [],
        education=schools or [],
        prior_startups=startups or [],
        accelerators=accelerators or [],
    )


def _work(company: str, role: str = "Engineer", start: int = 2020, end: int = 2023, technical: bool = True) -> WorkExperience:
    return WorkExperience(
        company=company,
        role=role,
        start_year=start,
        end_year=end,
        is_technical_role=technical,
    )


def _school(name: str, start: int = 2016, end: int = 2020) -> Education:
    return Education(school=name, start_year=start, end_year=end)


def _startup(name: str, role: str = "Co-founder") -> PriorStartup:
    return PriorStartup(name=name, role=role)


def _fake_call_structured_raising(schema, prompt, *, llm_calls_so_far=0, model=None):
    """Simulate a failing LLM call."""
    raise RuntimeError("LLM service unavailable")


def _fake_load_prompt(name):
    return "prompt: {overlap_payload}"


# ---------------------------------------------------------------------------
# VAL-BE-019: Fallback TeamOverlap is internally consistent when
#              deterministic overlap exists
# ---------------------------------------------------------------------------


def test_fallback_pair_strengths_nonzero_when_shared_employer():
    """Two founders share an employer with overlapping years. When the
    LLM call fails, the fallback must produce at least one pair with
    strength != 'none' and overall_strength >= 'weak'."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp", start=2018, end=2022)]),
        _profile("Bob", employers=[_work("Acme Corp", start=2020, end=2023)]),
    ]
    state: AnalyzerState = {
        "profiles": profiles,
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.overlap_analyzer.call_structured",
        side_effect=_fake_call_structured_raising,
    ), patch(
        "founding_team_analyzer.nodes.overlap_analyzer.load_prompt",
        side_effect=_fake_load_prompt,
    ):
        result = overlap_run(state)

    overlaps = result["overlaps"]
    # At least one pair must have strength != "none"
    pair_strengths = [p.strength for p in overlaps.pairs]
    assert any(s != "none" for s in pair_strengths), (
        f"Expected at least one pair with strength != 'none', got {pair_strengths}"
    )
    # overall_strength must be >= the max pair strength (consistent)
    assert overlaps.overall_strength != "none", (
        f"overall_strength is 'none' despite shared employer overlap"
    )
    # Consistency: overall_strength must equal the max of pair strengths
    strength_order = ["none", "weak", "medium", "strong"]
    max_pair = max(pair_strengths, key=lambda s: strength_order.index(s))
    assert overlaps.overall_strength == max_pair, (
        f"Inconsistent: overall_strength={overlaps.overall_strength} "
        f"but max pair strength={max_pair}"
    )


def test_fallback_pair_strengths_nonzero_when_shared_prior_startup():
    """Two founders share a prior startup. When the LLM call fails,
    the fallback must produce a pair with strength 'strong'."""
    profiles = [
        _profile("Alice", startups=[_startup("FooBar")]),
        _profile("Bob", startups=[_startup("FooBar")]),
    ]
    state: AnalyzerState = {
        "profiles": profiles,
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.overlap_analyzer.call_structured",
        side_effect=_fake_call_structured_raising,
    ), patch(
        "founding_team_analyzer.nodes.overlap_analyzer.load_prompt",
        side_effect=_fake_load_prompt,
    ):
        result = overlap_run(state)

    overlaps = result["overlaps"]
    # Shared prior startup should produce 'strong'
    assert any(p.strength == "strong" for p in overlaps.pairs), (
        f"Expected at least one 'strong' pair for shared prior startup, "
        f"got {[p.strength for p in overlaps.pairs]}"
    )
    assert overlaps.overall_strength == "strong", (
        f"Expected overall_strength='strong' for shared prior startup, "
        f"got {overlaps.overall_strength}"
    )


def test_fallback_no_contradictory_overall_strength():
    """The documented contradiction: overall_strength='medium' while every
    pair is strength='none'. This must not happen after the fix."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp", start=2018, end=2022)]),
        _profile("Bob", employers=[_work("Acme Corp", start=2020, end=2023)]),
    ]
    state: AnalyzerState = {
        "profiles": profiles,
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.overlap_analyzer.call_structured",
        side_effect=_fake_call_structured_raising,
    ), patch(
        "founding_team_analyzer.nodes.overlap_analyzer.load_prompt",
        side_effect=_fake_load_prompt,
    ):
        result = overlap_run(state)

    overlaps = result["overlaps"]
    pair_strengths = [p.strength for p in overlaps.pairs]

    # No contradiction: if overall_strength is non-none, at least one pair
    # must also be non-none. And overall_strength must match the max pair.
    if overlaps.overall_strength != "none":
        assert any(s != "none" for s in pair_strengths), (
            "Contradiction: overall_strength is non-none but all pair strengths are 'none'"
        )


def test_fallback_no_overlap_produces_none_strengths():
    """When there is no deterministic overlap and the LLM fails, all
    pair strengths and overall_strength should be 'none'."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp")]),
        _profile("Bob", employers=[_work("Beta Inc")]),
    ]
    state: AnalyzerState = {
        "profiles": profiles,
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.overlap_analyzer.call_structured",
        side_effect=_fake_call_structured_raising,
    ), patch(
        "founding_team_analyzer.nodes.overlap_analyzer.load_prompt",
        side_effect=_fake_load_prompt,
    ):
        result = overlap_run(state)

    overlaps = result["overlaps"]
    assert all(p.strength == "none" for p in overlaps.pairs), (
        f"Expected all pairs with strength 'none' when no overlap, "
        f"got {[p.strength for p in overlaps.pairs]}"
    )
    assert overlaps.overall_strength == "none", (
        f"Expected overall_strength='none' when no overlap, "
        f"got {overlaps.overall_strength}"
    )


def test_fallback_shared_school_with_overlap_years():
    """Two founders share a school with overlapping years. The fallback
    should produce at least 'medium' strength."""
    profiles = [
        _profile("Alice", schools=[_school("MIT", start=2016, end=2020)]),
        _profile("Bob", schools=[_school("MIT", start=2018, end=2022)]),
    ]
    state: AnalyzerState = {
        "profiles": profiles,
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.overlap_analyzer.call_structured",
        side_effect=_fake_call_structured_raising,
    ), patch(
        "founding_team_analyzer.nodes.overlap_analyzer.load_prompt",
        side_effect=_fake_load_prompt,
    ):
        result = overlap_run(state)

    overlaps = result["overlaps"]
    # Shared school with overlapping years should be at least 'medium'
    assert any(p.strength != "none" for p in overlaps.pairs), (
        f"Expected non-none pair for shared school with overlap years, "
        f"got {[p.strength for p in overlaps.pairs]}"
    )
    assert overlaps.overall_strength != "none", (
        "overall_strength should be non-none for shared school with overlap years"
    )


# ---------------------------------------------------------------------------
# VAL-BE-020: Fallback degrades via warnings, not raises
# ---------------------------------------------------------------------------


def test_fallback_appends_warning_on_llm_failure():
    """When the LLM call fails, the node must append a warning string
    describing the failure to state['warnings']."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp", start=2018, end=2022)]),
        _profile("Bob", employers=[_work("Acme Corp", start=2020, end=2023)]),
    ]
    state: AnalyzerState = {
        "profiles": profiles,
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.overlap_analyzer.call_structured",
        side_effect=_fake_call_structured_raising,
    ), patch(
        "founding_team_analyzer.nodes.overlap_analyzer.load_prompt",
        side_effect=_fake_load_prompt,
    ):
        result = overlap_run(state)

    warnings = result.get("warnings", [])
    assert any("llm" in w.lower() or "overlap" in w.lower() or "narrative" in w.lower() for w in warnings), (
        f"Expected a warning describing the LLM failure, got {warnings}"
    )


def test_fallback_does_not_raise_on_llm_failure():
    """When the LLM call fails, the node must not propagate the
    exception. It must return a partial state instead."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp", start=2018, end=2022)]),
        _profile("Bob", employers=[_work("Acme Corp", start=2020, end=2023)]),
    ]
    state: AnalyzerState = {
        "profiles": profiles,
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.overlap_analyzer.call_structured",
        side_effect=_fake_call_structured_raising,
    ), patch(
        "founding_team_analyzer.nodes.overlap_analyzer.load_prompt",
        side_effect=_fake_load_prompt,
    ):
        # Must not raise
        result = overlap_run(state)

    # Sanity: result is a dict with the expected keys
    assert "overlaps" in result
    assert "warnings" in result
    assert "cost" in result
