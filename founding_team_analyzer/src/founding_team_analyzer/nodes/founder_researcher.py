"""Agent 3 - FounderResearcher. Runs once per founder via LangGraph Send."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

from ..config import SETTINGS
from ..llm import call_structured, load_prompt
from ..schemas import (
    Company,
    CostLedger,
    Founder,
    FounderProfile,
    RawFactBundle,
)
from ..tools import search as search_tool

log = logging.getLogger(__name__)

_AUTHORITY_DOMAINS = (
    "linkedin.com",
    "crunchbase.com",
    "ycombinator.com",
    "techcrunch.com",
    "forbes.com",
    "wsj.com",
    "bloomberg.com",
    "wired.com",
    "stanford.edu",
    "mit.edu",
)


def _name_tokens(name: str) -> list[str]:
    return [t.strip().lower() for t in (name or "").split() if len(t.strip()) >= 2]


def _passes_disambiguation_gate(
    result: search_tool.SearchResult,
    founder: Founder,
    company: Company | None,
) -> bool:
    """Drop candidate URLs that don't co-mention the founder and the company.

    A LinkedIn URL that exactly matches Founder.linkedin_url is always allowed
    (the team page already vouched for that profile).
    """
    if not result or not result.url:
        return False
    url = result.url.strip()
    if founder.linkedin_url and url.rstrip("/").lower() == founder.linkedin_url.rstrip("/").lower():
        return True
    haystack = f"{result.title or ''}\n{result.content or ''}".lower()
    name_tokens = _name_tokens(founder.name)
    if not name_tokens:
        return False
    name_present = all(tok in haystack for tok in name_tokens)
    if not name_present:
        return False
    if company is None or not company.name:
        return True
    company_tokens = _name_tokens(company.name)
    company_present = any(tok in haystack for tok in company_tokens)
    if company_present:
        return True
    # Carve-out: linkedin.com/in/<slug> pages with a matching slug from the
    # founder linkedin url are also acceptable even if Tavily's snippet was
    # too short to mention the company.
    if founder.linkedin_url and "linkedin.com/in/" in url:
        try:
            founder_slug = urlparse(founder.linkedin_url).path.strip("/").split("/")[-1].lower()
            url_slug = urlparse(url).path.strip("/").split("/")[-1].lower()
            if founder_slug and founder_slug == url_slug:
                return True
        except Exception:
            return False
    return False


def _rank_for_extraction(
    results: list[search_tool.SearchResult],
    founder: Founder,
    company: Company | None,
) -> list[str]:
    company_website = company.website if company and company.website else None
    domain_pref = lambda url: next(
        (i for i, d in enumerate(_AUTHORITY_DOMAINS) if d in (url or "")),
        len(_AUTHORITY_DOMAINS),
    )
    filtered = [r for r in results if _passes_disambiguation_gate(r, founder, company)]
    sorted_results = sorted(filtered, key=lambda r: (domain_pref(r.url), -(r.score or 0.0)))
    urls: list[str] = []
    for r in sorted_results:
        if not r.url:
            continue
        if company_website and company_website in r.url:
            continue
        if r.url in urls:
            continue
        urls.append(r.url)
    return urls


def _search_plan(founder: Founder, company: Company | None) -> list[str]:
    company_name = company.name if company else ""
    base = founder.name
    queries = [
        f'"{base}" {company_name}'.strip(),
        f'"{base}" "{company_name}" LinkedIn',
        f'"{base}" {company_name} education',
        f'"{base}" {company_name} co-founder',
        f'"{base}" {company_name} interview',
    ]
    return [q for q in queries if q]


def _enforce_authoritative_title(
    profile: FounderProfile, founder: Founder, company: Company | None
) -> tuple[FounderProfile, list[str]]:
    """Restore the team-page title unless a company-domain source contradicts it."""
    warnings: list[str] = []
    authoritative = (founder.title or "").strip()
    if not authoritative:
        return profile, warnings
    current = (profile.current_title or "").strip()
    if not current:
        profile.current_title = authoritative
        return profile, warnings
    if current.lower() == authoritative.lower():
        return profile, warnings
    company_domain = ""
    if company and company.website:
        company_domain = urlparse(company.website).netloc.lower().replace("www.", "")
    has_company_source = False
    if company_domain:
        for w in profile.work:
            if any(company_domain in (u or "").lower() for u in w.source_urls):
                has_company_source = True
                break
    if not has_company_source:
        warnings.append(
            f"Researcher: restored authoritative title for {founder.name} "
            f"('{authoritative}'); rejected '{current}' (no company-domain source)."
        )
        profile.current_title = authoritative
    return profile, warnings


def run(payload: dict[str, Any]) -> dict[str, Any]:
    founder: Founder = payload["founder"]
    company: Company | None = payload.get("company")
    base_llm_calls: int = payload.get("base_llm_calls", 0)

    cost = CostLedger()
    if not founder or not founder.name:
        return {
            "profiles": [],
            "warnings": ["FounderResearcher: missing founder."],
            "cost": cost,
        }

    # Phase 1: search.
    all_results: list[search_tool.SearchResult] = []
    queries = _search_plan(founder, company)[: SETTINGS.max_tavily_per_founder]
    for q in queries:
        results = search_tool.search(q, max_results=4)
        all_results.extend(results)
        cost.tavily_searches += 1

    # Phase 2: pick top URLs to extract (with disambiguation gate).
    candidate_urls = _rank_for_extraction(all_results, founder, company)[
        : SETTINGS.max_extracts_per_founder
    ]
    extracts: list[tuple[str, str]] = []
    for url in candidate_urls:
        extracted = search_tool.extract(url)
        cost.tavily_extracts += 1
        if extracted and extracted.content:
            extracts.append((extracted.url, extracted.content))

    # Fallback: use snippets if extracts came back empty (still gated).
    if not extracts:
        for r in all_results[:5]:
            if not _passes_disambiguation_gate(r, founder, company):
                continue
            if r.url and r.content:
                extracts.append((r.url, r.content))

    if not extracts:
        log.warning("No sources found for founder %s", founder.name)
        empty = FounderProfile(
            name=founder.name,
            current_title=founder.title or "",
            linkedin_url=founder.linkedin_url,
            confidence="low",
            missing_fields=[
                "education",
                "work",
                "prior_startups",
                "accelerators",
                "total_years_experience",
                "domain_years_experience",
            ],
        )
        return {
            "profiles": [empty],
            "warnings": [f"FounderResearcher: no qualifying sources for {founder.name}."],
            "cost": cost,
        }

    # Stage A: extract raw facts per source.
    bundles: list[dict[str, Any]] = []
    company_name = company.name if company else ""
    for url, content in extracts:
        prompt_a = load_prompt("founder_extract_stage_a").format(
            founder_name=founder.name,
            company_name=company_name,
            source_url=url,
            source_content=content[:6000],
        )
        try:
            bundle, llm_cost = call_structured(
                RawFactBundle, prompt_a, model=SETTINGS.model_extract,
                llm_calls_so_far=base_llm_calls + cost.llm_calls,
            )
            cost = cost.merged(llm_cost)
            bundles.append(bundle.model_dump())
        except Exception as exc:
            log.warning("Stage A extraction failed for %s (%s): %s", founder.name, url, exc)

    # Stage B: consolidate.
    bundles_json = json.dumps(bundles, ensure_ascii=False, indent=2)
    prompt_b = load_prompt("founder_extract_stage_b").format(
        founder_name=founder.name,
        founder_title=founder.title or "",
        company_name=company_name,
        bundles_json=bundles_json,
    )
    try:
        profile, llm_cost = call_structured(
            FounderProfile, prompt_b,
            llm_calls_so_far=base_llm_calls + cost.llm_calls,
        )
        cost = cost.merged(llm_cost)
    except Exception as exc:
        log.exception("Stage B consolidation failed for %s", founder.name)
        profile = FounderProfile(
            name=founder.name,
            current_title=founder.title or "",
            linkedin_url=founder.linkedin_url,
            confidence="low",
            missing_fields=["education", "work", "prior_startups"],
        )

    seen_urls = {u for u, _ in extracts}
    profile.source_urls = sorted({*profile.source_urls, *seen_urls, *founder.source_urls})
    if not profile.linkedin_url and founder.linkedin_url:
        profile.linkedin_url = founder.linkedin_url
    if not profile.name:
        profile.name = founder.name

    profile, title_warnings = _enforce_authoritative_title(profile, founder, company)

    return {
        "profiles": [profile],
        "warnings": title_warnings,
        "cost": cost,
    }
