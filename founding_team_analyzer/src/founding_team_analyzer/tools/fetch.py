"""HTTP fetch + main-content extraction fallback (httpx + trafilatura)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .. import config as config_module

log = logging.getLogger(__name__)

try:
    import trafilatura  # type: ignore
except Exception:  # pragma: no cover
    trafilatura = None  # type: ignore[assignment]


_USER_AGENT = (
    "Mozilla/5.0 (compatible; FoundingTeamAnalyzer/0.1; +https://example.com/bot)"
)


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status: int
    html: str
    text: str


class FetchError(RuntimeError):
    """Raised when an HTTP fetch fails after retries."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.HTTPError,)),
    reraise=True,
)
def _do_get(url: str) -> httpx.Response:
    with httpx.Client(
        timeout=config_module.SETTINGS.http_timeout,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        return client.get(url)


def fetch(url: str) -> FetchedPage | None:
    if not url:
        return None
    try:
        resp = _do_get(url)
    except Exception as exc:  # pragma: no cover - network path
        log.warning("httpx.get failed for %s: %s", url, exc)
        return None
    if resp.status_code >= 400:
        log.info("httpx.get %s -> %s", url, resp.status_code)
        return FetchedPage(
            url=url,
            final_url=str(resp.url),
            status=resp.status_code,
            html="",
            text="",
        )
    html = resp.text
    text = ""
    if trafilatura is not None and html:
        try:
            text = trafilatura.extract(html, include_links=False) or ""
        except Exception as exc:  # pragma: no cover
            log.debug("trafilatura.extract failed: %s", exc)
            text = ""
    return FetchedPage(
        url=url,
        final_url=str(resp.url),
        status=resp.status_code,
        html=html,
        text=text,
    )
