from founding_team_analyzer.schemas import (
    Company,
    CostLedger,
    Education,
    Founder,
    FounderProfile,
    TeamScore,
    WorkExperience,
)


def test_company_minimum_fields():
    c = Company(name="Acme")
    assert c.name == "Acme"
    assert c.source_urls == []


def test_founder_profile_defaults_safe():
    p = FounderProfile(name="Jane Doe", current_title="CEO")
    assert p.confidence == "low"
    assert p.education == []
    assert p.work == []


def test_education_and_work():
    e = Education(school="MIT", start_year=2010, end_year=2014)
    w = WorkExperience(company="Google", role="SWE", start_year=2014, end_year=2018,
                       is_founder_role=False, is_technical_role=True)
    assert e.school == "MIT"
    assert w.is_technical_role


def test_cost_ledger_merge():
    a = CostLedger(llm_calls=2, tavily_searches=1)
    b = CostLedger(llm_calls=3, tavily_extracts=2)
    merged = a.merged(b)
    assert merged.llm_calls == 5
    assert merged.tavily_searches == 1
    assert merged.tavily_extracts == 2


def test_team_score_clamps():
    score = TeamScore(criteria=[])
    assert score.tier == "Mixed"
    assert score.overall_0_100 == 0.0
