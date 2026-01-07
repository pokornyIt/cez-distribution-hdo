"""Tests for TariffService._carry_prev_day_entries()."""

from __future__ import annotations

from collections.abc import Iterable  # noqa: TC003

from cez_distribution_hdo.models import SignalEntry, SignalsData, SignalsResponse
from cez_distribution_hdo.service import TariffService


def _se(
    *,
    signal: str,
    date_str: str,
    times_raw: str = "00:00-01:00",
    day_name: str = "X",
) -> SignalEntry:
    return SignalEntry(signal=signal, day_name=day_name, date_str=date_str, times_raw=times_raw)


def _resp(entries: list[SignalEntry]) -> SignalsResponse:
    return SignalsResponse(
        data=SignalsData(signals=entries, partner="x", raw={}),
        status_code=200,
        flash_messages=[],
        raw={},
    )


def _svc_with_last(entries: list[SignalEntry]) -> TariffService:
    svc = TariffService(tz_name="Europe/Prague")
    svc._last_response = _resp(entries)  # internal injection for tests
    return svc


def _keys(items: Iterable[SignalEntry]) -> list[tuple[str, str, str, str]]:
    """Return a stable logical key list matching service deduplicate key."""
    return [(i.signal, i.date_str, i.times_raw, i.day_name) for i in items]


def test_carry_prev_day_no_last_response_returns_new_unchanged() -> None:
    svc = TariffService(tz_name="Europe/Prague")
    new: list[SignalEntry] = [_se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00")]
    out: list[SignalEntry] = svc._carry_prev_day_entries(new)
    assert out == new


def test_carry_prev_day_present_signal_adds_prev_day_from_old() -> None:
    svc: TariffService = _svc_with_last(
        [
            _se(signal="PTV2", date_str="02.01.2025", times_raw="17:00-24:00", day_name="Thu"),
            _se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00", day_name="Fri"),
        ]
    )
    new: list[SignalEntry] = [
        _se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00", day_name="Fri")
    ]

    out: list[SignalEntry] = svc._carry_prev_day_entries(new)

    # Must include the carried prev day (02.01.2025) exactly once
    assert any(e.signal == "PTV2" and e.date_str == "02.01.2025" for e in out)
    assert _keys(out).count(("PTV2", "02.01.2025", "17:00-24:00", "Thu")) == 1

    # Order: new entries first, then carried extras (deduplicate keeps first occurrence)
    assert out[0] == new[0]


def test_carry_prev_day_present_signal_does_not_add_if_prev_day_already_in_new() -> None:
    svc: TariffService = _svc_with_last(
        [
            _se(signal="PTV2", date_str="02.01.2025", times_raw="17:00-24:00", day_name="Thu"),
            _se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00", day_name="Fri"),
        ]
    )

    # new already contains prev day
    new: list[SignalEntry] = [
        _se(signal="PTV2", date_str="02.01.2025", times_raw="17:00-24:00", day_name="Thu"),
        _se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00", day_name="Fri"),
    ]

    out: list[SignalEntry] = svc._carry_prev_day_entries(new)

    # Should be exactly the same (no duplicate, no extra)
    assert _keys(out) == _keys(new)


def test_carry_prev_day_missing_signal_keeps_prev_day_and_today_plus() -> None:
    """
    New entries start at 03.01.2025 => global prev_day is 02.01.2025.

    Missing signal "BOILER" should carry:
      - 02.01.2025 (prev day)
      - 03.01.2025 and future (>= 03.01.2025)
    """
    svc: TariffService = _svc_with_last(
        [
            _se(signal="BOILER", date_str="01.01.2025", times_raw="01:00-02:00", day_name="Wed"),
            _se(signal="BOILER", date_str="02.01.2025", times_raw="02:00-03:00", day_name="Thu"),
            _se(signal="BOILER", date_str="03.01.2025", times_raw="03:00-04:00", day_name="Fri"),
            _se(signal="BOILER", date_str="04.01.2025", times_raw="04:00-05:00", day_name="Sat"),
        ]
    )

    new: list[SignalEntry] = [
        _se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00", day_name="Fri"),
        _se(signal="PTV2", date_str="04.01.2025", times_raw="00:00-06:00", day_name="Sat"),
    ]

    out: list[SignalEntry] = svc._carry_prev_day_entries(new)

    # Must NOT carry older than prev_day_global (01.01.2025 must be absent)
    assert not any(e.signal == "BOILER" and e.date_str == "01.01.2025" for e in out)

    # Must carry prev_day_global + today+
    assert any(e.signal == "BOILER" and e.date_str == "02.01.2025" for e in out)
    assert any(e.signal == "BOILER" and e.date_str == "03.01.2025" for e in out)
    assert any(e.signal == "BOILER" and e.date_str == "04.01.2025" for e in out)


def test_carry_prev_day_missing_signal_only_prev_day_is_dropped_entirely() -> None:
    """
    Missing signal has ONLY prev_day_global, no today+ => must be dropped.
    """
    svc: TariffService = _svc_with_last(
        [
            _se(signal="BOILER", date_str="02.01.2025", times_raw="02:00-03:00", day_name="Thu"),
        ]
    )

    new: list[SignalEntry] = [
        _se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00", day_name="Fri"),
    ]

    out: list[SignalEntry] = svc._carry_prev_day_entries(new)
    # "BOILER" must not appear at all
    assert not any(e.signal == "BOILER" for e in out)
    assert _keys(out) == _keys(new)


def test_carry_prev_day_does_not_duplicate_entries_from_old_or_overlap_with_new() -> None:
    """
    Robust deduplicate:
      - old may contain duplicates
      - old may contain the same entry as new
    """
    duplicate_old: SignalEntry = _se(
        signal="PTV2", date_str="02.01.2025", times_raw="17:00-24:00", day_name="Thu"
    )

    svc: TariffService = _svc_with_last(
        [
            duplicate_old,
            duplicate_old,  # duplicate in old
            _se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00", day_name="Fri"),
        ]
    )

    # new already contains exactly the same prev-day entry (overlap old↔new)
    new: list[SignalEntry] = [
        duplicate_old,
        _se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00", day_name="Fri"),
    ]

    out: list[SignalEntry] = svc._carry_prev_day_entries(new)

    # Still must be present exactly once
    assert _keys(out).count(("PTV2", "02.01.2025", "17:00-24:00", "Thu")) == 1
    assert _keys(out) == _keys(new)


def test_carry_prev_day_per_signal_prev_day_uses_signal_min_date_not_global() -> None:
    """
    Two signals in new response:
      - PTV2 starts at 03.01.2025 (global_min_new=03.01)
      - BOILER starts at 04.01.2025 (per-signal min=04.01 => prev_day=03.01)

    For BOILER, we must carry 03.01 even though global prev_day is 02.01.
    """
    svc: TariffService = _svc_with_last(
        [
            _se(signal="BOILER", date_str="03.01.2025", times_raw="10:00-11:00", day_name="Fri"),
            _se(signal="BOILER", date_str="04.01.2025", times_raw="10:00-11:00", day_name="Sat"),
            _se(signal="PTV2", date_str="02.01.2025", times_raw="17:00-24:00", day_name="Thu"),
            _se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00", day_name="Fri"),
        ]
    )

    new: list[SignalEntry] = [
        _se(signal="PTV2", date_str="03.01.2025", times_raw="00:00-06:00", day_name="Fri"),
        _se(signal="BOILER", date_str="04.01.2025", times_raw="10:00-11:00", day_name="Sat"),
    ]

    out: list[SignalEntry] = svc._carry_prev_day_entries(new)

    # PTV2 carries its own prev_day 02.01
    assert any(e.signal == "PTV2" and e.date_str == "02.01.2025" for e in out)

    # BOILER must carry 03.01 (per-signal prev_day), not only global prev day
    assert any(e.signal == "BOILER" and e.date_str == "03.01.2025" for e in out)


def test_carry_prev_day_empty_new_entries_returns_empty() -> None:
    svc: TariffService = _svc_with_last(
        [
            _se(signal="PTV2", date_str="02.01.2025"),
        ]
    )
    out: list[SignalEntry] = svc._carry_prev_day_entries([])
    assert out == []
