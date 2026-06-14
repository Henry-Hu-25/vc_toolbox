"""Additional overlap_analyzer fallback tests: three-founder scenarios,
shared accelerators, and mixed overlap types.

Broadens coverage for VAL-BE-019 and VAL-BE-020 beyond the core
two-founder tests in test_overlap_analyzer_fallback.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

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


def _accelerator(name: str) -> str:
    return name


def _fake_call_structured_raising(schema, prompt, *, llm_calls_so_far=0, model=None):
    raise RuntimeError("LLM service unavailable")


def _fake_load_prompt(name):
    return "prompt: {overlap_payload}"


# ---------------------------------------------------------------------------
# Three-founder overlap with LLM failure
# ---------------------------------------------------------------------------


def test_three_founders_shared_employer_llm_failure():
    """Three founders, two share an employer.  On LLM failure, the
    fallback must produce consistent state: the shared pair should have
    strength != 'none' and overall_strength must match the max pair."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp", start=2018, end=2022)]),
        _profile("Bob", employers=[_work("Acme Corp", start=2020, end=2023)]),
        _profile("Carol", employers=[_work("Beta Inc", start=2019, end=2021)]),
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

    # Alice-Bob share an employer -> should be non-none
    # Alice-Carol and Bob-Carol have no overlap -> should be 'none'
    # There are C(3,2) = 3 pairs
    assert len(overlaps.pairs) == 3, f"Expected 3 pairs for 3 founders, got {len(overlaps.pairs)}"

    non_none_count = sum(1 for s in pair_strengths if s != "none")
    assert non_none_count >= 1, f"At least one pair should be non-none, got {pair_strengths}"

    # Consistency check: overall_strength matches max pair
    strength_order = ["none", "weak", "medium", "strong"]
    max_pair = max(pair_strengths, key=lambda s: strength_order.index(s))
    assert overlaps.overall_strength == max_pair, (
        f"Inconsistent: overall_strength={overlaps.overall_strength}, max pair={max_pair}"
    )


def test_three_founders_all_share_same_employer_llm_failure():
    """Three founders all share the same employer with overlapping years.
    All pairs should be non-none on fallback."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp", start=2018, end=2022)]),
        _profile("Bob", employers=[_work("Acme Corp", start=2019, end=2023)]),
        _profile("Carol", employers=[_work("Acme Corp", start=2020, end=2024)]),
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
    assert len(pair_strengths) == 3

    # All 3 pairs share an employer -> all should be non-none
    assert all(s != "none" for s in pair_strengths), (
        f"All pairs should be non-none for shared employer, got {pair_strengths}"
    )
    assert overlaps.overall_strength != "none"


# ---------------------------------------------------------------------------
# Shared accelerator overlap
# ---------------------------------------------------------------------------


def test_shared_accelerator_llm_failure():
    """Two founders share an accelerator (e.g., Y Combinator).
    On LLM failure, the fallback should detect this overlap."""
    profiles = [
        _profile("Alice", accelerators=["Y Combinator"]),
        _profile("Bob", accelerators=["Y Combinator"]),
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
    # Shared accelerator should produce at least a non-none strength
    pair_strengths = [p.strength for p in overlaps.pairs]
    assert any(s != "none" for s in pair_strengths), (
        f"Shared accelerator should produce non-none pair, got {pair_strengths}"
    )
    assert overlaps.overall_strength != "none"


# ---------------------------------------------------------------------------
# Mixed overlap types: employer + school + startup
# ---------------------------------------------------------------------------


def test_mixed_overlap_types_llm_failure():
    """Two founders share an employer, a school, AND a prior startup.
    The fallback should produce a 'strong' pair (shared prior startup
    is the strongest signal)."""
    profiles = [
        _profile(
            "Alice",
            employers=[_work("Acme Corp", start=2018, end=2022)],
            schools=[_school("MIT", start=2016, end=2020)],
            startups=[_startup("FooBar")],
        ),
        _profile(
            "Bob",
            employers=[_work("Acme Corp", start=2020, end=2023)],
            schools=[_school("MIT", start=2018, end=2022)],
            startups=[_startup("FooBar")],
        ),
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
    assert overlaps.overall_strength == "strong"


# ---------------------------------------------------------------------------
# Warning message content on LLM failure
# ---------------------------------------------------------------------------


def test_warning_message_describes_overlap_llm_failure():
    """The warning appended on LLM failure must mention the overlap
    analyzer and/or the LLM failure."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp")]),
        _profile("Bob", employers=[_work("Acme Corp")]),
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
    # The warning should reference either LLM failure or overlap analysis
    assert len(warnings) > 0, "Expected at least one warning on LLM failure"
    assert any("llm" in w.lower() or "overlap" in w.lower() or "narrative" in w.lower() for w in warnings), (
        f"Warning should describe the LLM/overlap failure, got {warnings}"
    )


def test_node_returns_only_own_warnings_on_llm_failure():
    """The overlap_analyzer node returns only its own new warnings in the
    partial state dict.  LangGraph's Annotated[list[str], operator.add]
    reducer appends these to the existing state warnings, so the node
    must NOT duplicate the pre-existing warnings in its return value."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp")]),
        _profile("Bob", employers=[_work("Acme Corp")]),
    ]
    state: AnalyzerState = {
        "profiles": profiles,
        "warnings": ["pre-existing warning"],
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
    # The node should return only its own LLM-failure warning,
    # not the pre-existing one from the input state (the reducer
    # handles merging).
    assert len(warnings) >= 1, (
        f"Expected at least 1 new warning, got {len(warnings)}"
    )
    # The node's own warning should describe the LLM failure
    assert any("llm" in w.lower() or "overlap" in w.lower() or "narrative" in w.lower() for w in warnings), (
        f"Expected LLM-failure warning in node output, got {warnings}"
    )
    # The pre-existing warning should NOT be duplicated in the node output
    assert "pre-existing warning" not in warnings, (
        f"Pre-existing warning should not be duplicated in node output, got {warnings}"
    )


# ---------------------------------------------------------------------------
# Cost ledger update on LLM failure
# ---------------------------------------------------------------------------


def test_cost_ledger_on_llm_failure():
    """When the LLM call fails, the cost ledger should still be returned
    in the partial state (even if no LLM calls were completed)."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp")]),
        _profile("Bob", employers=[_work("Acme Corp")]),
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

    assert "cost" in result, "Cost ledger must be present in partial state"
    # Cost may be zero (no LLM calls succeeded), but it must exist
    assert isinstance(result["cost"], CostLedger), (
        f"Cost must be a CostLedger, got {type(result['cost'])}"
    )


# ---------------------------------------------------------------------------
# Single founder: no pairs possible
# ---------------------------------------------------------------------------


def test_single_founder_no_pairs():
    """With only one founder, there are no pairs to analyze.
    The node should return empty pairs and overall_strength='none'."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp")]),
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
    assert len(overlaps.pairs) == 0, (
        f"Expected 0 pairs for single founder, got {len(overlaps.pairs)}"
    )
    assert overlaps.overall_strength == "none"


# ---------------------------------------------------------------------------
# Non-overlapping years at same employer
# ---------------------------------------------------------------------------


def test_same_employer_non_overlapping_years():
    """Two founders worked at the same company but at different, non-overlapping
    times. The fallback should classify this as 'weak' (shared employer but no
    year overlap), not 'medium' or 'strong'. overall_strength must be
    consistent with the pair strengths."""
    profiles = [
        _profile("Alice", employers=[_work("Acme Corp", start=2010, end=2015)]),
        _profile("Bob", employers=[_work("Acme Corp", start=2018, end=2023)]),
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
    # Non-overlapping years at same employer -> 'weak' (shared employer
    # but no year overlap).  This is NOT 'none' because they still share
    # the same employer; it's NOT 'medium' because there are no
    # overlapping years.
    assert pair_strengths == ["weak"], (
        f"Non-overlapping same employer should be 'weak', got {pair_strengths}"
    )
    # overall_strength must be consistent with pair strengths
    assert overlaps.overall_strength == "weak", (
        f"overall_strength must match max pair strength, "
        f"got {overlaps.overall_strength} with pairs {pair_strengths}"
    )
