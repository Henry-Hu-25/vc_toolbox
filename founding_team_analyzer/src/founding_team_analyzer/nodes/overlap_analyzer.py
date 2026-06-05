"""Agent 4 - OverlapAnalyzer. Deterministic Python overlaps + LLM narrative polish."""

from __future__ import annotations

import json
import logging
from itertools import combinations
from typing import Any

from ..llm import call_structured, load_prompt
from ..schemas import (
    CostLedger,
    FounderPairOverlap,
    FounderProfile,
    SharedEmployer,
    SharedSchool,
    Strength,
    TeamOverlap,
)
from ..state import AnalyzerState
from ..tools.normalize import normalize_company, normalize_school, year_ranges_overlap

log = logging.getLogger(__name__)


def _shared_schools(a: FounderProfile, b: FounderProfile) -> list[SharedSchool]:
    out: list[SharedSchool] = []
    a_index = {(normalize_school(e.school).lower(), e.start_year, e.end_year): e for e in a.education}
    b_index = {(normalize_school(e.school).lower(), e.start_year, e.end_year): e for e in b.education}
    a_schools = {k[0]: e for k, e in a_index.items()}
    b_schools = {k[0]: e for k, e in b_index.items()}
    for key in a_schools.keys() & b_schools.keys():
        ea = a_schools[key]
        eb = b_schools[key]
        overlap = year_ranges_overlap(ea.start_year, ea.end_year, eb.start_year, eb.end_year)
        out.append(SharedSchool(school=normalize_school(ea.school), overlap_years=overlap))
    return out


def _shared_employers(a: FounderProfile, b: FounderProfile) -> list[SharedEmployer]:
    out: list[SharedEmployer] = []
    a_jobs = {normalize_company(w.company): w for w in a.work}
    b_jobs = {normalize_company(w.company): w for w in b.work}
    for key in a_jobs.keys() & b_jobs.keys():
        if not key:
            continue
        wa = a_jobs[key]
        wb = b_jobs[key]
        overlap = year_ranges_overlap(wa.start_year, wa.end_year, wb.start_year, wb.end_year)
        out.append(
            SharedEmployer(
                company=wa.company,
                overlap_years=overlap,
                same_technical_cluster=bool(wa.is_technical_role and wb.is_technical_role),
            )
        )
    return out


def _shared_prior_startups(a: FounderProfile, b: FounderProfile) -> list[str]:
    a_names = {normalize_company(p.name) for p in a.prior_startups if p.name}
    b_names = {normalize_company(p.name) for p in b.prior_startups if p.name}
    return sorted({n for n in (a_names & b_names) if n})


def _shared_accelerators(a: FounderProfile, b: FounderProfile) -> list[str]:
    return sorted(set(a.accelerators) & set(b.accelerators))


def _deterministic_pair(a: FounderProfile, b: FounderProfile) -> FounderPairOverlap:
    return FounderPairOverlap(
        founder_a=a.name,
        founder_b=b.name,
        shared_schools=_shared_schools(a, b),
        shared_employers=_shared_employers(a, b),
        shared_prior_startups=_shared_prior_startups(a, b),
        shared_accelerators=_shared_accelerators(a, b),
    )


def _profile_summary(p: FounderProfile) -> dict[str, Any]:
    return {
        "name": p.name,
        "current_title": p.current_title,
        "education": [
            {"school": e.school, "start": e.start_year, "end": e.end_year} for e in p.education
        ],
        "work": [
            {
                "company": w.company,
                "role": w.role,
                "start": w.start_year,
                "end": w.end_year,
                "technical": w.is_technical_role,
            }
            for w in p.work
        ],
        "prior_startups": [{"name": s.name, "role": s.role} for s in p.prior_startups],
        "accelerators": p.accelerators,
    }


def _max_strength(values: list[Strength]) -> Strength:
    order = ["none", "weak", "medium", "strong"]
    best = "none"
    for v in values:
        if order.index(v) > order.index(best):
            best = v
    return best  # type: ignore[return-value]


def run(state: AnalyzerState) -> dict[str, Any]:
    profiles = state.get("profiles") or []
    cost = CostLedger()
    if len(profiles) < 2:
        notes = ["Solo founder: pairwise overlap not applicable."] if profiles else [
            "No founders to compute overlap from."
        ]
        return {
            "overlaps": TeamOverlap(pairs=[], overall_strength="none", notes=notes),
            "cost": cost,
            "warnings": [],
        }

    pairs = [_deterministic_pair(a, b) for a, b in combinations(profiles, 2)]
    has_any_overlap = any(
        p.shared_schools or p.shared_employers or p.shared_prior_startups or p.shared_accelerators
        for p in pairs
    )

    if not has_any_overlap:
        return {
            "overlaps": TeamOverlap(
                pairs=pairs,
                overall_strength="none",
                notes=["No deterministic overlaps found across schools, employers, prior startups, or accelerators."],
            ),
            "cost": cost,
            "warnings": [],
        }

    payload = {
        "pairs": [p.model_dump() for p in pairs],
        "profiles_summary": [_profile_summary(p) for p in profiles],
    }
    prompt = load_prompt("overlap_narrative").format(
        overlap_payload=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    try:
        polished, llm_cost = call_structured(TeamOverlap, prompt)
        cost = cost.merged(llm_cost)
    except Exception as exc:
        log.warning("Overlap narrative LLM call failed: %s", exc)
        polished = TeamOverlap(
            pairs=pairs,
            overall_strength=_max_strength(["medium" if has_any_overlap else "none"]),
        )

    if not polished.pairs:
        polished.pairs = pairs
    if polished.overall_strength == "none" and has_any_overlap:
        polished.overall_strength = _max_strength([p.strength for p in polished.pairs])

    return {
        "overlaps": polished,
        "cost": cost,
        "warnings": [],
    }
