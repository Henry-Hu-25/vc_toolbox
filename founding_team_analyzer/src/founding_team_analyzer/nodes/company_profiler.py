"""Agent 1 - CompanyProfiler. Resolves raw input into a Company object."""

from __future__ import annotations

import logging
from typing import Any

from ..llm import call_structured, load_prompt
from ..schemas import Company, CostLedger
from ..state import AnalyzerState
from ..tools import search as search_tool
from ..tools.normalize import detect_input_type, ensure_scheme

log = logging.getLogger(__name__)

_GAPFILL_FIELDS = ("founded_year", "hq_location", "sector", "sub_sector")


def _build_sources_block(items: list[dict[str, str]]) -> str:
    lines = []
    for i, item in enumerate(items, start=1):
        title = item.get("title", "")
        url = item.get("url", "")
        content = item.get("content", "")[:1500]
        lines.append(f"[{i}] {title} - {url}\n{content}\n")
    return "\n".join(lines).strip() or "(no sources gathered)"


def _gather_sources(raw_input: str, input_type: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if input_type == "url":
        url = ensure_scheme(raw_input)
        extracted = search_tool.extract(url)
        if extracted and extracted.content:
            items.append(
                {"title": "Company homepage", "url": extracted.url, "content": extracted.content}
            )
        for r in search_tool.search(f"{raw_input} company overview", max_results=3):
            items.append({"title": r.title, "url": r.url, "content": r.content})
    elif input_type == "linkedin_company":
        slug = raw_input.rstrip("/").split("/company/")[-1].split("/")[0]
        for r in search_tool.search(
            f"site:linkedin.com/company {slug}", max_results=3
        ):
            items.append({"title": r.title, "url": r.url, "content": r.content})
        for r in search_tool.search(f"{slug} official website", max_results=3):
            items.append({"title": r.title, "url": r.url, "content": r.content})
    else:  # free-text name
        for r in search_tool.search(
            f"{raw_input} startup official website", max_results=4
        ):
            items.append({"title": r.title, "url": r.url, "content": r.content})
        for r in search_tool.search(f"{raw_input} company about", max_results=3):
            items.append({"title": r.title, "url": r.url, "content": r.content})
        for r in search_tool.search(f'"{raw_input}" founded year', max_results=3):
            items.append({"title": r.title, "url": r.url, "content": r.content})
        for r in search_tool.search(f'"{raw_input}" headquarters location', max_results=3):
            items.append({"title": r.title, "url": r.url, "content": r.content})
    # Dedupe by url
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in items:
        u = item.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        deduped.append(item)
    return deduped


def run(state: AnalyzerState) -> dict[str, Any]:
    raw_input = (state.get("raw_input") or "").strip()
    if not raw_input:
        return {
            "warnings": ["CompanyProfiler: empty raw_input."],
            "company": None,
            "cost": CostLedger(),
        }

    input_type = detect_input_type(raw_input)
    sources = _gather_sources(raw_input, input_type)
    cost = CostLedger(
        tavily_searches=sum(1 for _ in sources if _.get("url")),
        tavily_extracts=1 if input_type == "url" else 0,
    )
    prior_llm_calls = (state.get("cost") or CostLedger()).llm_calls

    prompt = load_prompt("company_profiler").format(
        raw_input=raw_input,
        input_type=input_type,
        sources_block=_build_sources_block(sources),
    )

    try:
        company, llm_cost = call_structured(
            Company, prompt,
            llm_calls_so_far=prior_llm_calls + cost.llm_calls,
        )
        cost = cost.merged(llm_cost)
    except Exception as exc:
        log.exception("CompanyProfiler LLM call failed")
        return {
            "warnings": [f"CompanyProfiler failed: {exc}"],
            "company": None,
            "cost": cost,
        }

    warnings: list[str] = []
    if not company.name:
        warnings.append("CompanyProfiler: could not resolve a company name; downstream may stop.")
    if not company.website and input_type == "url":
        company.website = ensure_scheme(raw_input)
    if input_type == "linkedin_company" and not company.linkedin_url:
        company.linkedin_url = raw_input

    company, gap_cost, gap_warnings = _gap_fill(company, prior_llm_calls=prior_llm_calls + cost.llm_calls)
    cost = cost.merged(gap_cost)
    warnings.extend(gap_warnings)

    return {
        "company": company,
        "warnings": warnings,
        "cost": cost,
    }


def _gap_fill(company: Company, *, prior_llm_calls: int = 0) -> tuple[Company, CostLedger, list[str]]:
    """If key fields are missing, fire targeted Tavily searches and re-prompt."""
    cost = CostLedger()
    warnings: list[str] = []
    missing = [f for f in _GAPFILL_FIELDS if getattr(company, f) is None]
    if not missing or not company.name:
        return company, cost, warnings

    extra_sources: list[dict[str, str]] = []
    for field in missing:
        query = {
            "founded_year": f'"{company.name}" founded year',
            "hq_location": f'"{company.name}" headquarters location',
            "sector": f'"{company.name}" industry sector',
            "sub_sector": f'"{company.name}" what does it do',
        }[field]
        for r in search_tool.search(query, max_results=3):
            extra_sources.append({"title": r.title, "url": r.url, "content": r.content})
        cost.tavily_searches += 1

    if not extra_sources:
        return company, cost, warnings

    prompt = load_prompt("company_profiler_gapfill").format(
        current_company_json=company.model_dump_json(indent=2),
        missing_fields=", ".join(missing),
        sources_block=_build_sources_block(extra_sources),
    )
    try:
        refined, llm_cost = call_structured(
            Company, prompt,
            llm_calls_so_far=prior_llm_calls + cost.llm_calls,
        )
        cost = cost.merged(llm_cost)
    except Exception as exc:
        warnings.append(f"CompanyProfiler gap-fill failed: {exc}")
        return company, cost, warnings

    for field in missing:
        new_value = getattr(refined, field, None)
        if new_value is not None and getattr(company, field) is None:
            setattr(company, field, new_value)

    extra_urls = [s.get("url") for s in extra_sources if s.get("url")]
    company.source_urls = sorted({*company.source_urls, *(u for u in extra_urls if u)})
    return company, cost, warnings
