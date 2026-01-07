"""Async client for CEZ Distribution HDO switch-times API."""

from __future__ import annotations

import logging
from typing import Any, LiteralString, Self

import httpx

from .const import (
    DEFAULT_TIMEOUT,
    HTTP_STATUS_OK,
    KEY_NAME_EAN,
    KEY_NAME_PLACE,
    KEY_NAME_SN,
    MAX_PRINT_SIGNALS,
    REQUEST_URL,
)
from .exceptions import ApiError, HttpRequestError, InvalidRequestError, InvalidResponseError
from .models import SignalEntry, SignalsData, SignalsResponse
from .validators import validate_ean

logger: logging.Logger = logging.getLogger(__name__)


def _normalize_id(v: str | None) -> str | None:
    """Normalize input string: strip and convert empty to None.

    :param v: Input string or None.
    :returns: Stripped string or None.
    """
    if v is None:
        return None
    v2: str = v.strip()
    return v2 if v2 else None


class CezHdoClient:
    """
    Async HTTP client for CEZ Distribution HDO API.

    Typical usage:

    >>> async with CezHdoClient() as client:
    ...     resp = await client.fetch_signals(ean="859182400123456789")
    ...     for entry in resp.data.signals:
    ...         print(entry.date_str, entry.times_raw)

    :param timeout_s: Timeout for HTTP requests (seconds).
    :param base_url: Endpoint URL. Defaults to REQUEST_URL constant.
    """

    _timeout: float
    _base_url: str
    _client: httpx.AsyncClient | None

    def __init__(self, *, timeout_s: float = DEFAULT_TIMEOUT, base_url: str = REQUEST_URL) -> None:
        """Initialize the client.

        :param timeout_s: Timeout for HTTP requests (seconds).
        :param base_url: Endpoint URL. Defaults to REQUEST_URL constant.
        """
        self._timeout = timeout_s
        self._base_url = base_url
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        """Enter async context manager, initializing the AsyncClient."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        """Exit async context manager, closing the AsyncClient.

        :param exc_type: Exception type, if any.
        :param exc: Exception instance, if any.
        :param tb: Traceback, if any.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            msg = "Client is not initialized. Use 'async with CezHdoClient()' or call 'open()'."
            raise RuntimeError(msg)
        return self._client

    async def open(self) -> None:
        """Manually open the underlying AsyncClient (alternative to async with)."""
        if self._client is None:
            await self.__aenter__()

    async def close(self) -> None:
        """Manually close the underlying AsyncClient (alternative to async with)."""
        await self.__aexit__(None, None, None)

    @staticmethod
    def build_payload(
        *, ean: str | None = None, sn: str | None = None, place: str | None = None
    ) -> dict[str, str]:
        """Build request payload for the API.

        At least one of (ean, sn, place) must be provided.

        :param ean: EAN number of the electricity meter.
        :param sn: Serial number of the electricity meter.
        :param place: Place number of the electricity meter.
        :returns: Payload dict for the API.
        :raises InvalidRequestError: If no identifier is provided.
        """
        ean_n: str | None = _normalize_id(ean)
        sn_n: str | None = _normalize_id(sn)
        place_n: str | None = _normalize_id(place)

        provided: list[tuple[str, str | None]] = [("ean", ean_n), ("sn", sn_n), ("place", place_n)]
        present: list[str] = [name for name, val in provided if val is not None]

        msg: str
        if len(present) == 0:
            msg = "Exactly one of 'ean', 'sn', or 'place' must be provided."
            raise InvalidRequestError(msg)
        if len(present) > 1:
            msg = f"Provide exactly one identifier (got {', '.join(present)})."
            raise InvalidRequestError(msg)

        payload: dict[str, str] = {}
        if ean_n is not None:
            if not validate_ean(ean_n):
                msg = f"Invalid EAN format for CEZ Distribution: {ean_n}"
                raise InvalidRequestError(msg)
            payload[KEY_NAME_EAN] = ean_n
        if sn_n is not None:
            payload[KEY_NAME_SN] = sn_n
        if place_n is not None:
            payload[KEY_NAME_PLACE] = place_n

        if not payload:
            msg: str = "At one of 'ean', 'sn', or 'place' must be provided."
            raise InvalidRequestError(msg)

        return payload

    async def fetch_signals(
        self,
        *,
        ean: str | None = None,
        sn: str | None = None,
        place: str | None = None,
    ) -> SignalsResponse:
        """
        Fetch HDO switch times / signals from the API.

        :param ean: EAN number of the electricity meter.
        :param sn: Serial number of the electricity meter.
        :param place: Place number of the electricity meter.
        :returns: Parsed SignalsResponse.
        :raises InvalidRequestError: If no identifier is provided.
        :raises HttpRequestError: If HTTP request fails.
        :raises ApiError: If API returns non-200 statusCode in payload.
        :raises InvalidResponseError: If response schema is unexpected.
        """
        client: httpx.AsyncClient = self._ensure_client()
        payload: dict[str, str] = self.build_payload(ean=ean, sn=sn, place=place)
        logger.debug(
            "Fetching signals: url=%s timeout=%ss keys=%s",
            self._base_url,
            self._timeout,
            list(payload.keys()),
        )

        try:
            r: httpx.Response = await client.post(self._base_url, json=payload)
            logger.debug("HTTP response: status=%s", r.status_code)
            r.raise_for_status()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
            logger.warning("Request failed: %s", e)
            msg: str = f"Request failed: {e!s}"
            raise HttpRequestError(msg) from e

        try:
            raw: dict[str, Any] = r.json()
        except ValueError as e:
            logger.warning("Response is not valid JSON: %s", e)
            msg: str = "Response is not valid JSON."
            raise InvalidResponseError(msg) from e

        logger.debug("API payload statusCode=%s", raw.get("statusCode"))

        return self._parse_response(raw)

    @staticmethod
    def _parse_response(raw: dict[str, Any]) -> SignalsResponse:
        """Parse and validate the API response payload.

        :param raw: Raw response JSON as dict.
        :returns: Parsed SignalsResponse.
        :raises InvalidResponseError: If response schema is unexpected.
        """
        msg: str
        if not isinstance(raw, dict):
            msg = "Response JSON must be an object."
            raise InvalidResponseError(msg)

        status_code = raw.get("statusCode")
        if not isinstance(status_code, int):
            msg = "Missing or invalid 'statusCode'."
            raise InvalidResponseError(msg)

        data = raw.get("data")
        if not isinstance(data, dict):
            msg = "Missing or invalid 'data' object."
            raise InvalidResponseError(msg)

        if status_code != HTTP_STATUS_OK:
            # API sometimes still provides useful info in 'data', but treat as error by default
            msg = f"API returned statusCode={status_code}"
            raise ApiError(msg)

        signals: list[Any] | None = data.get("signals")
        if not isinstance(signals, list):
            msg = "Missing or invalid 'data.signals' list."
            raise InvalidResponseError(msg)

        parsed_signals: list[SignalEntry] = []
        for i, item in enumerate(signals):
            if not isinstance(item, dict):
                msg: str = f"signals[{i}] must be an object"
                raise InvalidResponseError(msg)

            signal: str | None = item.get("signal")
            day_name: str | None = item.get("den")
            date_str: str | None = item.get("datum")
            times_raw: str | None = item.get("casy")

            if not all(isinstance(x, str) and x for x in (signal, day_name, date_str, times_raw)):
                msg = f"signals[{i}] missing required string fields"
                raise InvalidResponseError(msg)

            parsed_signals.append(
                SignalEntry(
                    signal=signal,  # pyright: ignore[reportArgumentType]
                    day_name=day_name,  # pyright: ignore[reportArgumentType]
                    date_str=date_str,  # pyright: ignore[reportArgumentType]
                    times_raw=times_raw,  # pyright: ignore[reportArgumentType]
                )
            )

            signals = parsed_signals
            unique: list[Any] = sorted({s.signal for s in signals})
            preview: LiteralString = ", ".join(unique[:MAX_PRINT_SIGNALS])
            suffix: str = "..." if len(unique) > MAX_PRINT_SIGNALS else ""
            logger.debug(
                "Parsed signals: count=%d unique=%d (%s%s)",
                len(signals),
                len(unique),
                preview,
                suffix,
            )

        partner: str | None = data.get("partner")
        partner_str: str | None = partner if isinstance(partner, str) else None

        flash: Any | None = raw.get("flashMessages")
        flash_messages: list[Any] = flash if isinstance(flash, list) else []
        return SignalsResponse(
            data=SignalsData(signals=parsed_signals, partner=partner_str, raw=data),
            status_code=status_code,
            flash_messages=flash_messages,
            raw=raw,
        )
