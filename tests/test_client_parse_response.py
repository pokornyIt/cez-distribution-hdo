"""Tests for client._parse_response()."""

from typing import TYPE_CHECKING, Any, Literal

import pytest

from cez_distribution_hdo.client import HTTP_STATUS_OK, CezHdoClient
from cez_distribution_hdo.exceptions import ApiError, InvalidResponseError

if TYPE_CHECKING:
    from cez_distribution_hdo.models import SignalEntry, SignalsResponse


def _valid_payload() -> dict:
    return {
        "data": {
            "signals": [
                {
                    "signal": "PTV2",
                    "den": "Sobota",
                    "datum": "03.01.2026",
                    "casy": "00:00-06:00; 17:00-24:00",
                }
            ],
            "partner": "0011271556",
        },
        "statusCode": HTTP_STATUS_OK,
        "flashMessages": [],
    }


def test_parse_response_happy_path() -> None:
    raw: dict[Any, Any] = _valid_payload()
    resp: SignalsResponse = CezHdoClient._parse_response(raw)

    assert resp.status_code == HTTP_STATUS_OK
    assert resp.data.partner == "0011271556"
    assert len(resp.data.signals) == 1

    s: SignalEntry = resp.data.signals[0]
    assert s.signal == "PTV2"
    assert s.day_name == "Sobota"
    assert s.date_str == "03.01.2026"
    assert "00:00-06:00" in s.times_raw


def test_parse_response_partner_optional_or_non_str() -> None:
    raw: dict[Any, Any] = _valid_payload()
    raw["data"]["partner"] = 123  # type: ignore[index]
    resp: SignalsResponse = CezHdoClient._parse_response(raw)
    assert resp.data.partner is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        "x",
        123,
    ],
)
def test_parse_response_rejects_non_object(raw: Literal["x", 123] | None | list[object]) -> None:
    with pytest.raises(InvalidResponseError, match="must be an object"):
        CezHdoClient._parse_response(raw)  # type: ignore[arg-type]


def test_parse_response_missing_status_code() -> None:
    raw: dict[Any, Any] = _valid_payload()
    raw.pop("statusCode")
    with pytest.raises(InvalidResponseError, match="statusCode"):
        CezHdoClient._parse_response(raw)


def test_parse_response_status_code_not_int() -> None:
    raw: dict[Any, Any] = _valid_payload()
    raw["statusCode"] = "200"
    with pytest.raises(InvalidResponseError, match="statusCode"):
        CezHdoClient._parse_response(raw)  # type: ignore[arg-type]


def test_parse_response_missing_data_object() -> None:
    raw: dict[Any, Any] = _valid_payload()
    raw["data"] = None
    with pytest.raises(InvalidResponseError, match="'data'"):
        CezHdoClient._parse_response(raw)  # type: ignore[arg-type]


def test_parse_response_non_ok_status_raises_api_error() -> None:
    raw: dict[Any, Any] = _valid_payload()
    raw["statusCode"] = 500
    with pytest.raises(ApiError, match="statusCode=500"):
        CezHdoClient._parse_response(raw)


def test_parse_response_missing_signals_list() -> None:
    raw: dict[Any, Any] = _valid_payload()
    raw["data"]["signals"] = None  # type: ignore[index]
    with pytest.raises(InvalidResponseError, match="data\\.signals"):
        CezHdoClient._parse_response(raw)


def test_parse_response_signal_item_not_object() -> None:
    raw: dict[Any, Any] = _valid_payload()
    raw["data"]["signals"] = ["x"]  # type: ignore[index]
    with pytest.raises(InvalidResponseError, match="signals\\[0\\] must be an object"):
        CezHdoClient._parse_response(raw)


@pytest.mark.parametrize("field", ["signal", "den", "datum", "casy"])
def test_parse_response_signal_missing_required_fields(field: str) -> None:
    raw: dict[Any, Any] = _valid_payload()
    raw["data"]["signals"][0].pop(field)  # type: ignore[index]
    with pytest.raises(InvalidResponseError, match="missing required string fields"):
        CezHdoClient._parse_response(raw)


def test_parse_response_signal_required_fields_must_be_non_empty_str() -> None:
    raw: dict[Any, Any] = _valid_payload()
    raw["data"]["signals"][0]["casy"] = ""  # type: ignore[index]
    with pytest.raises(InvalidResponseError, match="missing required string fields"):
        CezHdoClient._parse_response(raw)
