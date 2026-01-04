"""Tests for service module."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from cez_distribution_hdo.const import TARIFF_HIGH, TARIFF_LOW
from cez_distribution_hdo.models import SignalEntry, SignalsData, SignalsResponse
from cez_distribution_hdo.service import (
    TariffService,
    TariffSnapshot,
    dt_to_iso_utc,
    sanitize_signal_for_entity,
    snapshot_to_dict,
    td_to_hhmmss,
    td_to_seconds,
)
from cez_distribution_hdo.tariffs import build_schedules


def test_dt_to_iso_utc_handles_none() -> None:
    assert dt_to_iso_utc(None) is None


def test_dt_to_iso_utc_converts_to_utc() -> None:
    prg = ZoneInfo("Europe/Prague")
    dt = datetime(2026, 1, 3, 12, 0, 5, tzinfo=prg)
    # Prague in January is CET (UTC+1) => 11:00:05Z
    assert dt_to_iso_utc(dt).endswith("+00:00")  # type: ignore  # noqa: PGH003
    assert dt_to_iso_utc(dt).startswith("2026-01-03T11:00:05")  # type: ignore  # noqa: PGH003

    dt = datetime(2026, 8, 3, 12, 0, 5, tzinfo=prg)
    # Prague in January is CET (UTC+1) => 11:00:05Z
    assert dt_to_iso_utc(dt).endswith("+00:00")  # type: ignore  # noqa: PGH003
    assert dt_to_iso_utc(dt).startswith("2026-08-03T10:00:05")  # type: ignore  # noqa: PGH003


def test_td_to_hhmmss_and_seconds() -> None:
    assert td_to_hhmmss(None) is None
    assert td_to_seconds(None) is None

    td = timedelta(hours=1, minutes=2, seconds=3)
    assert td_to_hhmmss(td) == "01:02:03"
    assert td_to_seconds(td) == 3723

    # negative => clamp to 0
    td_neg = timedelta(seconds=-5)
    assert td_to_hhmmss(td_neg) == "00:00:00"
    assert td_to_seconds(td_neg) == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PTV2", "ptv2"),
        ("a1b4dp04", "a1b4dp04"),
        (" Foo Bar ", "foo_bar"),
        ("foo---bar", "foo_bar"),
        ("___", "signal"),
        ("", "signal"),
    ],
)
def test_sanitize_signal_for_entity(raw: str, expected: str) -> None:
    assert sanitize_signal_for_entity(raw) == expected


def _make_service_with_schedule() -> TariffService:
    """
    Create TariffService with preloaded schedules (no HTTP).

    Schedule used:
      03.01.2026: NT 00:00-06:00 and 17:00-24:00
      04.01.2026: NT 00:00-06:00

    So:
      - VT 06:00-17:00 on 03.01
      - NT 17:00 on 03.01 -> 06:00 on 04.01 (merged across midnight)
      - VT 06:00 on 04.01 -> end of horizon (05.01 00:00)
    """
    svc = TariffService(tz_name="Europe/Prague")
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
    svc._schedules = build_schedules(
        entries, tz_name="Europe/Prague"
    )  # internal injection for tests
    return svc


def test_service_snapshot_unknown_signal_raises() -> None:
    svc: TariffService = _make_service_with_schedule()
    with pytest.raises(KeyError, match="Unknown signal"):
        svc.snapshot("UNKNOWN")


def test_service_snapshot_when_in_vt() -> None:
    tz = ZoneInfo("Europe/Prague")
    svc: TariffService = _make_service_with_schedule()

    now = datetime(2026, 1, 3, 12, 0, tzinfo=tz)  # VT 06-17
    snap: TariffSnapshot = svc.snapshot("PTV2", now=now)

    assert snap.low_tariff is False
    assert snap.actual_tariff == TARIFF_HIGH
    assert snap.actual_tariff_start == datetime(2026, 1, 3, 6, 0, tzinfo=tz)
    assert snap.actual_tariff_end == datetime(2026, 1, 3, 17, 0, tzinfo=tz)

    # next NT should be 17:00-06:00 next day (merged interval)
    assert snap.next_low_tariff_start == datetime(2026, 1, 3, 17, 0, tzinfo=tz)
    assert snap.next_low_tariff_end == datetime(2026, 1, 4, 6, 0, tzinfo=tz)

    # next VT should be after the NT ends: 04.01 06:00-05.01 00:00
    assert snap.next_high_tariff_start == datetime(2026, 1, 4, 6, 0, tzinfo=tz)
    assert snap.next_high_tariff_end == datetime(2026, 1, 5, 0, 0, tzinfo=tz)

    # next switch boundary from VT is start of next NT at 17:00
    assert snap.next_switch == datetime(2026, 1, 3, 17, 0, tzinfo=tz)
    assert snap.remain_actual == timedelta(hours=5)


def test_service_snapshot_when_in_nt() -> None:
    tz = ZoneInfo("Europe/Prague")
    svc: TariffService = _make_service_with_schedule()

    now = datetime(2026, 1, 3, 18, 0, tzinfo=tz)  # NT 17:00 -> 04.01 06:00
    snap: TariffSnapshot = svc.snapshot("PTV2", now=now)

    assert snap.low_tariff is True
    assert snap.actual_tariff == TARIFF_LOW
    assert snap.actual_tariff_start == datetime(2026, 1, 3, 17, 0, tzinfo=tz)
    assert snap.actual_tariff_end == datetime(2026, 1, 4, 6, 0, tzinfo=tz)

    # next NT is strictly future => after current NT ends there is no other NT in horizon
    assert snap.next_low_tariff_start is None
    assert snap.next_low_tariff_end is None

    # next VT is after NT ends
    assert snap.next_high_tariff_start == datetime(2026, 1, 4, 6, 0, tzinfo=tz)
    assert snap.next_high_tariff_end == datetime(2026, 1, 5, 0, 0, tzinfo=tz)

    # next switch from NT is end of NT at 06:00
    assert snap.next_switch == datetime(2026, 1, 4, 6, 0, tzinfo=tz)
    assert snap.remain_actual == timedelta(hours=12)


def test_snapshot_to_dict_serializes_expected_fields() -> None:
    tz = ZoneInfo("Europe/Prague")
    svc: TariffService = _make_service_with_schedule()

    now = datetime(2026, 1, 3, 12, 0, tzinfo=tz)
    snap: TariffSnapshot = svc.snapshot("PTV2", now=now)

    d: dict[str, object] = snapshot_to_dict(snap)

    assert d["signal"] == "PTV2"
    assert d["low_tariff"] is False
    assert d["actual_tariff"] == TARIFF_HIGH

    # ISO strings in UTC
    assert isinstance(d["now"], str)
    assert str(d["now"]).endswith("+00:00")

    assert isinstance(d["actual_tariff_start"], str)
    assert isinstance(d["actual_tariff_end"], str)

    # remain string and seconds
    assert d["remain_actual"] == "05:00:00"
    assert d["remain_actual_seconds"] == 18000


@pytest.mark.asyncio
async def test_service_refresh_uses_injected_client_and_sets_signals() -> None:
    class DummyClient:
        async def fetch_signals(self, **_kwargs) -> SignalsResponse:  # noqa: ANN003
            return SignalsResponse(
                data=SignalsData(
                    signals=[
                        SignalEntry(
                            signal="PTV2",
                            day_name="Sobota",
                            date_str="03.01.2026",
                            times_raw="00:00-06:00",
                        ),
                        SignalEntry(
                            signal="BOILER",
                            day_name="Sobota",
                            date_str="03.01.2026",
                            times_raw="10:00-12:00",
                        ),
                    ],
                    partner="x",
                    raw={},
                ),
                status_code=200,
                flash_messages=[],
                raw={},
            )

    svc = TariffService(tz_name="Europe/Prague")
    await svc.refresh(ean="123", client=DummyClient())  # type: ignore[arg-type]

    assert svc.signals == ["BOILER", "PTV2"]
    assert svc.last_refresh is not None
