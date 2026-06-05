"""Tests for F-BE-006: CompanyProfiler cost ledger counts API invocations,
not deduped result URLs.

Validates VAL-BE-012 (the pytest layer).
"""

from __future__ import annotations

from unittest.mock import patch

from founding_team_analyzer.nodes.company_profiler import run as profiler_run
from founding_team_analyzer.schemas import Company, CostLedger
from founding_team_analyzer.tools.search import SearchResult
from founding_team_analyzer.state import AnalyzerState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_search_result(idx: int, query_tag: str) -> SearchResult:
    """Return a fake SearchResult with a unique URL per invocation."""
    return SearchResult(
        title=f"Result {idx} for {query_tag}",
        url=f"https://example.com/{query_tag}/result-{idx}",
        content=f"Content for result {idx} on query {query_tag}",
    )


def _fake_search_factory(results_per_call: int = 5):
    """Return a fake search function that records invocation count and
    returns `results_per_call` unique results each time."""
    calls = []

    def _fake_search(query, max_results=5, search_depth="basic"):
        calls.append(query)
        return [
            _make_search_result(i, f"inv{len(calls)}")
            for i in range(results_per_call)
        ]

    return _fake_search, calls


def _fake_extract(url):
    """Fake extract that returns minimal content."""
    from founding_team_analyzer.tools.search import ExtractResult
    return ExtractResult(url=url, content="Extracted content", raw={})


def _fake_call_structured(schema, prompt, *, llm_calls_so_far=0, model=None):
    """Fake LLM call that returns a fully populated Company + 1 LLM call cost.

    All gap-fill fields are filled so _gap_fill becomes a no-op.
    """
    company = Company(
        name="TestCo",
        website="https://test.co",
        founded_year=2020,
        hq_location="San Francisco",
        sector="AI",
        sub_sector="Infra",
    )
    cost = CostLedger(llm_calls=1)
    return company, cost


# ---------------------------------------------------------------------------
# VAL-BE-012: tavily_searches counts invocations, not deduped result URLs
# ---------------------------------------------------------------------------


def test_profiler_tavily_searches_counts_invocations_not_urls():
    """Free-text input triggers 4 search() calls, each returning 5 results.
    The cost ledger must report tavily_searches == 4 (invocations),
    not 20 (4 * 5 URLs) or the deduped URL count."""
    fake_search, search_calls = _fake_search_factory(results_per_call=5)

    state: AnalyzerState = {
        "raw_input": "TestCo",
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.company_profiler.search_tool.search",
        side_effect=fake_search,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.search_tool.extract",
        side_effect=_fake_extract,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.call_structured",
        side_effect=_fake_call_structured,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.load_prompt",
        return_value="prompt: {raw_input} {input_type} {sources_block}",
    ):
        result = profiler_run(state)

    # Verify that search was actually called 4 times (free-text path)
    assert len(search_calls) == 4, (
        f"Expected 4 search() invocations for free-text input, got {len(search_calls)}"
    )

    cost = result.get("cost", CostLedger())
    assert isinstance(cost, CostLedger)

    # The key assertion: tavily_searches must equal the number of
    # search() invocations (4), NOT the total number of result URLs
    # (20 = 4*5) or the deduped URL count.
    assert cost.tavily_searches == 4, (
        f"Expected tavily_searches == 4 (invocation count), "
        f"got {cost.tavily_searches}. "
        f"search() was called {len(search_calls)} times, "
        f"each returning 5 results."
    )


def test_profiler_url_input_tavily_searches_counts_invocations():
    """URL input triggers 1 search() call + 1 extract. The cost ledger
    must report tavily_searches == 1, not the number of search results."""
    fake_search, search_calls = _fake_search_factory(results_per_call=3)

    state: AnalyzerState = {
        "raw_input": "https://test.co",
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.company_profiler.search_tool.search",
        side_effect=fake_search,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.search_tool.extract",
        side_effect=_fake_extract,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.call_structured",
        side_effect=_fake_call_structured,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.load_prompt",
        return_value="prompt: {raw_input} {input_type} {sources_block}",
    ):
        result = profiler_run(state)

    assert len(search_calls) == 1, (
        f"Expected 1 search() invocation for URL input, got {len(search_calls)}"
    )

    cost = result.get("cost", CostLedger())
    assert isinstance(cost, CostLedger)
    assert cost.tavily_searches == 1, (
        f"Expected tavily_searches == 1 (invocation count), "
        f"got {cost.tavily_searches}"
    )


def test_profiler_linkedin_input_tavily_searches_counts_invocations():
    """LinkedIn input triggers 2 search() calls. The cost ledger must
    report tavily_searches == 2, not the number of search results."""
    fake_search, search_calls = _fake_search_factory(results_per_call=3)

    state: AnalyzerState = {
        "raw_input": "https://linkedin.com/company/testco",
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.company_profiler.search_tool.search",
        side_effect=fake_search,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.search_tool.extract",
        side_effect=_fake_extract,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.call_structured",
        side_effect=_fake_call_structured,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.load_prompt",
        return_value="prompt: {raw_input} {input_type} {sources_block}",
    ):
        result = profiler_run(state)

    assert len(search_calls) == 2, (
        f"Expected 2 search() invocations for LinkedIn input, got {len(search_calls)}"
    )

    cost = result.get("cost", CostLedger())
    assert isinstance(cost, CostLedger)
    assert cost.tavily_searches == 2, (
        f"Expected tavily_searches == 2 (invocation count), "
        f"got {cost.tavily_searches}"
    )


def test_profiler_deduped_urls_do_not_overcount_tavily_searches():
    """When multiple search() calls return overlapping URLs, the deduped
    source list may be shorter than the total results, but tavily_searches
    must still equal the invocation count (not the deduped URL count)."""
    call_count = 0

    def _fake_search_with_overlapping_urls(query, max_results=5, search_depth="basic"):
        nonlocal call_count
        call_count += 1
        # Return the same URLs across invocations to simulate overlap
        return [
            SearchResult(
                title=f"Shared result {i}",
                url=f"https://example.com/shared/result-{i}",
                content=f"Content {i}",
            )
            for i in range(3)
        ]

    state: AnalyzerState = {
        "raw_input": "TestCo",
        "warnings": [],
        "cost": CostLedger(),
        "self_critique_disabled": False,
    }

    with patch(
        "founding_team_analyzer.nodes.company_profiler.search_tool.search",
        side_effect=_fake_search_with_overlapping_urls,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.search_tool.extract",
        side_effect=_fake_extract,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.call_structured",
        side_effect=_fake_call_structured,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.load_prompt",
        return_value="prompt: {raw_input} {input_type} {sources_block}",
    ):
        result = profiler_run(state)

    # 4 invocations for free-text, each returning 3 identical URLs
    # Deduped sources would have only 3 unique URLs, but we must
    # count 4 invocations, not 3.
    assert call_count == 4

    cost = result.get("cost", CostLedger())
    assert isinstance(cost, CostLedger)
    assert cost.tavily_searches == 4, (
        f"Expected tavily_searches == 4 (invocation count despite URL overlap), "
        f"got {cost.tavily_searches}. "
        f"Deduped URLs would be ~3, invocations were 4."
    )
