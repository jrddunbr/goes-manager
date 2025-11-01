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
- Filesystem statistics (`df`, `du`, or Python `os.statvfs`).

## Outputs
- Discord webhook payloads for critical warnings/errors.
- Local status file (e.g., `_state/health.json`) summarising current health indicators.
- Optional stdout/stderr logs for historical review.

## Implementation Notes
- Run as a lightweight daemon (Python script or systemd service) with minimal dependencies.
- Include rate limiting to avoid flooding Discord on recurring issues.
- Provide a CLI command for operators to trigger test alerts.
- No authentication layer is required; access is controlled at the OS/SSH level.
