from founding_team_analyzer.schemas import (
    Education,
    FounderProfile,
    PriorStartup,
    WorkExperience,
    is_placeholder_name,
)


def test_placeholder_detector():
    assert is_placeholder_name("Unspecified Institution")
    assert is_placeholder_name("Unknown")
    assert is_placeholder_name("N/A")
    assert is_placeholder_name("school")
    assert is_placeholder_name("various")
    assert is_placeholder_name("")
    assert is_placeholder_name(None)
    assert not is_placeholder_name("Stanford University")
    assert not is_placeholder_name("Meta")
    assert not is_placeholder_name("MIT")  # exactly 3 chars


def test_founder_profile_scrubs_placeholder_education():
    profile = FounderProfile(
        name="Jane",
        current_title="CEO",
        education=[
            Education(school="Unspecified Institution", start_year=2010),
            Education(school="Stanford University", start_year=2014),
        ],
    )
    schools = [e.school for e in profile.education]
    assert "Stanford University" in schools
    assert "Unspecified Institution" not in schools


def test_founder_profile_scrubs_placeholder_work_and_prior():
    profile = FounderProfile(
        name="Jane",
        current_title="CEO",
        work=[
            WorkExperience(company="Unknown", role="SWE"),
            WorkExperience(company="Google", role="SWE"),
        ],
        prior_startups=[PriorStartup(name="various", role="founder")],
    )
    assert [w.company for w in profile.work] == ["Google"]
    assert profile.prior_startups == []


def test_collision_detector_downgrades_confidence_on_long_span():
    profile = FounderProfile(
        name="Akash",
        current_title="CEO",
        confidence="high",
        work=[
            WorkExperience(company="Acme Corp", role="x", start_year=1995, end_year=2000),
            WorkExperience(company="Globex Inc", role="y", start_year=2020, end_year=2026),
        ],
    )
    assert profile.confidence == "low"
    assert "profile_breadth_suspicious" in profile.missing_fields


def test_collision_detector_flags_overlapping_employments():
    profile = FounderProfile(
        name="Jane",
        current_title="CEO",
        confidence="medium",
        work=[
            WorkExperience(company="Apple Inc", role="r", start_year=2018, end_year=2022),
            WorkExperience(company="Google LLC", role="r", start_year=2020, end_year=2024),
        ],
    )
    assert profile.confidence == "low"
    assert "overlapping_employment_conflict" in profile.missing_fields


def test_collision_detector_flags_excess_total_years():
    profile = FounderProfile(
        name="Jane",
        current_title="CEO",
        confidence="high",
        total_years_experience=30,
        work=[WorkExperience(company="Acme Corp", role="r", start_year=2020)],
    )
    assert profile.confidence == "low"
    assert "profile_breadth_suspicious" in profile.missing_fields
