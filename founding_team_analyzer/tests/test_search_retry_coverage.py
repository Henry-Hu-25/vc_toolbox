"""Additional search retry policy tests: _should_retry predicate unit tests
and edge cases not covered by test_search_retry_policy.py.

Broadens coverage for VAL-BE-017 and VAL-BE-018.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests.exceptions

from founding_team_analyzer.tools import search as search_module
from founding_team_analyzer.tools.search import _should_retry, search, extract


# ---------------------------------------------------------------------------
# Unit tests for _should_retry predicate
# ---------------------------------------------------------------------------


def test_should_retry_returns_false_for_unknown_exception():
    """An unexpected exception type (not auth, not HTTP, not connection)
    must NOT be retried."""
    result = _should_retry(ValueError("something unexpected"))
    assert result is False, "Unexpected exceptions should not be retried"


def test_should_retry_returns_false_for_type_error():
    """TypeError must NOT be retried (not a transient error)."""
    result = _should_retry(TypeError("wrong type"))
    assert result is False, "TypeError should not be retried"


def test_should_retry_returns_true_for_connection_error():
    """requests.exceptions.ConnectionError is transient and must be retried."""
    result = _should_retry(requests.exceptions.ConnectionError("refused"))
    assert result is True, "ConnectionError should be retried"


def test_should_retry_returns_true_for_timeout():
    """requests.exceptions.Timeout is transient and must be retried."""
    result = _should_retry(requests.exceptions.Timeout("timed out"))
    assert result is True, "Timeout should be retried"


def test_should_retry_returns_true_for_5xx_http_error():
    """requests.exceptions.HTTPError with 5xx status code must be retried."""
    mock_response = MagicMock()
    mock_response.status_code = 503
    exc = requests.exceptions.HTTPError(response=mock_response)
    result = _should_retry(exc)
    assert result is True, "5xx HTTPError should be retried"


def test_should_retry_returns_false_for_4xx_http_error():
    """requests.exceptions.HTTPError with 4xx status code (not 429)
    must NOT be retried."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    exc = requests.exceptions.HTTPError(response=mock_response)
    result = _should_retry(exc)
    assert result is False, "404 HTTPError should not be retried"


def test_should_retry_returns_false_for_422_http_error():
    """requests.exceptions.HTTPError with 422 status code must NOT be retried."""
    mock_response = MagicMock()
    mock_response.status_code = 422
    exc = requests.exceptions.HTTPError(response=mock_response)
    result = _should_retry(exc)
    assert result is False, "422 HTTPError should not be retried"


def test_should_retry_http_error_no_status_code_assumes_transient():
    """If an HTTPError has no response/status_code, assume transient
    (the predicate returns True for safety)."""
    exc = requests.exceptions.HTTPError("no response attached")
    # The response attribute may be None
    result = _should_retry(exc)
    # With no status code info, the predicate assumes transient
    assert result is True, "HTTPError without status code should be retried (assume transient)"


def test_should_retry_returns_true_for_tavily_timeout():
    """tavily.errors.TimeoutError must be retried (wraps requests Timeout)."""
    from tavily.errors import TimeoutError as TavilyTimeoutError
    result = _should_retry(TavilyTimeoutError(60))
    assert result is True, "Tavily TimeoutError should be retried"


def test_should_retry_returns_true_for_usage_limit_exceeded():
    """tavily.errors.UsageLimitExceededError (429) must be retried."""
    from tavily.errors import UsageLimitExceededError
    result = _should_retry(UsageLimitExceededError("rate limited"))
    assert result is True, "429 rate limit should be retried"


def test_should_retry_returns_false_for_invalid_api_key():
    """tavily.errors.InvalidAPIKeyError (401) must NOT be retried."""
    from tavily.errors import InvalidAPIKeyError
    result = _should_retry(InvalidAPIKeyError("bad key"))
    assert result is False, "401 auth error should not be retried"


def test_should_retry_returns_false_for_forbidden():
    """tavily.errors.ForbiddenError (403) must NOT be retried."""
    from tavily.errors import ForbiddenError
    result = _should_retry(ForbiddenError("forbidden"))
    assert result is False, "403 forbidden should not be retried"


def test_should_retry_returns_false_for_bad_request():
    """tavily.errors.BadRequestError (400) must NOT be retried."""
    from tavily.errors import BadRequestError
    result = _should_retry(BadRequestError("bad request"))
    assert result is False, "400 bad request should not be retried"


# ---------------------------------------------------------------------------
# Integration: search() returns empty on non-retryable errors
# ---------------------------------------------------------------------------


def test_search_returns_empty_on_auth_error():
    """search() must return [] (not raise) on auth errors after no retry."""
    from tavily.errors import InvalidAPIKeyError

    client = MagicMock()
    client.search.side_effect = InvalidAPIKeyError("bad key")

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = search("anything")

    assert result == [], f"Expected empty list on auth error, got {result}"
    assert client.search.call_count == 1


def test_extract_returns_none_on_auth_error():
    """extract() must return None (not raise) on auth errors after no retry."""
    from tavily.errors import InvalidAPIKeyError

    client = MagicMock()
    client.extract.side_effect = InvalidAPIKeyError("bad key")

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = extract("https://example.com")

    assert result is None, f"Expected None on auth error, got {result}"
    assert client.extract.call_count == 1


# ---------------------------------------------------------------------------
# Integration: retry exhaustion returns empty/None
# ---------------------------------------------------------------------------


def test_search_returns_empty_after_retry_exhaustion():
    """search() must return [] when all retries are exhausted for
    transient errors (e.g., persistent 5xx)."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    http_error = requests.exceptions.HTTPError(response=mock_response)

    client = MagicMock()
    client.search.side_effect = http_error  # Always fails

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = search("persistent 5xx query")

    # Should have been called 3 times (initial + 2 retries = stop_after_attempt(3))
    assert client.search.call_count == 3, (
        f"Expected 3 calls (exhausted retries), got {client.search.call_count}"
    )
    assert result == [], f"Expected empty list after retry exhaustion, got {result}"


def test_extract_returns_none_after_retry_exhaustion():
    """extract() must return None when all retries are exhausted."""
    mock_response = MagicMock()
    mock_response.status_code = 502
    http_error = requests.exceptions.HTTPError(response=mock_response)

    client = MagicMock()
    client.extract.side_effect = http_error  # Always fails

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result = extract("https://example.com")

    assert client.extract.call_count == 3, (
        f"Expected 3 calls (exhausted retries), got {client.extract.call_count}"
    )
    assert result is None


# ---------------------------------------------------------------------------
# Cache behavior: search results are cached and not re-fetched
# ---------------------------------------------------------------------------


def test_search_caches_results():
    """search() must cache results and not call the underlying client
    again for the same query."""
    client = MagicMock()
    valid_result = {"results": [{"title": "T", "url": "https://example.com", "content": "C"}]}
    client.search.return_value = valid_result

    search_module.reset_cache()

    with patch.object(search_module, "_client", return_value=client):
        result1 = search("cached query")
        result2 = search("cached query")

    # Second call should hit the cache
    assert client.search.call_count == 1, (
        f"Expected 1 client call (cached), got {client.search.call_count}"
    )
    assert len(result1) == 1
    assert result1 == result2
