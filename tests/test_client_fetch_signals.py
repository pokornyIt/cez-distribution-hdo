"""Tests for CezHdoClient.fetch_signals method."""

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from cez_distribution_hdo.client import HTTP_STATUS_OK, CezHdoClient
from cez_distribution_hdo.exceptions import HttpRequestError, InvalidResponseError

if TYPE_CHECKING:
    from cez_distribution_hdo.models import SignalsResponse


@pytest.mark.asyncio
async def test_fetch_signals_success_sends_expected_payload() -> None:
    seen: dict[str, None] = {"json": None, "url": None, "method": None}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)  # type: ignore  # noqa: PGH003
        seen["method"] = request.method  # type: ignore  # noqa: PGH003
        seen["json"] = json.loads(request.content.decode("utf-8"))

        body: dict[str, Any] = {
            "data": {"signals": [], "partner": "x"},
            "statusCode": HTTP_STATUS_OK,
            "flashMessages": [],
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)

    client = CezHdoClient(base_url="https://example.test/api")
    client._client = httpx.AsyncClient(transport=transport)  # NOTE: internal injection for tests

    resp: SignalsResponse = await client.fetch_signals(ean="859182400400000000")
    assert resp.status_code == HTTP_STATUS_OK
    assert seen["method"] == "POST"
    assert seen["url"] == "https://example.test/api"
    assert seen["json"] == {"ean": "859182400400000000"}

    await client.close()


@pytest.mark.asyncio
async def test_fetch_signals_http_500_raises_http_request_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    transport = httpx.MockTransport(handler)
    client = CezHdoClient(base_url="https://example.test/api")
    client._client = httpx.AsyncClient(transport=transport)

    with pytest.raises(HttpRequestError):
        await client.fetch_signals(ean="859182400400000000")

    await client.close()


@pytest.mark.asyncio
async def test_fetch_signals_timeout_raises_http_request_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")  # noqa: EM101

    transport = httpx.MockTransport(handler)
    client = CezHdoClient(base_url="https://example.test/api")
    client._client = httpx.AsyncClient(transport=transport)

    with pytest.raises(HttpRequestError, match="Request failed"):
        await client.fetch_signals(ean="859182400400000000")

    await client.close()


@pytest.mark.asyncio
async def test_fetch_signals_invalid_json_raises_invalid_response_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    transport = httpx.MockTransport(handler)
    client = CezHdoClient(base_url="https://example.test/api")
    client._client = httpx.AsyncClient(transport=transport)

    with pytest.raises(InvalidResponseError, match="not valid JSON"):
        await client.fetch_signals(ean="859182400400000000")

    await client.close()
