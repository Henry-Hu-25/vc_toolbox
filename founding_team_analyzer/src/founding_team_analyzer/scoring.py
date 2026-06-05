"""Rubric weights, tier mapping, and the Python-side overall calculation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .schemas import CriterionScore, Tier


@dataclass(frozen=True)
class RubricCriterion:
    key: str
    label: str
    weight: float
    anchor_0: str
    anchor_3: str
    anchor_5: str
    required_evidence: str


RUBRIC: tuple[RubricCriterion, ...] = (
    RubricCriterion(
        key="founder_market_fit",
        label="Founder-market fit",
        weight=0.20,
        anchor_0="No founder has worked in this sector.",
        anchor_3="One founder has 2-4 years in the sector.",
        anchor_5="Multiple founders have 5+ years in the exact sub-sector, or built/operated the problem.",
        required_evidence="Job titles + dates + sector match.",
    ),
    RubricCriterion(
        key="skill_complementarity",
        label="Skill complementarity",
        weight=0.15,
        anchor_0="All founders share the same skill (e.g. all engineers, no commercial).",
        anchor_3="Two of {tech, product, business} covered.",
        anchor_5="All three covered with senior-level depth; explicit CEO/CTO split.",
        required_evidence="Role mix across work[].",
    ),
    RubricCriterion(
        key="prior_shared_history",
        label="Prior shared history",
        weight=0.15,
        anchor_0="No shared school or employer.",
        anchor_3="Shared school OR employer with overlapping years.",
        anchor_5="Co-founded a prior company together, or overlapped 2+ years at the same employer in the same team.",
        required_evidence="From TeamOverlap.",
    ),
    RubricCriterion(
        key="founder_experience",
        label="Prior founding experience",
        weight=0.15,
        anchor_0="No founder has started anything.",
        anchor_3="One founder with one prior startup (any outcome).",
        anchor_5="Multiple founders with prior startups; >=1 successful exit or scaled to material revenue.",
        required_evidence="prior_startups[].",
    ),
    RubricCriterion(
        key="pedigree",
        label="Pedigree",
        weight=0.10,
        anchor_0="No notable school or employer.",
        anchor_3="One founder from a top school or top employer.",
        anchor_5="Multiple founders from top-tier schools AND top-tier employers (FAANG/top AI labs/unicorn ops roles).",
        required_evidence="education[] + work[].",
    ),
    RubricCriterion(
        key="seniority_depth",
        label="Seniority and depth",
        weight=0.10,
        anchor_0="<3 yrs avg experience.",
        anchor_3="5-8 yrs avg, some leadership.",
        anchor_5="10+ yrs avg, multiple founders held VP/Director or were technical leads.",
        required_evidence="total_years_experience.",
    ),
    RubricCriterion(
        key="network_signals",
        label="Network signals",
        weight=0.10,
        anchor_0="None.",
        anchor_3="One founder has YC/Techstars or strong public following.",
        anchor_5="Multiple accelerator alumni or repeat-founder networks; known investor backing visible.",
        required_evidence="accelerators[] + press.",
    ),
    RubricCriterion(
        key="team_completeness",
        label="Team completeness",
        weight=0.05,
        anchor_0="Solo founder with critical gap.",
        anchor_3="2 founders, one gap acknowledged.",
        anchor_5="2-3 founders, complementary, no critical gap.",
        required_evidence="Inferred from above.",
    ),
)


_RUBRIC_BY_KEY: dict[str, RubricCriterion] = {c.key: c for c in RUBRIC}


def total_weight() -> float:
    return sum(c.weight for c in RUBRIC)


def criterion(key: str) -> RubricCriterion:
    return _RUBRIC_BY_KEY[key]


def compute_overall(scores: Iterable[CriterionScore]) -> float:
    """Weighted overall in 0-100 using rubric weights (ignores stray keys)."""
    total = 0.0
    used_weight = 0.0
    for s in scores:
        rc = _RUBRIC_BY_KEY.get(s.key)
        weight = rc.weight if rc is not None else s.weight
        if weight <= 0:
            continue
        clamped = max(0, min(5, int(s.score)))
        total += weight * (clamped / 5.0)
        used_weight += weight
    if used_weight <= 0:
        return 0.0
    # If the LLM omitted criteria, renormalize so missing pieces don't drag the score to 0.
    return round((total / used_weight) * 100.0, 1)


def map_tier(overall: float) -> Tier:
    if overall >= 80:
        return "Strong"
    if overall >= 60:
        return "Promising"
    if overall >= 40:
        return "Mixed"
    return "Weak"


def render_rubric_for_prompt() -> str:
    lines = [
        "| # | Key | Weight | Score 0 | Score 3 | Score 5 |",
        "|---|-----|--------|---------|---------|---------|",
    ]
    for idx, c in enumerate(RUBRIC, start=1):
        lines.append(
            f"| {idx} | {c.key} | {int(c.weight * 100)}% | "
            f"{c.anchor_0} | {c.anchor_3} | {c.anchor_5} |"
        )
    return "\n".join(lines)
