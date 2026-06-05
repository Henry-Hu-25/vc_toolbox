"""Agent 5 - TeamScorer. Applies the rubric with an optional self-critique pass."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..llm import call_structured, load_prompt
from ..schemas import Company, CostLedger, FounderProfile, TeamOverlap, TeamScore
from ..scoring import RUBRIC, compute_overall, map_tier, render_rubric_for_prompt
from ..state import AnalyzerState

log = logging.getLogger(__name__)


def _build_dossier(
    company: Company | None,
    profiles: list[FounderProfile],
    overlaps: TeamOverlap | None,
) -> str:
    blob = {
        "company": company.model_dump() if company else None,
        "founders": [p.model_dump() for p in profiles],
        "overlaps": overlaps.model_dump() if overlaps else None,
    }
    return json.dumps(blob, ensure_ascii=False, indent=2)


def _empty_score() -> TeamScore:
    return TeamScore(
        criteria=[],
        overall_0_100=0.0,
        tier="Weak",
        top_strengths=[],
        top_risks=["No scoring possible: insufficient data."],
        open_questions=[],
    )


def _self_critique_enabled(state: AnalyzerState) -> bool:
    return not state.get("self_critique_disabled", False)


def run(state: AnalyzerState) -> dict[str, Any]:
    company = state.get("company")
    profiles = state.get("profiles") or []
    overlaps = state.get("overlaps")
    cost = CostLedger()
    prior_llm_calls = (state.get("cost") or CostLedger()).llm_calls

    if not profiles:
        warning = "TeamScorer: no founder profiles; emitting placeholder score."
        return {"score": _empty_score(), "warnings": [warning], "cost": cost}

    dossier = _build_dossier(company, profiles, overlaps)
    prompt = load_prompt("team_scorer").format(
        rubric_table=render_rubric_for_prompt(),
        dossier=dossier,
    )
    try:
        score, llm_cost = call_structured(
            TeamScore, prompt,
            llm_calls_so_far=prior_llm_calls + cost.llm_calls,
        )
        cost = cost.merged(llm_cost)
    except Exception as exc:
        log.exception("TeamScorer LLM call failed")
        return {
            "score": _empty_score(),
            "warnings": [f"TeamScorer failed: {exc}"],
            "cost": cost,
        }

    if _self_critique_enabled(state):
        critique_prompt = load_prompt("team_scorer_self_critique").format(
            dossier=dossier,
            prior_score_json=score.model_dump_json(indent=2),
        )
        try:
            refined, llm_cost = call_structured(
                TeamScore, critique_prompt,
                llm_calls_so_far=prior_llm_calls + cost.llm_calls,
            )
            cost = cost.merged(llm_cost)
            if refined.criteria:
                score = refined
        except Exception as exc:
            log.warning("TeamScorer self-critique failed: %s", exc)

    # Backfill weight/label from rubric in case the LLM omitted or distorted them.
    rubric_by_key = {c.key: c for c in RUBRIC}
    for cs in score.criteria:
        rc = rubric_by_key.get(cs.key)
        if rc is not None:
            cs.weight = rc.weight
            cs.label = rc.label

    score.overall_0_100 = compute_overall(score.criteria)
    score.tier = map_tier(score.overall_0_100)

    low_conf = sum(1 for p in profiles if p.confidence == "low")
    if low_conf >= 2:
        if score.overall_0_100 > 60:
            score.overall_0_100 = 60.0
            score.tier = map_tier(60.0)
        msg = "Limited public information; conclusions are tentative."
        if msg not in score.top_risks:
            score.top_risks.append(msg)

    return {"score": score, "cost": cost, "warnings": []}
