# Health & Alert Monitor

## Purpose
Collect operational signals from local services (including SatDump) and dispatch alerts to operators via Discord webhooks when issues arise.

## Responsibilities
- Tail `satdump.service` logs via `journalctl` to detect reception problems, decoder errors, or prolonged gaps.
- Monitor manifest heartbeat files (from the filesystem monitor) to ensure daemons remain active.
- Watch filesystem capacity and emit warnings when usage nears thresholds.
- Aggregate basic health metrics (last successful ingest, retention job status) and expose them via a status file or simple HTTP endpoint (internal only).
- Deliver alert messages to configured Discord webhooks with actionable summaries.

## Inputs
- systemd journal (`journalctl -u satdump.service`).
- Monitor manifests/status files (e.g., `_state/monitor.status`, retention audit logs).
- Filesystem statistics.
- local satdump HTTP API (e.g., `http://localhost:8000/api`).

## Outputs
- Discord webhook payloads for critical warnings/errors.
- Local status file (e.g., `_state/health.json`) summarising current health indicators.
- API endpoint for external monitoring
- Optional stdout/stderr logs for historical review.

## Implementation Notes
- Run as a lightweight daemon (Python script or systemd service) with minimal dependencies.
- Include rate limiting to avoid flooding Discord on recurring issues.
- Provide a CLI command for operators to trigger test alerts.
- No authentication layer is required; access is controlled at the OS/SSH level.

## Current Implementation

- Packaged as `python -m goes_health_monitor` with CLI options mirroring the other GOES daemons.
- Reads SatDump logs through the python-systemd journald APIs; review `config/health_monitor.sample.json` for available tuning fields.
- Persists a JSON snapshot (default `state/health.json`) capturing recent SatDump messages, detected warnings/errors, and API reachability.
- Optionally polls the SatDump HTTP API (default `http://localhost:8000/api`) and records results under the `satdump_api` key. Note: This is currently broken.
- Supports Discord webhook alerts with cooldown control; alerts emit when severity crosses the configured `min_severity` threshold or after the cooldown expires while degraded.

### Running the service

```bash
python -m goes_health_monitor \
  --common-config config/common.json \
  --config config/health_monitor.json
```

Use `--once` for ad-hoc checks or `--interval` (seconds) to override the loop cadence defined in configuration.

## Future Work

I want to make this tool more useful for helping figure out if there are antenna feed issues. I'd also like to parse the Satdump logs and provide more useful insights into what/why failures occur.

It would be neat to integrate this with rotctl so that you can get optimal antenna alignment automatically. The Discovery Dish is going to have a rotator available at some point in the future, and having the ability to align with the satellite with backing SNR data for precise localized alignment would be awesome.