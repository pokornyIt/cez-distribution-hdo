"""Input validators (public helpers)."""

from __future__ import annotations

import re

_EAN_RE: re.Pattern[str] = re.compile(r"^8591824\d\d[45678]\d{8}$")


def validate_ean(ean: str) -> bool:
    """Validate CEZ Distribution EAN format.

    Returns True if the EAN matches CEZ Distribution constraints.

    :param ean: Input EAN string.
    """
    return bool(_EAN_RE.fullmatch(ean.strip()))
