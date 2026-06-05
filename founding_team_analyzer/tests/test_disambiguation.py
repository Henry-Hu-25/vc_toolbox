from founding_team_analyzer.nodes.founder_researcher import _passes_disambiguation_gate
from founding_team_analyzer.schemas import Company, Founder
from founding_team_analyzer.tools.search import SearchResult


def _result(title: str, url: str, content: str) -> SearchResult:
    return SearchResult(title=title, url=url, content=content)


def test_passes_when_name_and_company_co_mentioned():
    founder = Founder(name="Akash Sharma")
    company = Company(name="Vellum AI", website="https://www.vellum.ai")
    r = _result(
        "Akash Sharma at Vellum AI",
        "https://example.com/akash",
        "Akash Sharma joined Vellum AI in 2023 as CEO.",
    )
    assert _passes_disambiguation_gate(r, founder, company)


def test_rejects_same_name_different_company():
    founder = Founder(name="Akash Sharma")
    company = Company(name="Vellum AI", website="https://www.vellum.ai")
    r = _result(
        "Akash Sharma - Admissions Officer at CDI",
        "https://cdi.example.com/team",
        "Akash Sharma has worked in college admissions for 15 years.",
    )
    assert not _passes_disambiguation_gate(r, founder, company)


def test_linkedin_carveout_when_exact_url_matches():
    founder = Founder(
        name="Sidd Seethepalli",
        linkedin_url="https://www.linkedin.com/in/siddseethepalli",
    )
    company = Company(name="Vellum AI")
    r = _result(
        "Sidd's LinkedIn",
        "https://www.linkedin.com/in/siddseethepalli",
        "Sidd",  # very short snippet, but URL matches authoritative one
    )
    assert _passes_disambiguation_gate(r, founder, company)


def test_linkedin_carveout_when_slug_matches():
    founder = Founder(
        name="Sidd Seethepalli",
        linkedin_url="https://www.linkedin.com/in/siddseethepalli/",
    )
    company = Company(name="Vellum AI")
    r = _result(
        "Sidd",
        "https://www.linkedin.com/in/siddseethepalli",
        "Sidd",
    )
    assert _passes_disambiguation_gate(r, founder, company)


def test_rejects_when_neither_company_nor_known_linkedin():
    founder = Founder(name="Akash Sharma")
    company = Company(name="Vellum AI")
    r = _result(
        "Akash Sharma realtor",
        "https://realtors.example.com/akash",
        "Akash Sharma has been selling homes since 1998.",
    )
    assert not _passes_disambiguation_gate(r, founder, company)


def test_rejects_missing_url_or_name():
    founder = Founder(name="")
    r = _result("anything", "https://x.com", "anything")
    assert not _passes_disambiguation_gate(r, founder, None)
