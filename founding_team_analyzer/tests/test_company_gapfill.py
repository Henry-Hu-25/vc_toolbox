from unittest.mock import patch

from founding_team_analyzer.nodes.company_profiler import _gap_fill
from founding_team_analyzer.schemas import Company, CostLedger
from founding_team_analyzer.tools.search import SearchResult


def _fake_search(query, max_results=4, search_depth="basic"):
    if "founded year" in query:
        return [
            SearchResult(
                title="Crunchbase",
                url="https://crunchbase.com/x",
                content="X was founded in 2022.",
            )
        ]
    if "headquarters" in query:
        return [
            SearchResult(
                title="LinkedIn",
                url="https://linkedin.com/company/x",
                content="HQ in San Francisco, CA.",
            )
        ]
    return []


def test_gap_fill_no_op_when_all_present():
    company = Company(
        name="X",
        founded_year=2022,
        hq_location="San Francisco",
        sector="AI",
        sub_sector="Infra",
    )
    refined, cost, warnings = _gap_fill(company)
    assert refined.founded_year == 2022
    assert cost.tavily_searches == 0
    assert warnings == []


def test_gap_fill_calls_searches_and_llm_for_missing_fields():
    company = Company(name="X", founded_year=None, hq_location=None, sector="AI")

    filled = Company(
        name="X",
        founded_year=2022,
        hq_location="San Francisco",
        sector="AI",
    )

    with patch(
        "founding_team_analyzer.nodes.company_profiler.search_tool.search",
        side_effect=_fake_search,
    ), patch(
        "founding_team_analyzer.nodes.company_profiler.call_structured",
        return_value=(filled, CostLedger(llm_calls=1)),
    ):
        refined, cost, warnings = _gap_fill(company)

    assert refined.founded_year == 2022
    assert refined.hq_location == "San Francisco"
    assert cost.llm_calls == 1
    assert cost.tavily_searches >= 2
    assert warnings == []
