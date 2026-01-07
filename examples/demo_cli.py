#!/usr/bin/env python3
"""
Demo CLI for cez-distribution-hdo.

1) Fetch schedules using ean/sn/place.
2) Print all computed snapshot values for all signals.
3) Refresh display every 1s for 5 seconds (no extra API calls) to show changes.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from cez_distribution_hdo.service import TariffService, TariffSnapshot, snapshot_to_dict


def _clean_str(value: str | None) -> str | None:
    """Return stripped string or None if empty/whitespace.

    :param value: input string or None
    :return: cleaned string or None
    """
    if value is None:
        return None
    v: str = value.strip()
    return v if v else None


def _clear_screen() -> None:
    """Clear terminal screen and move cursor to home position."""
    # ANSI: clear screen + cursor home
    print("\033[2J\033[H", end="")


def _fmt_local(dt_iso_utc: str | None, tz: ZoneInfo) -> str:
    """Convert ISO UTC string (from snapshot_to_dict) to local display.

    :param dt_iso_utc: ISO UTC datetime string or None
    :param tz: target timezone
    :return: formatted local datetime string or "-"
    """
    if not dt_iso_utc:
        return "-"
    # dt_iso_utc example: "2026-01-03T12:34:56+00:00"
    dt: datetime = datetime.fromisoformat(dt_iso_utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def _render(  # noqa: PLR0913
    *,
    title: str,
    signals: list[str],
    snapshots: dict[str, dict[str, object]],
    prev: dict[str, dict[str, object]] | None,
    tz: ZoneInfo,
    last_refresh: str | None = None,
) -> None:
    """Render the CLI display.

    :param title: title string
    :param signals: list of signal names
    :param snapshots: current snapshots dict
    :param prev: previous snapshots dict or None
    :param tz: target timezone
    :param last_refresh: last signal refresh ISO UTC string or None
    """
    _clear_screen()
    print(title)
    print("=" * len(title))
    print()

    print("Signals:", ", ".join(signals) if signals else "(none)")
    print()

    # keys in desired order
    keys: list[str] = [
        "low_tariff",
        "actual_tariff",
        "actual_tariff_start",
        "actual_tariff_end",
        "next_low_tariff_start",
        "next_low_tariff_end",
        "next_high_tariff_start",
        "next_high_tariff_end",
        "next_switch",
        "remain_actual",
        "remain_actual_seconds",
    ]

    for sig in signals:
        s: dict[str, object] = snapshots[sig]
        p: dict[str, object] = prev.get(sig, {}) if prev else {}

        print(f"[{sig}]")
        for k in keys:
            v: object | None = s.get(k)
            changed: str = "*" if (k in p and p.get(k) != v) else " "
            out: str
            if k.endswith(("_start", "_end")) or k == "next_switch":
                # these are ISO UTC strings in the serialized dict
                out = _fmt_local(v if isinstance(v, str) else None, tz)
            else:
                out = str(v)

            print(f" {changed} {k:24s}: {out}")
        print()
    print(f"Last refresh: {_fmt_local(last_refresh, tz)}")
    print()


async def main() -> int:
    """Run the demo CLI.

    :return: exit code
    """
    parser = argparse.ArgumentParser(description="cez-distribution-hdo demo CLI")
    parser.add_argument("--ean", help="EAN identifier", default=None)
    parser.add_argument("--sn", help="Serial number identifier", default=None)
    parser.add_argument("--place", help="Place identifier", default=None)
    parser.add_argument(
        "--seconds", type=int, default=5, help="How long to refresh view (default: 5)"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="Refresh interval in seconds (default: 1.0)"
    )
    args: argparse.Namespace = parser.parse_args()

    ean: str | None = _clean_str(args.ean)
    sn: str | None = _clean_str(args.sn)
    place: str | None = _clean_str(args.place)

    if not any([ean, sn, place]):
        print("ERROR: provide at least one of --ean / --sn / --place")
        return 2

    tz = ZoneInfo("Europe/Prague")

    service = TariffService(tz_name=tz.key)
    await service.refresh(ean=ean, sn=sn, place=place)

    signals: list[str] = service.signals
    if not signals:
        print("No signals returned by API.")
        return 1

    prev: dict[str, dict[str, object]] | None = None

    # initial + N refreshes
    steps: int = max(int(args.seconds / args.interval), 1)
    for i in range(steps + 1):
        now: datetime = datetime.now(tz)
        snapshots: dict[str, dict[str, object]] = {}

        for sig in signals:
            snap: TariffSnapshot = service.snapshot(sig, now=now)
            # snapshot_to_dict returns a stable, display-friendly dict
            # (ISO UTC timestamps, HH:MM:SS remain, etc.)
            snapshots[sig] = snapshot_to_dict(snap)

        title: str = (
            "cez-distribution-hdo demo  |  "
            f"local time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}  |  step {i}/{steps}"
        )
        last_signal_refresh: str | None = service.last_refresh_iso_utc
        _render(
            title=title,
            signals=signals,
            snapshots=snapshots,
            prev=prev,
            tz=tz,
            last_refresh=last_signal_refresh,
        )

        prev = snapshots
        if i < steps:
            await asyncio.sleep(args.interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
