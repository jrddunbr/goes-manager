# Filesystem Monitor

## Purpose
Continuously observe the `satellite_raw/` hierarchy for new or updated files, parse filename metadata, and emit lightweight manifests that downstream services can read without maintaining a separate database.

## Responsibilities
- Watch filesystem events (creation, modification, deletion) across all product families (`EMWIN`, `IMAGES`, `L2`, `Admin Messages`).
- Parse filenames into structured metadata (satellite, domain, timestamp, AWIPS ID, etc.).
- Write manifests (e.g., newline-delimited JSON files under `state/manifests/`) summarising new arrivals.
- Maintain rolling “latest” pointers (e.g., `state/latest/goes19_full_disk.json`) so other daemons can quickly discover current products.
- Provide simple CLI utilities for backfilling manifests from historical listings (`files.txt`).

## Inputs
- Filesystem watcher events via Python `watchdog`/`watchfiles`.
- Historical snapshots (e.g., `files.txt`, `goes_file_sizes.txt`) for bootstrap.

## Outputs
- Manifest files describing products (path, size, timestamp, product code).
- Optional event logs (plain text/JSON) for auditing and troubleshooting.

## Implementation Notes
- Keep manifests small and append-only; rotate by day/hour to avoid unbounded growth.
- Store manifests in a predictable location (`satellite_raw/_state/` or project `state/` folder) to keep them accessible to all daemons.
- Avoid heavy dependencies—filesystem remains the source of truth.
- Expose health info via a simple status file (e.g., write heartbeat timestamps to `_state/monitor.status`).
