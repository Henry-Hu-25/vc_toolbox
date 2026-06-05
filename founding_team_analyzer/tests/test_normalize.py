from founding_team_analyzer.tools.normalize import (
    detect_input_type,
    is_founder_title,
    normalize_company,
    normalize_name,
    normalize_school,
    slugify,
    year_ranges_overlap,
)


def test_detect_input_type():
    assert detect_input_type("https://acme.ai") == "url"
    assert detect_input_type("https://www.linkedin.com/company/acme") == "linkedin_company"
    assert detect_input_type("Acme Robotics") == "name"
    assert detect_input_type("acme.ai") == "url"


def test_slugify():
    assert slugify("Acme Robotics!") == "acme-robotics"
    assert slugify("") == "company"


def test_normalize_name():
    assert normalize_name("  john doe  ") == "John Doe"
    assert normalize_name("élise") == "Elise"


def test_normalize_company_strips_suffix():
    assert normalize_company("Acme Inc.") == "acme"
    assert normalize_company("Meta Platforms") == "meta platforms"


def test_normalize_school_canonicalizes():
    assert normalize_school("mit") == "Massachusetts Institute of Technology"
    assert normalize_school("Stanford") == "Stanford University"
    assert normalize_school("Some Unknown Polytechnic") == "Some Unknown Polytechnic"


def test_is_founder_title():
    assert is_founder_title("Co-Founder & CEO")
    assert is_founder_title("Founding Engineer")
    assert is_founder_title("CTO")
    assert not is_founder_title("Senior Designer")
    assert not is_founder_title(None)


def test_year_ranges_overlap():
    assert year_ranges_overlap(2010, 2014, 2013, 2016) == "2013-2014"
    assert year_ranges_overlap(2010, 2014, 2015, 2018) is None
    assert year_ranges_overlap(None, None, 2015, 2018) is None
    assert year_ranges_overlap(2010, None, 2015, None) is None  # both open -> ambiguous
    # One side closed: we can pin the upper bound to the closed end year.
    assert year_ranges_overlap(2010, 2020, 2015, None) == "2015-2020"
    assert year_ranges_overlap(None, None, 2015, 2018) is None  # one side fully unknown
