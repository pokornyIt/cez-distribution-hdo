"""Tests for validators.py"""

from cez_distribution_hdo import CezHdoClient
from cez_distribution_hdo.exceptions import InvalidRequestError
from cez_distribution_hdo.validators import validate_ean


def test_validate_ean_accepts_valid() -> None:
    assert validate_ean("859182400400000000") is True


def test_validate_ean_rejects_invalid() -> None:
    assert validate_ean("859182400300000000") is False  # '3' not in [4..8]


def test_build_payload_rejects_invalid_ean() -> None:
    try:
        CezHdoClient.build_payload(ean="859182400300000000")
    except InvalidRequestError:
        pass
    else:
        raise AssertionError("Expected InvalidRequestError")  # noqa: EM101, TRY003
