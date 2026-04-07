"""Shared HTTP client factory with retry/backoff and typed exceptions."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# --- Exceptions ---


class APIError(Exception):
    """Base exception for API errors."""

    def __init__(self, message: str, status_code: int | None = None, source: str = "") -> None:
        self.status_code = status_code
        self.source = source
        super().__init__(message)


class RateLimitError(APIError):
    """429 Too Many Requests."""

    def __init__(self, message: str, retry_after: float | None = None, source: str = "") -> None:
        self.retry_after = retry_after
        super().__init__(message, status_code=429, source=source)


class NotFoundError(APIError):
    """404 Not Found."""

    def __init__(self, message: str, source: str = "") -> None:
        super().__init__(message, status_code=404, source=source)


class AuthenticationError(APIError):
    """401/403 Authentication failure."""

    def __init__(self, message: str, status_code: int = 401, source: str = "") -> None:
        super().__init__(message, status_code=status_code, source=source)


class ServiceError(Exception):
    """Service-level error after all fallbacks exhausted."""


# --- Retry helpers ---


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APIError) and exc.status_code in (502, 503, 504):
        return True
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout)):
        return True
    return False


def _log_retry(state: RetryCallState) -> None:
    if state.outcome and state.outcome.failed:
        exc = state.outcome.exception()
        logger.warning(
            "Retry attempt %d after %s: %s",
            state.attempt_number,
            type(exc).__name__,
            exc,
        )


def with_retry(max_attempts: int = 3, min_wait: float = 1.0, max_wait: float = 30.0):
    """Decorator for retrying on transient errors with exponential backoff."""
    return retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=min_wait, max=max_wait),
        before_sleep=_log_retry,
        reraise=True,
    )


# --- Client factory ---


def create_http_client(
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    """Create a shared async HTTP client with sensible defaults."""
    default_headers = {
        "User-Agent": "research-mcp/0.1.0 (https://github.com/research-mcp)",
        "Accept": "application/json",
    }
    if headers:
        default_headers.update(headers)

    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        headers=default_headers,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )


def raise_for_status(response: httpx.Response, source: str = "") -> None:
    """Raise typed exceptions based on HTTP status codes."""
    if response.is_success:
        return

    status = response.status_code
    body = response.text[:500]

    if status == 404:
        raise NotFoundError(f"Not found: {response.url}", source=source)

    if status == 429:
        retry_after = response.headers.get("Retry-After")
        retry_secs = float(retry_after) if retry_after else None
        raise RateLimitError(
            f"Rate limited by {source}: {body}",
            retry_after=retry_secs,
            source=source,
        )

    if status in (401, 403):
        raise AuthenticationError(
            f"Auth error from {source} ({status}): {body}",
            status_code=status,
            source=source,
        )

    raise APIError(
        f"HTTP {status} from {source}: {body}",
        status_code=status,
        source=source,
    )


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    source: str = "",
    **kwargs: Any,
) -> Any:
    """GET a URL and return parsed JSON, raising typed exceptions."""
    response = await client.get(url, **kwargs)
    raise_for_status(response, source=source)
    return response.json()


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    source: str = "",
    **kwargs: Any,
) -> Any:
    """POST and return parsed JSON, raising typed exceptions."""
    response = await client.post(url, **kwargs)
    raise_for_status(response, source=source)
    return response.json()
