"""Async HTTP utilities for paper-wiki source plugins.

Two helpers are exposed:

* :func:`build_client` returns a default-configured :class:`httpx.AsyncClient`
  with paper-wiki's User-Agent and a longer timeout than httpx's 5s
  default (sources like Semantic Scholar are sometimes slow).
* :func:`fetch_with_retry` issues a single request with exponential
  backoff on retryable status codes (429, 5xx) and on transient
  ``httpx.RequestError``\\ s. On persistent failure it raises
  :class:`IntegrationError` with the last exception attached.

Plugin authors should prefer :func:`fetch_with_retry` over calling
``client.request`` directly so retry behavior stays consistent across
sources.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from paperwiki.core.errors import IntegrationError, RateLimitError

USER_AGENT = "paper-wiki/0.1.0 (+https://github.com/kaneyxx/paper-wiki)"
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def build_client(
    *,
    timeout: httpx.Timeout | None = None,
    headers: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Return an :class:`httpx.AsyncClient` configured with sane defaults.

    The default User-Agent identifies paper-wiki to upstream services so
    operators can spot the traffic. Caller-supplied headers merge over
    the defaults; passing ``User-Agent`` explicitly overrides the
    default.

    The ``transport`` parameter exists for tests, which inject a
    :class:`httpx.MockTransport` to replay scripted responses.
    """
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)
    return httpx.AsyncClient(
        timeout=timeout or DEFAULT_TIMEOUT,
        headers=merged_headers,
        transport=transport,
    )


async def fetch_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    backoff_factor: float = 2.0,
) -> httpx.Response:
    """Issue an HTTP request, retrying transient failures.

    Retries on:

    * Status codes in :data:`RETRYABLE_STATUS` (429 + 5xx).
    * Transient transport-layer errors raised by httpx
      (:class:`httpx.RequestError` and subclasses).

    Backoff doubles each attempt: ``initial_backoff * backoff_factor**n``.
    Raises :class:`IntegrationError` once ``max_retries`` is exhausted,
    with the most recent failure attached as the exception cause.
    """
    last_exc: BaseException | None = None
    last_status: int | None = None
    for attempt in range(max_retries):
        try:
            response = await client.request(method, url, params=params, headers=headers)
        except httpx.RequestError as exc:
            last_exc = exc
            last_status = None
        else:
            if response.status_code not in RETRYABLE_STATUS:
                return response
            last_status = response.status_code
            last_exc = httpx.HTTPStatusError(
                f"HTTP {response.status_code}",
                request=response.request,
                response=response,
            )

        if attempt < max_retries - 1:
            wait = initial_backoff * (backoff_factor**attempt)
            if wait > 0:
                await asyncio.sleep(wait)

    # Task 9.169: persistent rate-limit raises a typed RateLimitError so
    # SKILLs / the run-status ledger can spot rate-limit-driven failures
    # without parsing exception messages. Other exhausted retryable
    # statuses (5xx) keep the generic IntegrationError class.
    if last_status == 429:
        msg = f"{method} {url} rate-limited (HTTP 429) after {max_retries} attempts"
        raise RateLimitError(msg) from last_exc
    msg = f"{method} {url} failed after {max_retries} attempts"
    raise IntegrationError(msg) from last_exc


__all__ = [
    "DEFAULT_TIMEOUT",
    "RETRYABLE_STATUS",
    "USER_AGENT",
    "build_client",
    "fetch_with_retry",
]
