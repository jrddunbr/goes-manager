# Filesystem Monitor

The filesystem monitor ships as its own executable module backed by `src/goes_filesystem_monitor/monitor.py`. It replaces ad-hoc scripts by watching the ingest directories, emitting manifest files, and keeping lightweight state so downstream services can react without a database.

## Responsibilities
- Walk configured roots (`satellite_raw/` subdivisions) and detect new or updated files based on modification time.
- Emit newline-delimited JSON manifests summarizing arrivals (path, size, mtime, `seen_at`).
- Persist per-file state in `state/monitor_state.json` to avoid duplicate manifest entries across runs.
- Expose a CLI for single-shot scans or continuous polling.

## CLI Usage
Run a single scan:

```bash
PYTHONPATH=src python -m goes_filesystem_monitor --common-config /path/to/common.json --config /path/to/filesystem_monitor.json --once
```

Run continuously (default interval comes from the config):

```bash
PYTHONPATH=src python -m goes_filesystem_monitor --common-config /path/to/common.json --config /path/to/filesystem_monitor.json
```

## Configuration
Monitor settings live in a dedicated JSON file layered on `config/common.json` (see `config/common.sample.json` and `config/filesystem_monitor.sample.json` for a complete reference). Example excerpt:

```jsonc
{
  "monitor": {
    "enabled": true,
    "interval_seconds": 30,
    "manifests_dir": "manifests",
    "roots": [
      {
        "path": "IMAGES",
        "manifest": "imagery.ndjson",
        "include": ["**/*.png", "**/*.jpg"],
        "exclude": ["**/_thumbnails/**"]
      },
      {
        "path": "EMWIN",
        "manifest": "emwin.ndjson",
        "include": ["**/*.txt"],
        "exclude": ["**/_state/**"]
      }
    ]
  }
}
```

Key behaviors:
- `path` values are resolved relative to the top-level `data_root` unless absolute.
- `manifest` is stored under `state_dir/manifests/` by default; override with a path relative to that directory or an absolute path.
- Include/exclude patterns use shell-style globs. Use `**` to match recursively.
- The monitor records state keyed by path relative to `data_root` (or absolute fallback). Modifications bump the stored `mtime`, generating a new manifest entry.

## Manifest Format
Each manifest line is canonical JSON with sorted keys:

```json
{
  "mtime": "2024-04-11T01:23:45.000000+00:00",
  "path": "IMAGES/meso1/20240411_012345.png",
  "root": "/var/satellite/satellite_raw/IMAGES",
  "seen_at": "2024-04-11T01:23:47.123456+00:00",
  "size": 1234567
}
```

Downstream daemons can tail these files or ingest them batch-style to track latest products.

## systemd Deployment
Use `systemd/goes-filesystem-monitor.service` to run the monitor continuously. Adjust the identity, working directory, and paths, then install it with:

```bash
sudo cp systemd/goes-filesystem-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now goes-filesystem-monitor.service
```

## Implementation Reference
- Polling/state management: `src/goes_filesystem_monitor/monitor.py`
- CLI wrapper: `src/goes_filesystem_monitor/cli.py`
- Shared helpers: `src/goes_manager/config.py`, `src/goes_manager/util.py`

Future work can add inotify/watchfiles support for lower latency, manifest rotation policies, or richer metadata extraction from filenames. The current polling implementation keeps dependencies minimal while providing deterministic manifests for the rest of the toolchain.
