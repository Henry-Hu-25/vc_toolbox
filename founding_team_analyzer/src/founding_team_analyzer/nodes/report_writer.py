"""Agent 6 - ReportWriter. Pure-Python markdown + JSON renderer."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import SETTINGS
from ..schemas import (
    Company,
    CostLedger,
    FounderProfile,
    TeamOverlap,
    TeamScore,
)
from ..state import AnalyzerState
from ..tools.normalize import slugify

log = logging.getLogger(__name__)


def _na(value: Any) -> str:
    if value is None or value == "" or value == []:
        return "N/A - no public data found"
    return str(value)


def _confidence_badge(c: str) -> str:
    return {
        "high": "[confidence: HIGH]",
        "medium": "[confidence: MEDIUM]",
        "low": "[confidence: LOW]",
    }.get(c, "[confidence: ?]")


def _tier_badge(tier: str) -> str:
    return {
        "Strong": "STRONG - push to first meeting",
        "Promising": "PROMISING - needs targeted diligence",
        "Mixed": "MIXED - major gaps; pass unless thesis-fit",
        "Weak": "WEAK - pass",
    }.get(tier, tier)


def _render_company_header(company: Company | None) -> str:
    if company is None:
        return "## Company\n\nN/A - no company resolved.\n"
    lines = [
        f"## {company.name}",
        "",
        f"- One-liner: {_na(company.one_liner)}",
        f"- Sector: {_na(company.sector)}"
        + (f" / {company.sub_sector}" if company.sub_sector else ""),
        f"- HQ: {_na(company.hq_location)}",
        f"- Founded: {_na(company.founded_year)}",
        f"- Website: {_na(company.website)}",
        f"- LinkedIn: {_na(company.linkedin_url)}",
    ]
    if company.stage_signals:
        lines.append(f"- Stage signals: {', '.join(company.stage_signals)}")
    if company.source_urls:
        lines.append("- Sources: " + ", ".join(f"<{u}>" for u in company.source_urls))
    lines.append("")
    return "\n".join(lines)


def _render_founder_card(p: FounderProfile) -> str:
    lines = [
        f"### {p.name} - {_na(p.current_title)} {_confidence_badge(p.confidence)}",
    ]
    if p.linkedin_url:
        lines.append(f"- LinkedIn: <{p.linkedin_url}>")
    if p.total_years_experience is not None:
        lines.append(f"- Total years experience: {p.total_years_experience}")
    if p.domain_years_experience is not None:
        lines.append(f"- Domain years experience: {p.domain_years_experience}")
    if p.accelerators:
        lines.append(f"- Accelerators: {', '.join(p.accelerators)}")

    lines.append("\n**Education**")
    if not p.education:
        lines.append("- N/A")
    else:
        for e in p.education:
            years = ""
            if e.start_year or e.end_year:
                years = f" ({e.start_year or '?'}-{e.end_year or 'present'})"
            details = e.degree or ""
            if e.field:
                details = f"{details}, {e.field}" if details else e.field
            lines.append(f"- {e.school}{years}" + (f" - {details}" if details else ""))

    lines.append("\n**Work**")
    if not p.work:
        lines.append("- N/A")
    else:
        for w in p.work:
            years = ""
            if w.start_year or w.end_year:
                years = f" ({w.start_year or '?'}-{w.end_year or 'present'})"
            flags = []
            if w.is_founder_role:
                flags.append("founder")
            if w.is_technical_role:
                flags.append("technical")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"- {w.role} at {w.company}{years}{flag_str}")

    lines.append("\n**Prior startups**")
    if not p.prior_startups:
        lines.append("- N/A")
    else:
        for s in p.prior_startups:
            year = f" (started {s.year_started})" if s.year_started else ""
            lines.append(f"- {s.name} - {s.role} - outcome: {s.outcome}{year}")

    if p.notable_achievements:
        lines.append("\n**Notable**")
        for n in p.notable_achievements:
            lines.append(f"- {n}")

    if p.missing_fields:
        lines.append(f"\n_Missing fields:_ {', '.join(p.missing_fields)}")

    lines.append("")
    return "\n".join(lines)


def _render_overlap_section(overlaps: TeamOverlap | None) -> str:
    if overlaps is None or not overlaps.pairs:
        if overlaps and overlaps.notes:
            return "## Founder Overlap\n\n" + "\n".join(f"- {n}" for n in overlaps.notes) + "\n"
        return "## Founder Overlap\n\nN/A\n"

    lines = ["## Founder Overlap", ""]
    lines.append(f"**Overall strength:** {overlaps.overall_strength.upper()}")
    lines.append("")
    lines.append("| Founder A | Founder B | Schools | Employers | Prior Startups | Accelerators | Strength |")
    lines.append("|---|---|---|---|---|---|---|")
    for p in overlaps.pairs:
        lines.append(
            "| {a} | {b} | {sc} | {em} | {ps} | {ac} | {st} |".format(
                a=p.founder_a,
                b=p.founder_b,
                sc=", ".join(s.school for s in p.shared_schools) or "-",
                em=", ".join(s.company for s in p.shared_employers) or "-",
                ps=", ".join(p.shared_prior_startups) or "-",
                ac=", ".join(p.shared_accelerators) or "-",
                st=p.strength,
            )
        )
    lines.append("")
    for p in overlaps.pairs:
        if p.narrative:
            lines.append(f"- **{p.founder_a} & {p.founder_b}:** {p.narrative}")
    if overlaps.notes:
        lines.append("")
        for n in overlaps.notes:
            lines.append(f"_Note:_ {n}")
    lines.append("")
    return "\n".join(lines)


def _render_score_section(score: TeamScore | None) -> str:
    if score is None:
        return "## Score\n\nN/A - scoring not produced.\n"
    lines = [
        "## Team Score",
        "",
        f"**Overall: {score.overall_0_100:.1f} / 100 - {_tier_badge(score.tier)}**",
        "",
        "| Criterion | Weight | Score (0-5) | Rationale |",
        "|---|---|---|---|",
    ]
    for c in score.criteria:
        lines.append(
            f"| {c.label} | {int(c.weight * 100)}% | {c.score} | {c.rationale} |"
        )
    lines.append("")
    if score.top_strengths:
        lines.append("**Top strengths**")
        for s in score.top_strengths:
            lines.append(f"- {s}")
        lines.append("")
    if score.top_risks:
        lines.append("**Top risks**")
        for r in score.top_risks:
            lines.append(f"- {r}")
        lines.append("")
    if score.open_questions:
        lines.append("**Open questions for DD**")
        for q in score.open_questions:
            lines.append(f"- {q}")
        lines.append("")
    if any(c.evidence for c in score.criteria):
        lines.append("**Evidence**")
        for c in score.criteria:
            if not c.evidence:
                continue
            lines.append(f"- _{c.label}_")
            for e in c.evidence:
                lines.append(f"  - {e}")
        lines.append("")
    return "\n".join(lines)


def _render_appendix(profiles: list[FounderProfile], warnings: list[str], cost: CostLedger | None) -> str:
    lines = ["## Appendix", "", "### Sources by founder"]
    if not profiles:
        lines.append("- N/A")
    for p in profiles:
        urls = sorted(set(p.source_urls))
        if not urls:
            lines.append(f"- **{p.name}:** N/A")
        else:
            lines.append(f"- **{p.name}:**")
            for u in urls:
                lines.append(f"  - <{u}>")
    if warnings:
        lines.append("\n### Warnings")
        for w in warnings:
            lines.append(f"- {w}")
    if cost is not None:
        lines.append("\n### Cost ledger")
        lines.append(
            f"- LLM calls: {cost.llm_calls}; Tavily searches: {cost.tavily_searches}; "
            f"Tavily extracts: {cost.tavily_extracts}; HTTP fetches: {cost.http_fetches}"
        )
    lines.append("")
    return "\n".join(lines)


def _build_markdown(state: AnalyzerState) -> str:
    company = state.get("company")
    profiles = state.get("profiles") or []
    overlaps = state.get("overlaps")
    score = state.get("score")
    warnings = state.get("warnings") or []
    cost = state.get("cost")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = [
        f"# Founding Team Analysis",
        "",
        f"_Generated: {timestamp}_",
        "",
        _render_company_header(company),
        "## Founders",
        "",
    ]
    if not profiles:
        parts.append("N/A - no founders identified.\n")
    else:
        for p in profiles:
            parts.append(_render_founder_card(p))
    parts.append(_render_overlap_section(overlaps))
    parts.append(_render_score_section(score))
    parts.append(_render_appendix(profiles, warnings, cost))
    return "\n".join(parts).rstrip() + "\n"


def _build_json(state: AnalyzerState) -> dict[str, Any]:
    company = state.get("company")
    profiles = state.get("profiles") or []
    overlaps = state.get("overlaps")
    score = state.get("score")
    cost = state.get("cost")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_input": state.get("raw_input"),
        "company": company.model_dump() if company else None,
        "founders": [p.model_dump() for p in profiles],
        "overlaps": overlaps.model_dump() if overlaps else None,
        "score": score.model_dump() if score else None,
        "warnings": list(state.get("warnings") or []),
        "cost": cost.model_dump() if cost else None,
    }


def run(state: AnalyzerState) -> dict[str, Any]:
    company = state.get("company")
    md = _build_markdown(state)
    payload = _build_json(state)

    slug = slugify(company.name if company else (state.get("raw_input") or "report"))
    out_root = Path(SETTINGS.output_dir) / slug
    try:
        out_root.mkdir(parents=True, exist_ok=True)
        (out_root / "report.md").write_text(md, encoding="utf-8")
        (out_root / "report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log.warning("ReportWriter could not persist files to %s: %s", out_root, exc)

    return {"report_md": md, "cost": CostLedger(), "warnings": []}
