"""Data models for CEZ Distribution HDO API responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from datetime import datetime


Tariff = Literal["NT", "VT"]


@dataclass(frozen=True, slots=True, order=True)
class DateTimeInterval:
    """One continuous low-tariff (NT) interval."""

    start: datetime  # tz-aware
    end: datetime  # tz-aware, end > start

    def contains(self, dt: datetime) -> bool:
        """Return True if dt is within the interval.

        :param dt: tz-aware datetime to check.
        :returns: True if dt is within [start, end).
        """
        return self.start <= dt < self.end


@dataclass(frozen=True, slots=True)
class TariffWindow:
    """Tariff window (NT or VT) for a signal."""

    tariff: Tariff  # "NT" or "VT"
    start: datetime
    end: datetime

    def contains(self, dt: datetime) -> bool:
        """Return True if dt is within the window.

        :param dt: tz-aware datetime to check.
        :returns: True if dt is within [start, end).
        """
        return self.start <= dt < self.end


@dataclass(frozen=True, slots=True)
class SignalEntry:
    """
    One daily signal entry from the API.

    :param signal: Signal code, e.g. "PTV2"
    :param day_name: Czech day name, e.g. "Sobota"
    :param date_str: Date in format "DD.MM.YYYY"
    :param times_raw: Times string, e.g. "00:00-06:00; 07:00-09:00; ..."
    """

    signal: str
    day_name: str  # is "den" in JSON
    date_str: str  # is "datum" in JSON
    times_raw: str  # is "casy" in JSON


@dataclass(frozen=True, slots=True)
class SignalsData:
    """
    Main "data" payload from the API.

    Only fields you currently need are typed strictly; rest can be added later.

    :param signals: List of signal entries.
    :param partner: Partner id (as returned by API), if present.
    :param raw: Full raw dict of "data" for forward compatibility.
    """

    signals: list[SignalEntry]
    partner: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SignalsResponse:
    """
    Full API response wrapper.

    :param data: Parsed data section.
    :param status_code: statusCode from API JSON payload.
    :param flash_messages: flashMessages from API JSON payload.
    :param raw: Full raw response dict.
    """

    data: SignalsData
    status_code: int
    flash_messages: list[Any]
    raw: dict[str, Any]
