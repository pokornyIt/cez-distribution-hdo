"""Tariff schedule utilities for CEZ Distribution HDO signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from .const import TARIFF_HIGH, TARIFF_LOW
from .exceptions import InvalidResponseError
from .models import DateTimeInterval, SignalEntry, TariffWindow

Tariff = Literal["NT", "VT"]


def _ensure_tz(dt: datetime, tz: ZoneInfo) -> datetime:
    """Ensure datetime is in given timezone.

    :param dt: Input datetime (naive or tz-aware).
    :param tz: Timezone to ensure.
    :returns: tz-aware datetime in given timezone.
    """
    # If naive, assume tz; if aware, convert to tz.
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _parse_date_ddmmyyyy(value: str) -> date:
    """Parse date in DD.MM.YYYY format.

    :param value: Date string in DD.MM.YYYY format.
    :returns: date object.
    """
    try:
        parts: list[str] = value.strip().split(".", 2)
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except Exception as e:
        msg: str = f"Invalid date format: {value!r}"
        raise InvalidResponseError(msg) from e


def _parse_time_hhmm(value: str) -> tuple[time, bool]:
    """Parse HH:MM into time.

    Returns (time, is_24h) where is_24h=True for special 24:00 end marker.

    :param value: Time string in HH:MM format, or "24:00".
    :returns: (time object, is_24h boolean)
    """
    value = value.strip()
    if value == "24:00":
        return time(0, 0), True
    data_split: list[str] = value.split(":", 1)
    return time(int(data_split[0]), int(data_split[1])), False


def merge_touching(intervals: list[DateTimeInterval]) -> list[DateTimeInterval]:
    """Merge overlapping OR touching intervals (start <= previous.end).

    :param intervals: List of DateTimeInterval objects, sorted by start time.
    :returns: List of merged DateTimeInterval objects.
    """
    if not intervals:
        return []
    intervals_sorted: list[DateTimeInterval] = sorted(intervals, key=lambda x: x.start)

    merged: list[DateTimeInterval] = [intervals_sorted[0]]
    for iv in intervals_sorted[1:]:
        last: DateTimeInterval = merged[-1]
        if iv.start <= last.end:  # IMPORTANT: <= merges touching boundaries at midnight
            merged[-1] = DateTimeInterval(start=last.start, end=max(last.end, iv.end))
        else:
            merged.append(iv)
    return merged


def parse_casy(date_value: date, casy_raw: str, tz: ZoneInfo) -> list[DateTimeInterval]:
    """
    Parse 'casy' string into tz-aware datetime intervals (low tariff windows).

    Example:
      "00:00-06:00;   07:00-09:00;   17:00-24:00"

    :param date_value: Date for which the casy_raw applies.
    :param casy_raw: Raw 'casy' string from API.
    :param tz: Timezone for resulting datetime objects.
    :returns: List of DateTimeInterval objects (may be empty).
    """
    if not casy_raw:
        return []

    # split by ';' and ignore empty parts (trailing ';' is common)
    parts: list[str] = [p.strip() for p in casy_raw.split(";") if p.strip()]
    intervals: list[DateTimeInterval] = []

    for part in parts:
        if "-" not in part:
            msg: str = f"Invalid time window format: {part!r}"
            raise InvalidResponseError(msg)

        start_end: list[str] = [x.strip() for x in part.split("-", 1)]
        try:
            start_time: tuple[time, bool] = _parse_time_hhmm(start_end[0])
            end_time: tuple[time, bool] = _parse_time_hhmm(start_end[1])
        except Exception as e:
            msg: str = f"Invalid time format in window: {part!r}"
            raise InvalidResponseError(msg) from e

        start_dt: datetime = datetime.combine(date_value, start_time[0], tzinfo=tz)
        end_dt: datetime

        if end_time[1]:
            # 24:00 => next day 00:00
            end_dt = datetime.combine(date_value + timedelta(days=1), time(0, 0), tzinfo=tz)
        else:
            end_dt = datetime.combine(date_value, end_time[0], tzinfo=tz)
            # if provider ever returns something crossing midnight, handle it safely
            if end_dt <= start_dt:
                end_dt = end_dt + timedelta(days=1)

        intervals.append(DateTimeInterval(start=start_dt, end=end_dt))

    return merge_touching(intervals)


@dataclass(frozen=True, slots=True)
class SignalSchedule:
    """
    Low-tariff schedule for one `signal` (across multiple days).

    - `low_intervals`: merged NT windows across the loaded horizon
    - `range_start`/`range_end`: known time span covered by the loaded data
    """

    signal: str
    low_intervals: list[DateTimeInterval]
    range_start: datetime
    range_end: datetime
    tz: ZoneInfo

    def _vt_intervals(self) -> list[DateTimeInterval]:
        """Compute VT intervals as complement of NT within [range_start, range_end).

        :returns: List of DateTimeInterval objects representing VT intervals.
        """
        start: datetime = self.range_start
        vt: list[DateTimeInterval] = []

        for low in self.low_intervals:
            if low.end <= self.range_start:
                continue
            if low.start >= self.range_end:
                break

            low_s: datetime = max(low.start, self.range_start)
            low_e: datetime = min(low.end, self.range_end)

            if start < low_s:
                vt.append(DateTimeInterval(start=start, end=low_s))
            start = max(start, low_e)

        if start < self.range_end:
            vt.append(DateTimeInterval(start=start, end=self.range_end))

        return vt

    def current_tariff(self, dt: datetime | None = None) -> Tariff:
        """Return current tariff ("NT" or "VT") at given datetime.

        :param dt: tz-aware datetime to check; if None, uses current time.
        :returns: "NT" if dt is within any low-tariff interval, else "VT".
        """
        dt = _ensure_tz(dt or datetime.now(self.tz), self.tz)
        return TARIFF_LOW if any(iv.contains(dt) for iv in self.low_intervals) else TARIFF_HIGH

    def next_switch(self, dt: datetime | None = None) -> datetime | None:
        """Return next boundary (either start or end of a low interval) after dt.

        If no future boundary exists in loaded data, returns None.

        :param dt: tz-aware datetime to check from; if None, uses current time.
        :returns: Next boundary datetime, or None if outside known horizon / no future boundary.
        """
        dt = _ensure_tz(dt or datetime.now(self.tz), self.tz)

        boundaries: list[datetime] = []
        for iv in self.low_intervals:
            if iv.start > dt:
                boundaries.append(iv.start)
            if iv.end > dt:
                boundaries.append(iv.end)
        nxt: datetime | None = min(boundaries) if boundaries else None
        if nxt is None:
            return None
        return nxt if nxt < self.range_end else None

    def remaining(self, dt: datetime | None = None) -> timedelta | None:
        """How long until next switch. None if no next switch within horizon.

        :param dt: tz-aware datetime to check from; if None, uses current time.
        :returns: timedelta until next switch, or None if no next switch within horizon.
        """
        dt = _ensure_tz(dt or datetime.now(self.tz), self.tz)
        nxt: datetime | None = self.next_switch(dt)
        return (nxt - dt) if nxt else None

    def current_window(self, dt: datetime | None = None) -> TariffWindow | None:
        """Return the current tariff window (NT or VT) that contains dt.

        If dt is outside loaded horizon, returns None.

        :param dt: tz-aware datetime to check; if None, uses current time.
        :returns: TariffWindow if dt is within known horizon, else None.
        """
        dt = _ensure_tz(dt or datetime.now(self.tz), self.tz)
        if not (self.range_start <= dt < self.range_end):
            return None

        # NT?
        for iv in self.low_intervals:
            if iv.contains(dt):
                return TariffWindow(TARIFF_LOW, iv.start, iv.end)

        # VT => complement between NT windows
        vt: list[DateTimeInterval] = self._vt_intervals()
        for iv in vt:
            if iv.contains(dt):
                return TariffWindow(TARIFF_HIGH, iv.start, iv.end)

        # Should not happen if horizon is consistent
        return None

    def next_nt_window(self, dt: datetime | None = None) -> TariffWindow | None:
        """Return the next (future) NT window strictly after dt.

        - Never returns the current NT window.
        - Returns None if there is no future NT window within horizon.

        :param dt: tz-aware datetime to check; if None, uses current time.
        :returns: TariffWindow if found, else None.
        """
        dt = _ensure_tz(dt or datetime.now(self.tz), self.tz)

        for iv in self.low_intervals:
            if iv.start > dt:  # STRICT: start must be in the future
                return TariffWindow(TARIFF_LOW, iv.start, iv.end)

        return None

    def next_vt_window(self, dt: datetime | None = None) -> TariffWindow | None:
        """Return the next (future) VT window strictly after dt.

        VT is computed as the complement of NT within [range_start, range_end).

        - Never returns the current VT window.
        - Returns None if there is no future VT window within horizon.

        :param dt: tz-aware datetime to check; if None, uses current time.
        :returns: TariffWindow if found, else None.
        """
        dt = _ensure_tz(dt or datetime.now(self.tz), self.tz)

        # If outside horizon, we can't compute VT reliably
        if not (self.range_start <= dt < self.range_end):
            return None

        for iv in self._vt_intervals():
            if iv.start > dt:  # STRICT: start must be in the future
                return TariffWindow(TARIFF_HIGH, iv.start, iv.end)

        return None


def build_schedules(
    entries: list[SignalEntry],
    *,
    tz_name: str = "Europe/Prague",
) -> dict[str, SignalSchedule]:
    """Group entries by `signal` and build parsed schedules (NT windows).

    Horizon per signal is computed from min/max dates in entries:
    [min_date 00:00, (max_date + 1 day) 00:00)

    :param entries: List of SignalEntry objects.
    :returns: dict {signal: SignalSchedule}
    """
    tz = ZoneInfo(tz_name)

    by_signal: dict[str, list[SignalEntry]] = {}
    for e in entries:
        by_signal.setdefault(e.signal, []).append(e)

    schedules: dict[str, SignalSchedule] = {}

    for signal, items in by_signal.items():
        dates: list[date] = [_parse_date_ddmmyyyy(it.date_str) for it in items]
        min_d: date = min(dates)
        max_d: date = max(dates)

        range_start: datetime = datetime.combine(min_d, time(0, 0), tzinfo=tz)
        range_end: datetime = datetime.combine(max_d + timedelta(days=1), time(0, 0), tzinfo=tz)

        low: list[DateTimeInterval] = []
        for it in items:
            d: date = _parse_date_ddmmyyyy(it.date_str)
            low.extend(parse_casy(d, it.times_raw, tz))

        low = merge_touching(low)

        schedules[signal] = SignalSchedule(
            signal=signal,
            low_intervals=low,
            range_start=range_start,
            range_end=range_end,
            tz=tz,
        )
    return schedules
