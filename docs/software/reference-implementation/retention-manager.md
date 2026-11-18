# Retention Manager

The retention manager lives in the `goes_retention` Python package (`src/goes_retention/engine.py`) and ships as its own executable module. It enforces the tiered hot/warm/seasonal/archive policy described in `docs/retention.md` by scanning configured directories and applying age-based actions.

## Capabilities
- Walk configured directories and match files via glob include/exclude patterns.
- Execute staged actions (move, gzip, delete) once files cross age thresholds.
- Maintain a dry-run mode so policies can be rehearsed safely.
- Produce detailed logs and optional CLI summaries for auditing.

## CLI Usage
The dedicated CLI entry point is:

```bash
PYTHONPATH=src python -m goes_retention --common-config /path/to/common.json --config /path/to/retention.json
```

Key options:
- `--dry-run` forces simulation regardless of config.
- `--execute` overrides a dry-run config and performs real changes.
- `--summarize` prints a plain-text summary of the actions taken.
- `--interval N` keeps the process running, re-evaluating policy every `N` seconds (defaults to the config interval when `N` is omitted or zero). For production deployments we typically omit `--interval` and rely on a systemd timer to launch the tool once per day.

See `PYTHONPATH=src python -m goes_retention --help` for the full flag list.

## Configuration
Retention configuration lives in its own JSON file layered on top of the common settings. Examples live under `config/retention.sample.json` (retention-specific) and `config/common.sample.json` (shared parameters). The shared sample pins `data_root` to `/var/satellite/satellite_raw`, which is both the ingest root and the nginx document root, ensuring archived artifacts remain web-accessible. The retention file structure:

```jsonc
{
  "retention": {
    "enabled": true,
    "interval_seconds": 3600,
    "rules": [
      {
        "name": "Mesoscale imagery retention",
        "directories": ["IMAGES"],
        "include": ["**/*.png"],
        "exclude": ["**/_thumbnails/**"],
        "actions": [
          { "after": "7d", "type": "move", "target": "ARCHIVE/WARM/IMAGES" },
          { "after": "90d", "type": "compress", "target": "ARCHIVE/SEASONAL/IMAGES", "compression": "zstd" },
          { "after": "400d", "type": "delete" }
        ]
      }
    ]
  }
}
```

Important notes:
- `directories` are resolved relative to `data_root` (declared in `common.json`) unless given as absolute paths.
- Archive targets (`ARCHIVE/...`) also live beneath `data_root`, making them automatically available under `/var/satellite/satellite_raw/` for HTTP serving.
- Glob patterns follow `fnmatch` semantics (`**` for recursive matching).
- `after` accepts compact durations (`7d`, `30d12h`, etc.). Actions are evaluated in ascending age order.
- Supported action types today: `move`/`archive`, `compress`, `delete`/`remove`.
- `target` directories are created automatically when actions run (skipped during dry-run).
- `compress` supports gzip (`gz`) and Zstandard (`zstd`/`zst`). Zstandard handling requires the `zstandard` Python package to be installed on the host. Source files are removed after compression unless `keep_original` is set.

## Scheduling & systemd Deployment
The recommended approach is to run retention once per day via a systemd timer. The service `systemd/goes-retention.service` executes a single retention pass (`python -m goes_retention --common-config … --config … --execute`); pair it with `systemd/goes-retention.timer` to trigger the run on a daily cadence.

Update the `User`, `Group`, `WorkingDirectory`, and `ExecStart` fields in the service file to match your deployment, then install both units:

```bash
sudo cp systemd/goes-retention.service /etc/systemd/system/
sudo cp systemd/goes-retention.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now goes-retention.timer
```

The service sets `PYTHONPATH` to the repository `src/` directory and reads configuration from the split config files. Adjust the timer schedule (`OnCalendar=`) if you prefer a different cadence.

## Logs & Reporting
- The CLI runs under standard Python logging. Adjust `logging.level` in the config or the `--log-level` flag.
- Each retention action is logged with the rule name, path, and outcome. Dry-run executions are clearly labeled.
- Use `--summarize` to capture a concise summary for change control reviews or testing documentation.

## Implementation Reference
- Core rule evaluation: `src/goes_retention/engine.py`
- CLI orchestration: `src/goes_retention/cli.py`
- Shared helpers (configuration + utilities): `src/goes_manager/config.py`, `src/goes_manager/util.py`

Future enhancements (checksum verification, richer thinning strategies, per-rule concurrency) can be added by extending `RetentionManager` while keeping the existing CLI contract intact.
