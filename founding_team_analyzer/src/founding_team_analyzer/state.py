"""Typed LangGraph state and reducers."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from .schemas import (
    Company,
    CostLedger,
    Founder,
    FounderProfile,
    TeamOverlap,
    TeamScore,
)


def merge_cost(left: CostLedger | None, right: CostLedger | None) -> CostLedger:
    left = left or CostLedger()
    right = right or CostLedger()
    return left.merged(right)


class AnalyzerState(TypedDict, total=False):
    raw_input: str
    company: Company | None
    founders: list[Founder]
    profiles: Annotated[list[FounderProfile], operator.add]
    overlaps: TeamOverlap | None
    score: TeamScore | None
    report_md: str | None
    warnings: Annotated[list[str], operator.add]
    cost: Annotated[CostLedger, merge_cost]


class ResearcherInput(TypedDict, total=False):
    """Payload sent to each parallel researcher via LangGraph Send."""

    founder: Founder
    company: Company | None
