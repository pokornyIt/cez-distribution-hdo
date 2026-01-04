"""Tests for cez_distribution_hdo.tariffs module."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from cez_distribution_hdo.const import TARIFF_HIGH, TARIFF_LOW
from cez_distribution_hdo.exceptions import InvalidResponseError
from cez_distribution_hdo.models import DateTimeInterval, SignalEntry, TariffWindow
from cez_distribution_hdo.tariffs import (
    SignalSchedule,
    _parse_date_ddmmyyyy,
    _parse_time_hhmm,
    build_schedules,
    merge_touching,
    parse_casy,
)


def test_parse_date_ddmmyyyy_ok() -> None:
    assert _parse_date_ddmmyyyy("03.01.2026") == date(2026, 1, 3)
    assert _parse_date_ddmmyyyy(" 03.12.2025 ") == date(2025, 12, 3)


@pytest.mark.parametrize("value", ["2026-01-03", "03/01/2026", "xx.xx.xxxx", "", "  "])
def test_parse_date_ddmmyyyy_invalid(value: str) -> None:
    with pytest.raises(InvalidResponseError, match="Invalid date format"):
        _parse_date_ddmmyyyy(value)


@pytest.mark.parametrize(
    ("value", "expected_time", "expected_is_24"),
    [
        ("00:00", time(0, 0), False),
        ("07:05", time(7, 5), False),
        ("7:05", time(7, 5), False),
        ("7:5", time(7, 5), False),
        ("24:00", time(0, 0), True),
    ],
)
def test_parse_time_hhmm_ok(value: str, expected_time: time, expected_is_24: bool) -> None:  # noqa: FBT001
    t: tuple[time, bool] = _parse_time_hhmm(value)
    assert t[0] == expected_time
    assert t[1] is expected_is_24


@pytest.mark.parametrize(
    "value", ["", "xx:yy", "0700", "24:01", "99:99", "-1:5", "12:-5", ":", "7:60"]
)
def test_parse_time_hhmm_invalid(value: str) -> None:
    # _parse_time_hhmm currently raises ValueError/TypeError directly.
    # That's fine; we just assert it fails.
    with pytest.raises(Exception):  # noqa: B017, PT011
        _parse_time_hhmm(value)


def test_merge_touching_merges_overlap_and_touching() -> None:
    tz = ZoneInfo("Europe/Prague")
    intervals: list[DateTimeInterval] = [
        DateTimeInterval(
            datetime(2026, 1, 3, 0, 0, tzinfo=tz), datetime(2026, 1, 3, 6, 0, tzinfo=tz)
        ),
        # overlaps
        DateTimeInterval(
            datetime(2026, 1, 3, 5, 0, tzinfo=tz), datetime(2026, 1, 3, 7, 0, tzinfo=tz)
        ),
        # touches (start == previous.end)  # noqa: ERA001
        DateTimeInterval(
            datetime(2026, 1, 3, 7, 0, tzinfo=tz), datetime(2026, 1, 3, 9, 0, tzinfo=tz)
        ),
        # gap => separate
        DateTimeInterval(
            datetime(2026, 1, 3, 10, 0, tzinfo=tz), datetime(2026, 1, 3, 11, 0, tzinfo=tz)
        ),
    ]

    merged: list[DateTimeInterval] = merge_touching(intervals)
    assert len(merged) == 2
    assert merged[0].start == datetime(2026, 1, 3, 0, 0, tzinfo=tz)
    assert merged[0].end == datetime(2026, 1, 3, 9, 0, tzinfo=tz)
    assert merged[1].start == datetime(2026, 1, 3, 10, 0, tzinfo=tz)
    assert merged[1].end == datetime(2026, 1, 3, 11, 0, tzinfo=tz)


def test_nt_crosses_midnight_and_merges() -> None:
    tz = ZoneInfo("Europe/Prague")

    entries: list[SignalEntry] = [
        SignalEntry(
            signal="PTV2", day_name="Sobota", date_str="03.01.2026", times_raw="17:00-24:00"
        ),
        SignalEntry(
            signal="PTV2", day_name="Neděle", date_str="04.01.2026", times_raw="00:00-06:00"
        ),
    ]

    schedules: dict[str, SignalSchedule] = build_schedules(entries)
    s: SignalSchedule = schedules["PTV2"]

    # NT should be one continuous interval 03.01 17:00 -> 04.01 06:00
    assert len(s.low_intervals) == 1
    assert s.low_intervals[0].start == datetime(2026, 1, 3, 17, 0, tzinfo=tz)
    assert s.low_intervals[0].end == datetime(2026, 1, 4, 6, 0, tzinfo=tz)

    # 03.01 23:00 is NT
    assert s.current_tariff(datetime(2026, 1, 3, 23, 0, tzinfo=tz)) == TARIFF_LOW
    # 04.01 05:00 is still NT
    assert s.current_tariff(datetime(2026, 1, 4, 5, 0, tzinfo=tz)) == TARIFF_LOW
    # 04.01 06:01 is VT
    assert s.current_tariff(datetime(2026, 1, 4, 6, 1, tzinfo=tz)) == TARIFF_HIGH


def test_parse_casy_splits_and_ignores_trailing_semicolons() -> None:
    tz = ZoneInfo("Europe/Prague")
    d = date(2026, 1, 3)
    intervals: list[DateTimeInterval] = parse_casy(d, "00:00-06:00;   07:00-09:00;   ", tz)

    assert [(i.start.time(), i.end.time()) for i in intervals] == [
        (time(0, 0), time(6, 0)),
        (time(7, 0), time(9, 0)),
    ]


def test_parse_casy_24_00_creates_next_day_midnight() -> None:
    tz = ZoneInfo("Europe/Prague")
    d = date(2026, 1, 3)
    intervals: list[DateTimeInterval] = parse_casy(d, "17:00-24:00", tz)

    assert len(intervals) == 1
    assert intervals[0].start == datetime(2026, 1, 3, 17, 0, tzinfo=tz)
    assert intervals[0].end == datetime(2026, 1, 4, 0, 0, tzinfo=tz)


def test_parse_casy_crossing_midnight_end_before_start_is_shifted() -> None:
    # even if provider returns something weird like 23:00-01:00, we shift end to next day
    tz = ZoneInfo("Europe/Prague")
    d = date(2026, 1, 3)
    intervals: list[DateTimeInterval] = parse_casy(d, "23:00-01:00", tz)

    assert len(intervals) == 1
    assert intervals[0].start == datetime(2026, 1, 3, 23, 0, tzinfo=tz)
    assert intervals[0].end == datetime(2026, 1, 4, 1, 0, tzinfo=tz)


@pytest.mark.parametrize(
    "invalid_window",
    [
        "not-a-window",
        "25:00-26:00",
        "12:60-13:00",
        "00:00-24:01",
        "12:00/",
        "/13:00",
        "12:00-",
        "00:00-aa:bb",
    ],
)
def test_parse_casy_invalid_window_format_raises(invalid_window: str) -> None:
    tz = ZoneInfo("Europe/Prague")
    d = date(2026, 1, 3)

    with pytest.raises(InvalidResponseError, match="Invalid time"):
        parse_casy(d, invalid_window, tz)


def test_build_schedules_groups_signals_and_sets_horizon() -> None:
    tz = ZoneInfo("Europe/Prague")
    entries: list[SignalEntry] = [
        SignalEntry(
            signal="PTV2", day_name="Sobota", date_str="03.01.2026", times_raw="00:00-06:00"
        ),
        SignalEntry(
            signal="PTV2", day_name="Neděle", date_str="04.01.2026", times_raw="00:00-06:00"
        ),
        SignalEntry(
            signal="BOILER", day_name="Sobota", date_str="03.01.2026", times_raw="10:00-12:00"
        ),
    ]

    schedules: dict[str, SignalSchedule] = build_schedules(entries)
    assert set(schedules.keys()) == {"PTV2", "BOILER"}

    s_ptv2: SignalSchedule = schedules["PTV2"]
    assert s_ptv2.range_start == datetime(2026, 1, 3, 0, 0, tzinfo=tz)
    assert s_ptv2.range_end == datetime(2026, 1, 5, 0, 0, tzinfo=tz)  # max date 04.01 + 1 day

    s_boiler: SignalSchedule = schedules["BOILER"]
    assert s_boiler.range_start == datetime(2026, 1, 3, 0, 0, tzinfo=tz)
    assert s_boiler.range_end == datetime(2026, 1, 4, 0, 0, tzinfo=tz)


def test_vt_intervals_are_complement_of_nt() -> None:
    tz = ZoneInfo("Europe/Prague")
    entries: list[SignalEntry] = [
        SignalEntry(
            signal="PTV2",
            day_name="Sobota",
            date_str="03.01.2026",
            times_raw="00:00-06:00; 17:00-24:00",
        ),
        SignalEntry(
            signal="PTV2", day_name="Neděle", date_str="04.01.2026", times_raw="00:00-06:00"
        ),
    ]
    s: SignalSchedule = build_schedules(entries)["PTV2"]

    # NT merges across midnight: 03.01 17:00 -> 04.01 06:00
    assert len(s.low_intervals) == 2
    assert s.low_intervals[0].start == datetime(2026, 1, 3, 0, 0, tzinfo=tz)
    assert s.low_intervals[0].end == datetime(2026, 1, 3, 6, 0, tzinfo=tz)
    assert s.low_intervals[1].start == datetime(2026, 1, 3, 17, 0, tzinfo=tz)
    assert s.low_intervals[1].end == datetime(2026, 1, 4, 6, 0, tzinfo=tz)

    vt: list[DateTimeInterval] = s._vt_intervals()
    # Within horizon [03.01 00:00, 05.01 00:00):
    # VT should be 03.01 06:00-17:00 and 04.01 06:00-05.01 00:00
    assert vt[0].start == datetime(2026, 1, 3, 6, 0, tzinfo=tz)
    assert vt[0].end == datetime(2026, 1, 3, 17, 0, tzinfo=tz)
    assert vt[1].start == datetime(2026, 1, 4, 6, 0, tzinfo=tz)
    assert vt[1].end == datetime(2026, 1, 5, 0, 0, tzinfo=tz)


def test_current_window_returns_nt_and_vt() -> None:
    tz = ZoneInfo("Europe/Prague")
    entries: list[SignalEntry] = [
        SignalEntry(
            signal="PTV2",
            day_name="Sobota",
            date_str="03.01.2026",
            times_raw="00:00-06:00; 17:00-24:00",
        ),
        SignalEntry(
            signal="PTV2", day_name="Neděle", date_str="04.01.2026", times_raw="00:00-06:00"
        ),
    ]
    s: SignalSchedule = build_schedules(entries)["PTV2"]

    w_nt: TariffWindow | None = s.current_window(datetime(2026, 1, 3, 1, 0, tzinfo=tz))
    assert w_nt is not None
    assert w_nt.tariff == TARIFF_LOW
    assert w_nt.start == datetime(2026, 1, 3, 0, 0, tzinfo=tz)
    assert w_nt.end == datetime(2026, 1, 3, 6, 0, tzinfo=tz)

    w_vt: TariffWindow | None = s.current_window(datetime(2026, 1, 3, 12, 0, tzinfo=tz))
    assert w_vt is not None
    assert w_vt.tariff == TARIFF_HIGH
    assert w_vt.start == datetime(2026, 1, 3, 6, 0, tzinfo=tz)
    assert w_vt.end == datetime(2026, 1, 3, 17, 0, tzinfo=tz)


def test_current_window_outside_horizon_is_none() -> None:
    tz = ZoneInfo("Europe/Prague")
    entries: list[SignalEntry] = [
        SignalEntry(
            signal="PTV2", day_name="Sobota", date_str="03.01.2026", times_raw="00:00-06:00"
        ),
    ]
    s: SignalSchedule = build_schedules(entries)["PTV2"]

    assert s.current_window(datetime(2026, 1, 2, 23, 59, tzinfo=tz)) is None
    assert (
        s.current_window(datetime(2026, 1, 4, 0, 0, tzinfo=tz)) is None
    )  # end boundary is exclusive


def test_next_switch_and_remaining() -> None:
    tz = ZoneInfo("Europe/Prague")
    entries: list[SignalEntry] = [
        SignalEntry(
            signal="PTV2",
            day_name="Sobota",
            date_str="03.01.2026",
            times_raw="00:00-06:00; 17:00-24:00",
        ),
        SignalEntry(
            signal="PTV2", day_name="Neděle", date_str="04.01.2026", times_raw="00:00-06:00"
        ),
    ]
    s: SignalSchedule = build_schedules(entries)["PTV2"]

    now = datetime(2026, 1, 3, 12, 0, tzinfo=tz)  # VT (06-17)
    nxt: datetime | None = s.next_switch(now)
    assert nxt == datetime(2026, 1, 3, 17, 0, tzinfo=tz)

    rem: timedelta | None = s.remaining(now)
    assert rem == timedelta(hours=5)

    # if we're in NT 17-06, next switch is 06:00 next day
    now2 = datetime(2026, 1, 3, 18, 0, tzinfo=tz)
    nxt2: datetime | None = s.next_switch(now2)
    assert nxt2 == datetime(2026, 1, 4, 6, 0, tzinfo=tz)


def test_next_nt_window_is_future_only() -> None:
    tz = ZoneInfo("Europe/Prague")
    entries: list[SignalEntry] = [
        SignalEntry(
            signal="PTV2",
            day_name="Sobota",
            date_str="03.01.2026",
            times_raw="00:00-06:00; 17:00-24:00",
        ),
        SignalEntry(
            signal="PTV2", day_name="Neděle", date_str="04.01.2026", times_raw="00:00-06:00"
        ),
    ]
    s: SignalSchedule = build_schedules(entries)["PTV2"]

    now = datetime(2026, 1, 3, 1, 0, tzinfo=tz)  # currently NT 00-06
    next_nt: TariffWindow | None = s.next_nt_window(now)
    assert next_nt is not None
    assert next_nt.start == datetime(2026, 1, 3, 17, 0, tzinfo=tz)


def test_next_vt_window_is_future_only() -> None:
    tz = ZoneInfo("Europe/Prague")
    entries: list[SignalEntry] = [
        SignalEntry(
            signal="PTV2",
            day_name="Sobota",
            date_str="03.01.2026",
            times_raw="00:00-06:00; 17:00-24:00",
        ),
        SignalEntry(
            signal="PTV2", day_name="Neděle", date_str="04.01.2026", times_raw="00:00-06:00"
        ),
    ]
    s: SignalSchedule = build_schedules(entries)["PTV2"]

    now = datetime(2026, 1, 3, 12, 0, tzinfo=tz)  # currently VT 06-17
    next_vt: TariffWindow | None = s.next_vt_window(now)
    assert next_vt is not None
    # next VT starts after the next NT block ends (after 04.01 06:00)
    assert next_vt.start == datetime(2026, 1, 4, 6, 0, tzinfo=tz)


def test_build_schedules_with_empty_entries_returns_empty_dict() -> None:
    schedules: dict[str, SignalSchedule] = build_schedules([])
    assert schedules == {}


def test_next_switch_and_remaining_on_boundaries_start_and_end() -> None:
    tz = ZoneInfo("Europe/Prague")
    entries: list[SignalEntry] = [
        SignalEntry(
            signal="PTV2",
            day_name="Sobota",
            date_str="03.01.2026",
            times_raw="00:00-06:00",
        ),
    ]
    s: SignalSchedule = build_schedules(entries)["PTV2"]

    at_start = datetime(2026, 1, 3, 0, 0, tzinfo=tz)
    at_end = datetime(2026, 1, 3, 6, 0, tzinfo=tz)

    # At exact start of NT (00:00), next switch is the end (06:00)
    assert s.next_switch(at_start) == at_end
    assert s.remaining(at_start) == (at_end - at_start)

    # At exact end of NT (06:00), there is no future NT boundary in loaded data
    assert s.next_switch(at_end) is None
    assert s.remaining(at_end) is None


def test_merge_touching_three_intervals_cascades() -> None:
    tz = ZoneInfo("Europe/Prague")
    entries: list[SignalEntry] = [
        SignalEntry(
            signal="PTV2",
            day_name="Sobota",
            date_str="03.01.2026",
            times_raw="00:00-01:00; 01:00-02:00; 01:30-03:00",
        ),
    ]
    s: SignalSchedule = build_schedules(entries)["PTV2"]

    # All three should merge into one: 00:00 -> 03:00
    assert len(s.low_intervals) == 1
    assert s.low_intervals[0].start == datetime(2026, 1, 3, 0, 0, tzinfo=tz)
    assert s.low_intervals[0].end == datetime(2026, 1, 3, 3, 0, tzinfo=tz)
