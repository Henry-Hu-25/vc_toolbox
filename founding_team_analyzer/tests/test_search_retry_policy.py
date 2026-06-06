"""Tests for F-BE-013: tools/search.py retries only on transient/5xx errors,
not on auth failures or 4xx.

Validates VAL-BE-017 and VAL-BE-018.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests.exceptions

from founding_team_analyzer.tools import search as search_module
from founding_team_analyzer.tools.search import TavilyError, search, extract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client_that_raises(exc: Exception):
    """Return a mock TavilyClient whose .search() and .extract() both raise *exc*."""
    client = MagicMock()
    client.search.side_effect = exc
    client.extract.side_effect = exc
    return client


def _mock_client_transient_then_ok(n_failures: int, exc: Exception):
    """Return a mock TavilyClient whose .search() raises *exc* for the first
    *n_failures* calls and then returns a valid payload."""
    valid_search_result = {"results": [{"title": "T", "url": "https://example.com", "content": "C"}]}
    client = MagicMock()
    side_effects = [exc] * n_failures + [valid_search_result]
    client.search.side_effect = side_effects
    return client


def _mock_extract_client_transient_then_ok(n_failures: int, exc: Exception):
    """Return a mock TavilyClient whose .extract() raises *exc* for the first
    *n_failures* calls and then returns a valid payload."""
    valid_extract_result = {"results": [{"url": "https://example.com", "raw_content": "Content"}]}
    client = MagicMock()
    side_effects = [exc] * n_failures + [valid_extract_result]
    client.extract.side_effect = side_effects
    return client


# ---------------------------------------------------------------------------
# VAL-BE-017: Auth-class failures (401/403) do NOT trigger retries
# ---------------------------------------------------------------------------


def test_auth_401_not_retried_search():
    """InvalidAPIKeyError (401) must NOT trigger a retry.
    The underlying client should be called exactly once."""
    from tavily.errors import InvalidAPIKeyError

    client = _mock_client_that_raises(InvalidAPIKeyError("bad key"))

    # Clear cache so we don't hit cached results
    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        # search() catches exceptions and returns [], so it won't raise
        result = search("test query")

    # The client .search() should have been called exactly once (no retries)
    assert client.search.call_count == 1, (
        f"Expected exactly 1 call to client.search() for 401 auth error, "
        f"got {client.search.call_count} (retries are occurring)."
    )
    assert result == []


def test_auth_403_not_retried_search():
    """ForbiddenError (403) must NOT trigger a retry.
    The underlying client should be called exactly once."""
    from tavily.errors import ForbiddenError

    client = _mock_client_that_raises(ForbiddenError("forbidden"))

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = search("test query")

    assert client.search.call_count == 1, (
        f"Expected exactly 1 call to client.search() for 403 auth error, "
        f"got {client.search.call_count} (retries are occurring)."
    )
    assert result == []


def test_auth_401_not_retried_extract():
    """InvalidAPIKeyError (401) must NOT trigger a retry for extract either."""
    from tavily.errors import InvalidAPIKeyError

    client = _mock_client_that_raises(InvalidAPIKeyError("bad key"))

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = extract("https://example.com")

    assert client.extract.call_count == 1, (
        f"Expected exactly 1 call to client.extract() for 401 auth error, "
        f"got {client.extract.call_count} (retries are occurring)."
    )
    assert result is None


def test_auth_403_not_retried_extract():
    """ForbiddenError (403) must NOT trigger a retry for extract."""
    from tavily.errors import ForbiddenError

    client = _mock_client_that_raises(ForbiddenError("forbidden"))

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = extract("https://example.com")

    assert client.extract.call_count == 1, (
        f"Expected exactly 1 call to client.extract() for 403 auth error, "
        f"got {client.extract.call_count} (retries are occurring)."
    )
    assert result is None


def test_bad_request_400_not_retried_search():
    """BadRequestError (400) must NOT trigger a retry."""
    from tavily.errors import BadRequestError

    client = _mock_client_that_raises(BadRequestError("bad request"))

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = search("test query")

    assert client.search.call_count == 1, (
        f"Expected exactly 1 call to client.search() for 400 error, "
        f"got {client.search.call_count} (retries are occurring)."
    )
    assert result == []


# ---------------------------------------------------------------------------
# VAL-BE-018: Transient/5xx network errors DO trigger retry
# ---------------------------------------------------------------------------


def test_5xx_retried_search():
    """requests.exceptions.HTTPError with a 5xx status code MUST trigger retries.
    After 2 failures + 1 success, the underlying client is called 3 times
    and search() returns the successful result."""
    # Simulate a 5xx HTTPError
    mock_response = MagicMock()
    mock_response.status_code = 500
    http_error = requests.exceptions.HTTPError(response=mock_response)

    client = _mock_client_transient_then_ok(n_failures=2, exc=http_error)

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = search("test query")

    # After 2 failures + 1 success = 3 total calls
    assert client.search.call_count == 3, (
        f"Expected 3 calls to client.search() for 5xx transient error "
        f"(2 retries + 1 success), got {client.search.call_count}"
    )
    assert len(result) == 1
    assert result[0].title == "T"


def test_timeout_retried_search():
    """tavily.errors.TimeoutError (transient timeout) MUST trigger retries.
    After 2 timeouts + 1 success, the underlying client is called 3 times."""
    from tavily.errors import TimeoutError as TavilyTimeoutError

    client = _mock_client_transient_then_ok(n_failures=2, exc=TavilyTimeoutError(60))

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = search("test query")

    assert client.search.call_count == 3, (
        f"Expected 3 calls to client.search() for transient timeout "
        f"(2 retries + 1 success), got {client.search.call_count}"
    )
    assert len(result) == 1


def test_connection_error_retried_search():
    """requests.exceptions.ConnectionError (transient) MUST trigger retries."""
    conn_error = requests.exceptions.ConnectionError("connection refused")

    client = _mock_client_transient_then_ok(n_failures=1, exc=conn_error)

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = search("test query")

    assert client.search.call_count == 2, (
        f"Expected 2 calls to client.search() for transient connection error "
        f"(1 retry + 1 success), got {client.search.call_count}"
    )
    assert len(result) == 1


def test_429_rate_limit_retried_search():
    """UsageLimitExceededError (429 rate-limit) MUST trigger retries.
    Rate limiting is a transient condition that should be retried."""
    from tavily.errors import UsageLimitExceededError

    client = _mock_client_transient_then_ok(n_failures=1, exc=UsageLimitExceededError("rate limited"))

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = search("test query")

    assert client.search.call_count == 2, (
        f"Expected 2 calls to client.search() for 429 rate-limit error "
        f"(1 retry + 1 success), got {client.search.call_count}"
    )
    assert len(result) == 1


def test_5xx_retried_extract():
    """5xx HTTPError MUST trigger retries for extract as well."""
    mock_response = MagicMock()
    mock_response.status_code = 502
    http_error = requests.exceptions.HTTPError(response=mock_response)

    client = _mock_extract_client_transient_then_ok(n_failures=2, exc=http_error)

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = extract("https://example.com")

    assert client.extract.call_count == 3, (
        f"Expected 3 calls to client.extract() for 5xx transient error "
        f"(2 retries + 1 success), got {client.extract.call_count}"
    )
    assert result is not None


def test_4xx_http_error_not_retried_search():
    """A requests.exceptions.HTTPError with a 4xx status code (other than 429)
    must NOT trigger retries. Note: the Tavily client maps known 4xx codes
    to its own exceptions, but if an unmapped 4xx leaks through as
    HTTPError, it still should not be retried."""
    mock_response = MagicMock()
    mock_response.status_code = 422
    http_error = requests.exceptions.HTTPError(response=mock_response)

    client = _mock_client_that_raises(http_error)

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = search("test query")

    assert client.search.call_count == 1, (
        f"Expected exactly 1 call to client.search() for 422 HTTP error, "
        f"got {client.search.call_count} (retries are occurring)."
    )
    assert result == []
