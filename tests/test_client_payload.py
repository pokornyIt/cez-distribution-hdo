"""Tests for client payload building."""

import pytest

from cez_distribution_hdo.client import CezHdoClient
from cez_distribution_hdo.exceptions import InvalidRequestError


@pytest.mark.parametrize(
    ("ean", "sn", "place", "expected"),
    [
        ("123", None, None, {"ean": "123"}),
        (" 123 ", None, None, {"ean": "123"}),
        (None, "SN1", None, {"sn": "SN1"}),
        (None, None, "P1", {"place": "P1"}),
        ("123", "SN1", None, {"ean": "123", "sn": "SN1"}),
        ("123", None, "P1", {"ean": "123", "place": "P1"}),
        (None, "SN1", "P1", {"sn": "SN1", "place": "P1"}),
        ("123", "SN1", "P1", {"ean": "123", "sn": "SN1", "place": "P1"}),
    ],
)
def test_build_payload_combinations(
    ean: str | None, sn: str | None, place: str | None, expected: dict[str, str]
) -> None:
    assert CezHdoClient.build_payload(ean=ean, sn=sn, place=place) == expected


@pytest.mark.parametrize("value", ["", "   "])
def test_build_payload_rejects_empty_strings(value: str) -> None:
    # All empty => error (empty strings are falsy)
    with pytest.raises(InvalidRequestError):
        CezHdoClient.build_payload(ean=value, sn=value, place=value)


def test_build_payload_requires_at_least_one_key() -> None:
    with pytest.raises(InvalidRequestError):
        CezHdoClient.build_payload()


def test_build_payload_accepts_ean() -> None:
    payload: dict[str, str] = CezHdoClient.build_payload(ean="123")
    assert payload == {"ean": "123"}


def test_build_payload_strips_whitespace() -> None:
    assert CezHdoClient.build_payload(ean=" 123 ") == {"ean": "123"}


def test_build_payload_rejects_whitespace_only() -> None:
    with pytest.raises(InvalidRequestError):
        CezHdoClient.build_payload(ean="   ")
