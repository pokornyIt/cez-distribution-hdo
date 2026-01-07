# cez-distribution-hdo

[![Checks](https://github.com/pokornyIt/cez-distribution-hdo/actions/workflows/ci.yml/badge.svg)](https://github.com/pokornyIt/cez-distribution-hdo/actions/workflows/ci.yml)
[![Coverage Status](https://coveralls.io/repos/github/pokornyIt/cez-distribution-hdo/badge.svg)](https://coveralls.io/github/pokornyIt/cez-distribution-hdo)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Python library for reading and interpreting HDO (low/high tariff) switch times from the CEZ Distribution “switch-times / signals” API.

> This repository contains the **core library** only.
> A Home Assistant integration is planned as a separate project.

## Features

- Async HTTP client (`httpx`) for the CEZ Distribution API (POST JSON)
- Parsing of `signals[]` including multiple `signal` sets (e.g. boiler vs heating)
- Robust handling of `24:00` and **cross-midnight** low-tariff windows
- Per-signal schedule utilities:
  - current tariff (NT/VT)
  - current window start/end
  - next switch time
  - next NT/VT window (future-only)
  - remaining time until next switch
- High-level service (`TariffService`) that:
  - refreshes data occasionally (API call)
  - computes “snapshots” frequently without extra network calls (ideal for HA)

See [`examples/`](examples/) for runnable demos (e.g., `demo_cli.py`).

## Requirements

- Python `>= 3.13`
- Runtime dependency: `httpx`

Development tools (optional): `uv`, `ruff`, `pyright`, `pytest`, `pytest-asyncio`.

## Version

The package version is derived from git tags via `uv-dynamic-versioning`.

```python
from cez_distribution_hdo import __version__

print(__version__)
```

## Install

### From PyPI (recommended)

```bash
pip install cez-distribution-hdo
```

Using `uv`:

```bash
uv add cez-distribution-hdo
```

### From TestPyPI (pre-releases)

> TestPyPI is useful for verifying releases before publishing to PyPI.
> Pre-releases may require `--pre`.

With pip:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple cez-distribution-hdo
```

With `uv` (using the `testpypi` index from `pyproject.toml`):

```bash
uv add --index testpypi cez-distribution-hdo
```

### From Git (development)

Using `uv`:

```bash
uv add "cez-distribution-hdo @ git+https://github.com/pokornyIt/cez-distribution-hdo.git"
```

Or with pip:

```bash
pip install "cez-distribution-hdo @ git+https://github.com/pokornyIt/cez-distribution-hdo.git"
```

## Logging

This library uses Python's standard `logging` module and does not configure logging by itself.
To see debug logs from the library, configure logging in your application:

```python
import logging

logging.basicConfig(level=logging.INFO)

# Increase verbosity for this library
logging.getLogger("cez_distribution_hdo").setLevel(logging.DEBUG)
```

If you also want to see HTTPX request logs:

```python
import logging

logging.getLogger("httpx").setLevel(logging.INFO)
```

## Quickstart

### 1) Fetch schedules (API call)

```python
import asyncio

from cez_distribution_hdo import CezHdoClient


async def main() -> None:
    async with CezHdoClient() as client:
        # Provide exactly one identifier: ean OR sn OR place
        resp = await client.fetch_signals(ean="859182400123456789")
        print(f"Signals returned: {len(resp.data.signals)}")
        for s in resp.data.signals[:3]:
            print(s.signal, s.date_str, s.times_raw)


if __name__ == "__main__":
    asyncio.run(main())
```

### 2) High-level service (recommended)

Refresh schedules occasionally (e.g. hourly) and compute values frequently (e.g. every 1–5 seconds) without extra API calls.

```python
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from cez_distribution_hdo import TariffService, snapshot_to_dict


async def main() -> None:
    tz = ZoneInfo("Europe/Prague")
    svc = TariffService(tz_name="Europe/Prague")

    # One API call (do this occasionally)
    # Provide exactly one identifier: ean OR sn OR place
    await svc.refresh(ean="859182400123456789")

    print("Available signals:", svc.signals)

    # Compute values (no network) - do this often
    now = datetime.now(tz)
    for signal in svc.signals:
        snap = svc.snapshot(signal, now=now)
        print(snapshot_to_dict(snap))


if __name__ == "__main__":
    asyncio.run(main())
```

## Identifiers (EAN / SN / place)

The CEZ Distribution API accepts **exactly one** identifier per request.

Provide one of:

- `ean` — EAN of the electricity meter
- `sn` — serial number of the electricity meter
- `place` — place number of the electricity meter

If you pass **none** or **more than one**, the library raises `InvalidRequestError`.

## Data model

The API returns a list of signal entries:

* `signal` – identifies a “signal set” (multiple sets may be returned)
* `datum` – date (DD.MM.YYYY)
* `casy` – semicolon-separated time ranges where **low tariff (NT)** is active
  (everything outside those windows is **high tariff (VT)**)

Example:

```json
{
  "signal": "PTV2",
  "datum": "03.01.2026",
  "casy": "00:00-06:00; 17:00-24:00"
}
```

### Cross-midnight handling

`24:00` is treated as `00:00` of the next day.

If a low-tariff window ends at `24:00` and the next day starts with `00:00-06:00`,
the library merges these into one continuous interval:

* `03.01 17:00 → 04.01 06:00`

This makes “current window”, “next switch”, and “remaining time” behave correctly.

## Error handling

The client raises:

* `InvalidRequestError` – invalid request (must provide **exactly one** identifier: `ean`/`sn`/`place`)
* `HttpRequestError` – network/timeout/non-2xx HTTP errors
* `InvalidResponseError` – unexpected JSON schema or invalid time/date formats
* `ApiError` – API returned non-200 `statusCode` in JSON payload

## Development

### Setup

```bash
uv venv
uv sync
```

### Lint / typecheck / tests

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

### Pre-commit

```bash
uv add --group dev pre-commit
uv run pre-commit install
uv run pre-commit run --all-files
```

### Build

```bash
uv build
```

## License

This project is licensed under the MIT License.
See [LICENSE](LICENSE) for details.
