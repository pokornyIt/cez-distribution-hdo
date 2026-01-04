"""High-level service for CEZ Distribution HDO schedules (HA-friendly outputs)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .client import CezHdoClient
from .const import TARIFF_HIGH, TARIFF_LOW
from .tariffs import SignalSchedule, Tariff, TariffWindow, build_schedules

if TYPE_CHECKING:
    from .models import SignalsResponse

_UTC = ZoneInfo("UTC")


def dt_to_iso_utc(dt: datetime | None) -> str | None:
    """Return ISO 8601 timestamp in UTC with seconds, or None.

    :param dt: Input datetime (tz-aware or naive).
    :returns: ISO 8601 string in UTC, or None.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # fallback: treat as UTC (ideally, it will never come here)
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC).isoformat(timespec="seconds")


def td_to_hhmmss(td: timedelta | None) -> str | None:
    """Format timedelta as HH:MM:SS (non-negative), or None.

    :param td: Input timedelta.
    :returns: Formatted string, or None.
    """
    if td is None:
        return None
    total: int = int(td.total_seconds())
    total = max(total, 0)
    hh: int = total // 3600
    mm: int = (total % 3600) // 60
    ss: int = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def td_to_seconds(td: timedelta | None) -> int | None:
    """Timedelta to seconds (non-negative), or None.

    :param td: Input timedelta.
    :returns: Total seconds as int, or None.
    """
    if td is None:
        return None
    total: int = int(td.total_seconds())
    return max(total, 0)


def snapshot_to_dict(snapshot: TariffSnapshot) -> dict[str, object]:
    """Serialize snapshot to a plain dict (no HA entity naming).

    :param snapshot: TariffSnapshot to serialize.
    :returns: Dict with serialized values.
    """
    return {
        "signal": snapshot.signal,
        "now": dt_to_iso_utc(snapshot.now),
        "low_tariff": snapshot.low_tariff,
        "actual_tariff": snapshot.actual_tariff,
        "actual_tariff_start": dt_to_iso_utc(snapshot.actual_tariff_start),
        "actual_tariff_end": dt_to_iso_utc(snapshot.actual_tariff_end),
        "next_low_tariff_start": dt_to_iso_utc(snapshot.next_low_tariff_start),
        "next_low_tariff_end": dt_to_iso_utc(snapshot.next_low_tariff_end),
        "next_high_tariff_start": dt_to_iso_utc(snapshot.next_high_tariff_start),
        "next_high_tariff_end": dt_to_iso_utc(snapshot.next_high_tariff_end),
        "next_switch": dt_to_iso_utc(snapshot.next_switch),
        "remain_actual": td_to_hhmmss(snapshot.remain_actual),
        "remain_actual_seconds": (
            max(int(snapshot.remain_actual.total_seconds()), 0) if snapshot.remain_actual else None
        ),
    }


@dataclass(frozen=True, slots=True)
class TariffSnapshot:
    """One computed snapshot for a single signal at a given time."""

    signal: str
    now: datetime

    low_tariff: bool  # binary_sensor.*_low_tariff
    actual_tariff: str  # sensor.*_actual_tariff  ("NT"/"VT")

    actual_tariff_start: datetime | None
    actual_tariff_end: datetime | None

    next_low_tariff_start: datetime | None
    next_low_tariff_end: datetime | None

    next_high_tariff_start: datetime | None
    next_high_tariff_end: datetime | None

    next_switch: datetime | None
    remain_actual: timedelta | None  # time until next_switch


def sanitize_signal_for_entity(signal: str) -> str:
    """Convert signal name into safe suffix for HA entity_id.

    Example:
      "a1b4dp04" -> "a1b4dp04"
      "PTV2" -> "ptv2"
      "foo bar" -> "foo_bar"

    :param signal: Original signal name.
    :returns: Sanitized string.
    """
    s: str = signal.strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "signal"


def _next_of_type(schedule: SignalSchedule, tariff: str, now: datetime) -> TariffWindow | None:
    """Return next window of given tariff type *after now*.

    IMPORTANT semantics (for your "next_*"):
      - Never returns the current window of the given tariff.
      - Returns None if there is no future window of the given tariff within horizon.

    :param schedule: SignalSchedule to query.
    :param tariff: "NT" or "VT"
    :param now: Reference datetime.
    :returns: Next TariffWindow of given type, or None if not found.
    """
    if tariff == TARIFF_LOW:
        return schedule.next_nt_window(now)
    return schedule.next_vt_window(now)


class TariffService:
    """
    Fetches data once and provides HA-friendly computed values per signal.

    Strategy for HA:
      - refresh() (API call) e.g. 1x per hour/day
      - snapshot(...) can be called often (1s-5s) with no API traffic
    """

    def __init__(self, *, tz_name: str = "Europe/Prague") -> None:
        """Initialize the service.

        :param tz_name: Timezone name for all datetime computations.
        """
        self._tz = ZoneInfo(tz_name)
        self._schedules: dict[str, SignalSchedule] = {}
        self._last_response: SignalsResponse | None = None
        self._last_refresh: datetime | None = None

    @property
    def signals(self) -> list[str]:
        """List of available signal names.

        :returns: List of signal strings.
        """
        return sorted(self._schedules.keys())

    @property
    def last_refresh(self) -> datetime | None:
        """Timestamp of the last successful refresh, or None if never refreshed.

        :returns: datetime or None.
        """
        return self._last_refresh

    async def refresh(
        self,
        *,
        ean: str | None = None,
        sn: str | None = None,
        place: str | None = None,
        client: CezHdoClient | None = None,
    ) -> None:
        """Fetch latest data and rebuild schedules.

        You can pass an existing CezHdoClient, or let this method manage it.

        :param ean: EAN number of the electricity meter.
        :param sn: Serial number of the electricity meter.
        :param place: Place number of the electricity meter.
        :param client: Optional existing CezHdoClient to use.
        :raises ApiError: If the API returns an error status.
        """
        resp: SignalsResponse
        if client is None:
            async with CezHdoClient() as c:
                resp = await c.fetch_signals(ean=ean, sn=sn, place=place)
        else:
            resp = await client.fetch_signals(ean=ean, sn=sn, place=place)

        self._last_response = resp
        self._schedules = build_schedules(resp.data.signals, tz_name=self._tz.key)
        self._last_refresh = datetime.now(self._tz)

    def snapshot(self, signal: str, *, now: datetime | None = None) -> TariffSnapshot:
        """Compute all values for HA sensors for a given signal.

        :param signal: Signal name to compute snapshot for. Must be in self.signals.
        :param now: Reference datetime (default: current time in service timezone).
        :returns: TariffSnapshot with all computed values.
        :raises KeyError: If signal is unknown.
        """
        if signal not in self._schedules:
            msg: str = f"Unknown signal {signal!r}. Known: {self.signals}"
            raise KeyError(msg)

        schedule: SignalSchedule = self._schedules[signal]
        now_dt: datetime = now or datetime.now(self._tz)

        # Current
        current: TariffWindow | None = schedule.current_window(now_dt)
        actual_tariff: Tariff = schedule.current_tariff(now_dt)
        low_tariff: bool = actual_tariff == TARIFF_LOW

        # Next switch / remain
        next_switch: datetime | None = schedule.next_switch(now_dt)
        remain: timedelta | None = schedule.remaining(now_dt)
        # Next windows by type (see semantics above)
        next_low: TariffWindow | None = _next_of_type(schedule, TARIFF_LOW, now_dt)
        next_high: TariffWindow | None = _next_of_type(schedule, TARIFF_HIGH, now_dt)

        return TariffSnapshot(
            signal=signal,
            now=now_dt,
            low_tariff=low_tariff,
            actual_tariff=actual_tariff,
            actual_tariff_start=current.start if current else None,
            actual_tariff_end=current.end if current else None,
            next_low_tariff_start=next_low.start if next_low else None,
            next_low_tariff_end=next_low.end if next_low else None,
            next_high_tariff_start=next_high.start if next_high else None,
            next_high_tariff_end=next_high.end if next_high else None,
            next_switch=next_switch,
            remain_actual=remain,
        )
