"""Tavily wrapper: search() and extract() with retry, timeout and in-memory cache."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests.exceptions
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .. import config as config_module

log = logging.getLogger(__name__)

try:  # Tavily client is required for live runs, but tests may monkeypatch this module.
    from tavily import TavilyClient  # type: ignore
except Exception:  # pragma: no cover - optional at import time for tests
    TavilyClient = None  # type: ignore[assignment]

try:  # Tavily error classes — optional at import time for tests.
    from tavily.errors import (  # type: ignore
        BadRequestError,
        ForbiddenError,
        InvalidAPIKeyError,
        UsageLimitExceededError,
    )
except Exception:  # pragma: no cover
    BadRequestError = None  # type: ignore[assignment,misc]
    ForbiddenError = None  # type: ignore[assignment,misc]
    InvalidAPIKeyError = None  # type: ignore[assignment,misc]
    UsageLimitExceededError = None  # type: ignore[assignment,misc]


@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractResult:
    url: str
    content: str
    raw: dict[str, Any] = field(default_factory=dict)


class TavilyError(RuntimeError):
    """Raised when Tavily calls fail after retries."""


_SEARCH_CACHE: dict[tuple[str, int, str], list[SearchResult]] = {}
_EXTRACT_CACHE: dict[str, ExtractResult] = {}


def _client() -> Any:
    if TavilyClient is None:
        raise TavilyError("tavily-python is not installed in this environment.")
    if not config_module.SETTINGS.tavily_api_key:
        raise TavilyError("TAVILY_API_KEY is not set.")
    return TavilyClient(api_key=config_module.SETTINGS.tavily_api_key)


# ---------------------------------------------------------------------------
# Retry predicate — only retry on transient errors, not auth/4xx
# ---------------------------------------------------------------------------

# Exceptions that represent non-retryable client / auth errors.
_NON_RETRYABLE: tuple[type[Exception], ...] = tuple(
    cls
    for cls in (InvalidAPIKeyError, ForbiddenError, BadRequestError)
    if cls is not None  # filtered when tavily.errors is unavailable
)


def _should_retry(exc: BaseException) -> bool:
    """Return True for transient errors that are worth retrying (5xx,
    connection failures, timeouts, rate limits).  Return False for
    auth failures (401/403) and client errors (4xx except 429)."""
    # Auth / client errors — never retry
    if _NON_RETRYABLE and isinstance(exc, _NON_RETRYABLE):
        return False

    # 429 rate-limit — retry with backoff
    if UsageLimitExceededError is not None and isinstance(exc, UsageLimitExceededError):
        return True

    # requests HTTPError — retry only for 5xx
    if isinstance(exc, requests.exceptions.HTTPError):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status >= 500
        # No status code info — assume transient
        return True

    # Transient network errors — retry
    if isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ),
    ):
        return True

    # Tavily TimeoutError wraps requests Timeout — also retry
    try:
        from tavily.errors import TimeoutError as TavilyTimeout  # type: ignore

        if isinstance(exc, TavilyTimeout):
            return True
    except Exception:  # pragma: no cover
        pass

    # Anything else is unexpected — don't retry
    return False


_retry_decorator = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_should_retry),
    reraise=True,
)


@_retry_decorator
def _do_search(query: str, max_results: int, search_depth: str) -> dict[str, Any]:
    return _client().search(
        query=query,
        max_results=max_results,
        search_depth=search_depth,
        include_answer=False,
    )


@_retry_decorator
def _do_extract(url: str) -> dict[str, Any]:
    return _client().extract(urls=[url])


def search(query: str, max_results: int = 5, search_depth: str = "basic") -> list[SearchResult]:
    key = (query, max_results, search_depth)
    if key in _SEARCH_CACHE:
        return _SEARCH_CACHE[key]
    try:
        payload = _do_search(query, max_results, search_depth)
    except Exception as exc:  # pragma: no cover - network failure path
        log.warning("tavily.search failed for %r: %s", query, exc)
        return []
    items: list[SearchResult] = []
    for r in payload.get("results", []) or []:
        items.append(
            SearchResult(
                title=str(r.get("title") or "").strip(),
                url=str(r.get("url") or "").strip(),
                content=str(r.get("content") or "").strip(),
                score=r.get("score"),
                raw=r,
            )
        )
    _SEARCH_CACHE[key] = items
    return items


def extract(url: str) -> ExtractResult | None:
    if not url:
        return None
    if url in _EXTRACT_CACHE:
        return _EXTRACT_CACHE[url]
    try:
        payload = _do_extract(url)
    except Exception as exc:  # pragma: no cover - network failure path
        log.warning("tavily.extract failed for %s: %s", url, exc)
        return None
    results = payload.get("results") or []
    if not results:
        return None
    item = results[0]
    out = ExtractResult(
        url=str(item.get("url") or url),
        content=str(item.get("raw_content") or item.get("content") or "").strip(),
        raw=item,
    )
    _EXTRACT_CACHE[url] = out
    return out


def reset_cache() -> None:
    _SEARCH_CACHE.clear()
    _EXTRACT_CACHE.clear()
