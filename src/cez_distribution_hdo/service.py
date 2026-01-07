"""High-level service for CEZ Distribution HDO schedules (HA-friendly outputs)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping  # noqa: TC003
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import logging
import re
from types import MappingProxyType
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from cez_distribution_hdo.models import SignalsData

from .client import CezHdoClient
from .const import MAX_PRINT_SIGNALS, TARIFF_HIGH, TARIFF_LOW
from .models import SignalEntry, SignalsResponse
from .tariffs import SignalSchedule, Tariff, TariffWindow, _parse_date_ddmmyyyy, build_schedules

if TYPE_CHECKING:
    from collections.abc import Iterable

logger: logging.Logger = logging.getLogger(__name__)
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


def _entry_key(e: SignalEntry) -> tuple[str, str, str, str]:
    """Return logical key for a SignalEntry.

    :param e: SignalEntry to get the key for.
    :returns: Logical key tuple.
    """
    return (e.signal, e.date_str, e.times_raw, e.day_name)


def _deduplicate_keep_order(items: Iterable[SignalEntry]) -> list[SignalEntry]:
    """Deduplicate SignalEntry items by logical key, keeping first occurrence order.

    :param items: Iterable of SignalEntry items.
    :returns: Deduplicated list of SignalEntry items.
    """
    seen: set[tuple[str, str, str, str]] = set()
    out: list[SignalEntry] = []
    for it in items:
        k: tuple[str, str, str, str] = _entry_key(it)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def _parse_date_cached_factory() -> Callable[[str], date]:
    """Small per-call cache for parsing DD.MM.YYYY repeatedly.

    :returns: Callable that parses date strings with caching.
    """
    cache: dict[str, date] = {}

    def parse(value: str) -> date:
        if value not in cache:
            cache[value] = _parse_date_ddmmyyyy(value)
        return cache[value]

    return parse


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


def _next_of_type(schedule: SignalSchedule, tariff: Tariff, now: datetime) -> TariffWindow | None:
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

    _tz: ZoneInfo
    _schedules: dict[str, SignalSchedule]
    _last_response: SignalsResponse | None
    _last_refresh: datetime | None

    def __init__(self, *, tz_name: str = "Europe/Prague") -> None:
        """Initialize the service.

        :param tz_name: Timezone name for all datetime computations.
        """
        self._tz = ZoneInfo(tz_name)
        self._schedules = {}
        self._last_response = None
        self._last_refresh = None

    def _index_new_entries(
        self, new_entries: list[SignalEntry]
    ) -> tuple[dict[str, set[date]], set[str], date]:
        """Index new entries by signal and collect dates.

        :param new_entries: List of new SignalEntry items.
        :returns: Tuple of (dates_by_signal, signals, global_min_date).
        """
        parse: Callable[[str], date] = _parse_date_cached_factory()

        dates_by_signal: dict[str, set[date]] = defaultdict(set)
        all_dates: list[date] = []
        signals: set[str] = set()

        for e in new_entries:
            d: date = parse(e.date_str)
            all_dates.append(d)
            signals.add(e.signal)
            dates_by_signal[e.signal].add(d)

        return dict(dates_by_signal), signals, min(all_dates)

    def _index_old_entries(
        self, old_entries: list[SignalEntry]
    ) -> tuple[dict[tuple[str, date], list[SignalEntry]], dict[str, list[SignalEntry]], set[str]]:
        """Index old entries by (signal, date) and by signal.

        :param old_entries: List of old SignalEntry items.
        :returns: Tuple of (by_signal_date, by_signal, signals).
        """
        parse: Callable[[str], date] = _parse_date_cached_factory()

        by_signal_date: dict[tuple[str, date], list[SignalEntry]] = defaultdict(list)
        by_signal: dict[str, list[SignalEntry]] = defaultdict(list)
        signals: set[str] = set()

        for e in old_entries:
            signals.add(e.signal)
            d: date = parse(e.date_str)
            by_signal_date[(e.signal, d)].append(e)
            by_signal[e.signal].append(e)  # preserves original order

        return dict(by_signal_date), dict(by_signal), signals

    def _carry_for_present_signals(
        self,
        *,
        new_dates_by_signal: dict[str, set[date]],
        old_by_signal_date: dict[tuple[str, date], list[SignalEntry]],
    ) -> list[SignalEntry]:
        """Carry per-signal prev_day (min_new - 1) if missing in new response.

        :param new_dates_by_signal: New entries indexed by signal and dates.
        :param old_by_signal_date: Old entries indexed by (signal, date).
        :returns: List of carried SignalEntry items.
        """
        extra: list[SignalEntry] = []

        for signal, dates in new_dates_by_signal.items():
            if not dates:
                continue

            prev_day: date = min(dates) - timedelta(days=1)

            if prev_day in dates:
                continue

            prev_items: list[SignalEntry] = old_by_signal_date.get((signal, prev_day), [])
            if not prev_items:
                continue

            extra.extend(prev_items)
            logger.debug(
                "Carrying previous-day entries: signal=%s date=%s count=%d",
                signal,
                prev_day.isoformat(),
                len(prev_items),
            )

        return extra

    def _carry_for_missing_signals(
        self,
        *,
        missing_signals: set[str],
        old_by_signal: dict[str, list[SignalEntry]],
        prev_day_global: date,
        global_min_new: date,
    ) -> list[SignalEntry]:
        """Missing signals in NEW response.

        keep only:
          - prev_day_global
          - today and future (>= global_min_new)

        BUT if it would keep ONLY prev_day_global (no today+), drop entirely.
        """
        parse: Callable[[str], date] = _parse_date_cached_factory()
        extra: list[SignalEntry] = []

        for signal in sorted(missing_signals):
            old_items: list[SignalEntry] = old_by_signal.get(signal, [])
            if not old_items:
                continue

            kept_prev: list[SignalEntry] = []
            kept_today_plus: list[SignalEntry] = []

            for e in old_items:
                d: date = parse(e.date_str)
                if d == prev_day_global:
                    kept_prev.append(e)
                elif d >= global_min_new:
                    kept_today_plus.append(e)

            # Only prev_day exists => drop the signal completely
            if kept_prev and not kept_today_plus:
                logger.debug(
                    "Skipping missing signal carry (only prev_day exists): signal=%s prev_day=%s",
                    signal,
                    prev_day_global.isoformat(),
                )
                continue

            kept: list[SignalEntry] = [*kept_prev, *kept_today_plus]
            if not kept:
                continue

            extra.extend(kept)
            logger.debug(
                "Carrying missing signal entries: signal=%s prev_day=%s today_from=%s count=%d",
                signal,
                prev_day_global.isoformat(),
                global_min_new.isoformat(),
                len(kept),
            )

        return extra

    def _carry_prev_day_entries(self, new_entries: list[SignalEntry]) -> list[SignalEntry]:
        """If the API response starts at day D, carry day D-1 entries from previous refresh.

        Enhancements:
        - Works even when some signals are missing in the new response.
        - Avoids duplicates (stable de-dup by logical entry key).

        :param new_entries: Newly fetched entries from the API.
        :returns: Extended list of entries including previous-day ones if needed.
        """
        if self._last_response is None or not new_entries:
            return new_entries

        old_entries: list[SignalEntry] = self._last_response.data.signals

        new_dates_by_signal: dict[str, set[date]]
        new_signals: set[str]
        global_min_new: date
        new_dates_by_signal, new_signals, global_min_new = self._index_new_entries(new_entries)
        prev_day_global: date = global_min_new - timedelta(days=1)

        old_by_signal_date: dict[tuple[str, date], list[SignalEntry]]
        old_by_signal: dict[str, list[SignalEntry]]
        old_signals: set[str]

        old_by_signal_date, old_by_signal, old_signals = self._index_old_entries(old_entries)

        extra_present: list[SignalEntry] = self._carry_for_present_signals(
            new_dates_by_signal=new_dates_by_signal,
            old_by_signal_date=old_by_signal_date,
        )

        missing_signals: set[str] = old_signals - new_signals
        extra_missing: list[SignalEntry] = self._carry_for_missing_signals(
            missing_signals=missing_signals,
            old_by_signal=old_by_signal,
            prev_day_global=prev_day_global,
            global_min_new=global_min_new,
        )

        extra: list[SignalEntry] = [*extra_present, *extra_missing]
        if not extra:
            return new_entries

        return _deduplicate_keep_order([*new_entries, *extra])

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

    @property
    def last_refresh_iso_utc(self) -> str | None:
        """ISO 8601 UTC timestamp of the last successful refresh, or None.

        :returns: ISO 8601 string or None.
        """
        return dt_to_iso_utc(self._last_refresh)

    @property
    def last_response(self) -> SignalsResponse | None:
        """Last raw SignalsResponse from the API, or None.

        :returns: SignalsResponse or None.
        """
        return self._last_response

    @property
    def schedules(self) -> Mapping[str, SignalSchedule]:
        """Read-only mapping of parsed schedules keyed by signal.

        :returns: Mapping of SignalSchedule per signal.
        """
        return MappingProxyType(self._schedules)

    def last_response_raw(self) -> dict[str, object] | None:
        """Last raw data dict from the API response, or None.

        :returns: Raw data dict or None.
        """
        return self._last_response.data.raw if self._last_response else None

    def get_schedule(self, signal: str) -> SignalSchedule:
        """Return parsed schedule for a signal.

        :param signal: Signal name to get the schedule for.
        :returns: SignalSchedule for the given signal.
        :raises KeyError: If signal is unknown.
        """
        if signal not in self._schedules:
            msg: str = f"Unknown signal {signal!r}. Known: {self.signals}"
            raise KeyError(msg)
        return self._schedules[signal]

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
        logger.debug("Refreshing schedules (tz=%s)", self._tz.key)
        resp: SignalsResponse
        if client is None:
            async with CezHdoClient() as c:
                resp = await c.fetch_signals(ean=ean, sn=sn, place=place)
        else:
            resp = await client.fetch_signals(ean=ean, sn=sn, place=place)
        effective_entries: list[SignalEntry] = self._carry_prev_day_entries(resp.data.signals)
        self._schedules = build_schedules(effective_entries, tz_name=self._tz.key)
        effective_data: SignalsData = replace(resp.data, signals=effective_entries)

        self._last_response = replace(resp, data=effective_data)
        names: list[str] = self.signals
        self._last_refresh = datetime.now(self._tz)

        # Logging
        preview: str = ", ".join(names[:MAX_PRINT_SIGNALS]) if names else "(none)"
        suffix: str = "..." if len(names) > MAX_PRINT_SIGNALS else ""
        logger.debug("Schedules rebuilt: signals=%d (%s%s)", len(names), preview, suffix)

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

    def snapshots(self, *, now: datetime | None = None) -> dict[str, TariffSnapshot]:
        """Compute snapshots for all available signals.

        :param now: Reference datetime (default: current time in service timezone).
        :returns: Dict of TariffSnapshot per signal.
        """
        now_dt: datetime = now or datetime.now(self._tz)
        return {s: self.snapshot(s, now=now_dt) for s in self.signals}

    def snapshots_dict(self, *, now: datetime | None = None) -> dict[str, dict[str, object]]:
        """Compute snapshots for all signals and serialize to dicts.

        :param now: Reference datetime (default: current time in service timezone).
        :returns: Dict of serialized snapshot dicts per signal.
        """
        return {s: snapshot_to_dict(sn) for s, sn in self.snapshots(now=now).items()}
