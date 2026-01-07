"""Tests for client payload building."""

import pytest

from cez_distribution_hdo.client import CezHdoClient
from cez_distribution_hdo.exceptions import InvalidRequestError


@pytest.mark.parametrize(
    ("ean", "sn", "place", "expected"),
    [
        ("859182400400000000", None, None, {"ean": "859182400400000000"}),
        (" 859182400400000000 ", None, None, {"ean": "859182400400000000"}),
        (None, "SN1", None, {"sn": "SN1"}),
        (None, None, "P1", {"place": "P1"}),
    ],
)
def test_build_payload_combinations(
    ean: str | None, sn: str | None, place: str | None, expected: dict[str, str]
) -> None:
    assert CezHdoClient.build_payload(ean=ean, sn=sn, place=place) == expected


@pytest.mark.parametrize(
    ("ean", "sn", "place"),
    [
        ("859182400400000000", "SN1", None),
        ("859182400400000000", None, "P1"),
        (None, "SN1", "P1"),
        (
            "859182400400000000",
            "SN1",
            "P1",
        ),
    ],
)
def test_build_payload_rejects_zero_or_multiple_identifiers(
    ean: str | None, sn: str | None, place: str
) -> None:
    with pytest.raises(InvalidRequestError):
        CezHdoClient.build_payload(ean=ean, sn=sn, place=place)


@pytest.mark.parametrize("value", ["", "   "])
def test_build_payload_rejects_empty_strings(value: str) -> None:
    # All empty => error (empty strings are falsy)
    with pytest.raises(InvalidRequestError):
        CezHdoClient.build_payload(ean=value, sn=value, place=value)


def test_build_payload_requires_at_least_one_key() -> None:
    with pytest.raises(InvalidRequestError):
        CezHdoClient.build_payload()


def test_build_payload_accepts_ean() -> None:
    payload: dict[str, str] = CezHdoClient.build_payload(ean="859182400400000000")
    assert payload == {"ean": "859182400400000000"}


def test_build_payload_strips_whitespace() -> None:
    assert CezHdoClient.build_payload(ean=" 859182400400000000 ") == {"ean": "859182400400000000"}


def test_build_payload_rejects_whitespace_only() -> None:
    with pytest.raises(InvalidRequestError):
        CezHdoClient.build_payload(ean="   ")
