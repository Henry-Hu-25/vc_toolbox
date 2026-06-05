import math

from founding_team_analyzer.schemas import CriterionScore
from founding_team_analyzer.scoring import RUBRIC, compute_overall, map_tier, total_weight


def _scores(value: int) -> list[CriterionScore]:
    return [
        CriterionScore(
            key=c.key,
            label=c.label,
            weight=c.weight,
            score=value,
            evidence=[f"https://example.com/{c.key}"],
            rationale="anchor",
        )
        for c in RUBRIC
    ]


def test_total_weight_is_one():
    assert math.isclose(total_weight(), 1.0, abs_tol=1e-6)


def test_all_fives_is_100():
    assert compute_overall(_scores(5)) == 100.0


def test_all_zeros_is_0():
    assert compute_overall(_scores(0)) == 0.0


def test_threes_around_60():
    assert compute_overall(_scores(3)) == 60.0


def test_tier_mapping():
    assert map_tier(95) == "Strong"
    assert map_tier(80) == "Strong"
    assert map_tier(79.9) == "Promising"
    assert map_tier(60) == "Promising"
    assert map_tier(59.9) == "Mixed"
    assert map_tier(40) == "Mixed"
    assert map_tier(39.9) == "Weak"
    assert map_tier(0) == "Weak"


def test_missing_criterion_renormalizes():
    partial = _scores(5)[:4]
    assert compute_overall(partial) == 100.0


def test_clamps_out_of_range_scores():
    one = _scores(3)[0]
    one.score = 99
    others = _scores(0)[1:]
    overall = compute_overall([one, *others])
    expected = round(RUBRIC[0].weight * 1.0 * 100.0, 1)
    assert overall == expected
