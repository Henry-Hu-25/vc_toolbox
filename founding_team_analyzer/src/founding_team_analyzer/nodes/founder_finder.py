"""Agent 2 - FounderFinder. Resolves a Company into a list of Founder candidates."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin, urlparse

from ..config import SETTINGS
from ..llm import call_structured, load_prompt
from ..schemas import Company, CostLedger, Founder, FounderList
from ..state import AnalyzerState
from ..tools import search as search_tool
from ..tools.normalize import is_founder_title, normalize_name

log = logging.getLogger(__name__)


def _build_sources_block(items: list[dict[str, str]]) -> str:
    lines = []
    for i, item in enumerate(items, start=1):
        title = item.get("title", "")
        url = item.get("url", "")
        content = item.get("content", "")[:1500]
        lines.append(f"[{i}] {title} - {url}\n{content}\n")
    return "\n".join(lines).strip() or "(no sources gathered)"


def _candidate_team_pages(website: str | None) -> list[str]:
    if not website:
        return []
    base = website if website.endswith("/") else website + "/"
    parsed = urlparse(base)
    if not parsed.scheme:
        base = "https://" + base.lstrip("/")
    return [urljoin(base, p) for p in ("about", "about-us", "team", "company", "founders")]


def _gather_sources(company: Company) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    queries = [
        f"{company.name} founders",
        f"{company.name} co-founder CEO",
        f"{company.name} site:crunchbase.com",
        f"{company.name} founding team",
    ]
    for q in queries:
        for r in search_tool.search(q, max_results=4):
            items.append({"title": r.title, "url": r.url, "content": r.content})

    for url in _candidate_team_pages(company.website):
        extracted = search_tool.extract(url)
        if extracted and extracted.content:
            items.append({"title": f"{company.name} team page", "url": extracted.url, "content": extracted.content})

    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in items:
        u = item.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        deduped.append(item)
    return deduped


def _filter_and_dedupe(raw_list: list[Founder], max_founders: int) -> tuple[list[Founder], list[str]]:
    warnings: list[str] = []
    by_name: dict[str, Founder] = {}
    for f in raw_list:
        normalized = normalize_name(f.name)
        if not normalized:
            continue
        if normalized in by_name:
            existing = by_name[normalized]
            existing.source_urls = list({*existing.source_urls, *f.source_urls})
            if not existing.linkedin_url and f.linkedin_url:
                existing.linkedin_url = f.linkedin_url
            if not existing.title and f.title:
                existing.title = f.title
            continue
        if not is_founder_title(f.title):
            # Keep entries that lack a title but have evidence of being a founder via snippet.
            if not f.source_urls:
                continue
        by_name[normalized] = Founder(
            name=normalized,
            title=f.title,
            linkedin_url=f.linkedin_url,
            twitter_url=f.twitter_url,
            source_urls=f.source_urls,
        )

    founders = list(by_name.values())
    if len(founders) > max_founders:
        warnings.append(
            f"FounderFinder: found {len(founders)} candidates, capping at {max_founders}."
        )
        founders = founders[:max_founders]
    return founders, warnings


def run(state: AnalyzerState) -> dict[str, Any]:
    company = state.get("company")
    if company is None or not company.name:
        return {
            "founders": [],
            "warnings": ["FounderFinder: no company in state; skipping."],
            "cost": CostLedger(),
        }

    sources = _gather_sources(company)
    cost = CostLedger(
        tavily_searches=4,
        tavily_extracts=sum(
            1 for item in sources if "team page" in (item.get("title") or "").lower()
        ),
    )
    prior_llm_calls = (state.get("cost") or CostLedger()).llm_calls
    prompt = load_prompt("founder_finder").format(
        company_name=company.name,
        company_website=company.website or "",
        max_founders=SETTINGS.max_founders,
        sources_block=_build_sources_block(sources),
    )

    try:
        result, llm_cost = call_structured(
            FounderList, prompt, model=SETTINGS.model_extract,
            llm_calls_so_far=prior_llm_calls + cost.llm_calls,
        )
        cost = cost.merged(llm_cost)
    except Exception as exc:
        log.exception("FounderFinder LLM call failed")
        return {
            "founders": [],
            "warnings": [f"FounderFinder failed: {exc}"],
            "cost": cost,
        }

    founders, warnings = _filter_and_dedupe(result.founders, SETTINGS.max_founders)
    if not founders:
        warnings.append("FounderFinder: zero founders explicitly identified.")
    return {
        "founders": founders,
        "warnings": warnings,
        "cost": cost,
    }
