# Examples

This folder contains small runnable demos for **cez-distribution-hdo**.

## demo_cli.py

A minimal CLI that demonstrates how to use the library:

1. Fetches schedules from the CEZ Distribution API using one of:
   - `--ean`
   - `--sn`
   - `--place`

2. Prints all available computed values for each returned `signal`.

3. Refreshes the view every 1 second for 5 seconds (by default) **without additional API calls**
   to make it obvious which values change over time (e.g., `remain_actual*`, `next_switch`, etc.).

### Run

From the repository root:

```bash
# Using EAN
uv run python examples/demo_cli.py --ean "859182400123456789"

# Using SN
uv run python examples/demo_cli.py --sn "<serial-number>"

# Using place
uv run python examples/demo_cli.py --place "<place-number>"
```

### Options

```bash
# Show the dashboard for 10 seconds, refresh every 1 second
uv run python examples/demo_cli.py --ean "..." --seconds 10 --interval 1

# Faster refresh (e.g., 0.5s)
uv run python examples/demo_cli.py --ean "..." --seconds 5 --interval 0.5
```

### Notes

* The script calls the API only once (`service.refresh(...)`). The periodic output is computed locally.
* Timestamps are shown in local time (**Europe/Prague**) while the underlying serialized values are stored in UTC ISO format.
* If you see no signals, verify the identifier value (`ean`/`sn`/`place`) is correct.
