"""Unit tests for paperwiki._internal.http.

Uses httpx's :class:`httpx.MockTransport` so tests stay hermetic — no
live network access, no extra packages, just stdlib + httpx.
"""

from __future__ import annotations

import httpx
import pytest

from paperwiki._internal.http import (
    DEFAULT_TIMEOUT,
    RETRYABLE_STATUS,
    USER_AGENT,
    build_client,
    fetch_with_retry,
)
from paperwiki.core.errors import IntegrationError

# ---------------------------------------------------------------------------
# build_client
# ---------------------------------------------------------------------------


class TestBuildClient:
    def test_returns_async_client(self) -> None:
        client = build_client()
        try:
            assert isinstance(client, httpx.AsyncClient)
        finally:
            # Avoid ResourceWarning from un-closed client.
            import asyncio

            asyncio.run(client.aclose())

    def test_default_user_agent_is_set(self) -> None:
        client = build_client()
        try:
            assert client.headers["User-Agent"] == USER_AGENT
        finally:
            import asyncio

            asyncio.run(client.aclose())

    def test_custom_headers_merge_with_default_user_agent(self) -> None:
        client = build_client(headers={"X-Test": "yes"})
        try:
            assert client.headers["X-Test"] == "yes"
            assert client.headers["User-Agent"] == USER_AGENT
        finally:
            import asyncio

            asyncio.run(client.aclose())

    def test_custom_user_agent_overrides_default(self) -> None:
        client = build_client(headers={"User-Agent": "custom/1.0"})
        try:
            assert client.headers["User-Agent"] == "custom/1.0"
        finally:
            import asyncio

            asyncio.run(client.aclose())

    def test_default_timeout_is_explicit(self) -> None:
        # We do not want the httpx default of 5s — sources can be slow.
        assert DEFAULT_TIMEOUT.read == 30.0
        assert DEFAULT_TIMEOUT.connect == 10.0


# ---------------------------------------------------------------------------
# fetch_with_retry
# ---------------------------------------------------------------------------


def _client_with_handler(
    handler: httpx.MockTransport,
) -> httpx.AsyncClient:
    return build_client(transport=handler)


class TestFetchWithRetry:
    async def test_returns_response_on_first_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        async with _client_with_handler(httpx.MockTransport(handler)) as client:
            resp = await fetch_with_retry(client, "GET", "https://example.com/api")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    async def test_retries_on_503_then_succeeds(self) -> None:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            if calls["count"] < 3:
                return httpx.Response(503, text="busy")
            return httpx.Response(200, text="ok")

        async with _client_with_handler(httpx.MockTransport(handler)) as client:
            resp = await fetch_with_retry(
                client,
                "GET",
                "https://example.com/api",
                max_retries=3,
                initial_backoff=0,
            )

        assert resp.status_code == 200
        assert calls["count"] == 3

    async def test_retries_on_429_then_succeeds(self) -> None:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            if calls["count"] == 1:
                return httpx.Response(429, text="rate limited")
            return httpx.Response(200, text="ok")

        async with _client_with_handler(httpx.MockTransport(handler)) as client:
            resp = await fetch_with_retry(
                client,
                "GET",
                "https://example.com/api",
                initial_backoff=0,
            )

        assert resp.status_code == 200
        assert calls["count"] == 2

    async def test_does_not_retry_on_404(self) -> None:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            return httpx.Response(404, text="not found")

        async with _client_with_handler(httpx.MockTransport(handler)) as client:
            resp = await fetch_with_retry(
                client,
                "GET",
                "https://example.com/api",
                initial_backoff=0,
            )

        assert resp.status_code == 404
        assert calls["count"] == 1  # No retry on client error.

    async def test_raises_integration_error_after_exhausting_retries(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server boom")

        async with _client_with_handler(httpx.MockTransport(handler)) as client:
            with pytest.raises(IntegrationError, match="failed after"):
                await fetch_with_retry(
                    client,
                    "GET",
                    "https://example.com/api",
                    max_retries=3,
                    initial_backoff=0,
                )

    async def test_retries_on_request_error_then_succeeds(self) -> None:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.ConnectError("network down")
            return httpx.Response(200, text="ok")

        async with _client_with_handler(httpx.MockTransport(handler)) as client:
            resp = await fetch_with_retry(
                client,
                "GET",
                "https://example.com/api",
                initial_backoff=0,
            )

        assert resp.status_code == 200

    async def test_persistent_network_failure_raises_integration_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("network down")

        async with _client_with_handler(httpx.MockTransport(handler)) as client:
            with pytest.raises(IntegrationError, match="failed after") as excinfo:
                await fetch_with_retry(
                    client,
                    "GET",
                    "https://example.com/api",
                    max_retries=2,
                    initial_backoff=0,
                )
        assert excinfo.value.__cause__ is not None

    async def test_passes_params_and_headers_to_underlying_request(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["x_test"] = request.headers.get("x-test")
            return httpx.Response(200)

        async with _client_with_handler(httpx.MockTransport(handler)) as client:
            await fetch_with_retry(
                client,
                "GET",
                "https://example.com/api",
                params={"q": "foo bar"},
                headers={"X-Test": "yep"},
            )

        assert "q=foo+bar" in str(captured["url"]) or "q=foo%20bar" in str(captured["url"])
        assert captured["x_test"] == "yep"


class TestRetryableStatusContents:
    def test_includes_429_and_5xx(self) -> None:
        assert 429 in RETRYABLE_STATUS
        for code in (500, 502, 503, 504):
            assert code in RETRYABLE_STATUS

    def test_excludes_4xx_other_than_429(self) -> None:
        for code in (400, 401, 403, 404):
            assert code not in RETRYABLE_STATUS
