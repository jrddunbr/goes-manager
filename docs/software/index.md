# Software Components Overview

This section outlines the planned services required to ingest GOES data, manage retention, generate derivative media, and drive the public dashboards. Each component will eventually live under `src/` or associated infrastructure tooling.

## Core Daemons

| Service | Role | Key Interfaces | Notes |
| --- | --- | --- | --- |
| [Filesystem Monitor](filesystem-monitor.md) | Watches `satellite_raw/` for new files and writes lightweight manifests for other daemons. | Filesystem watchers (inotify/watchdog), manifest files on disk. | Packaged as `python -m goes_filesystem_monitor` with its own service unit. |
| [Retention Manager](retention-manager.md) | Applies retention policies (7d/30d/90d/400d/indefinite) directly against the filesystem. | Manifest files, filesystem operations, logging/metrics. | Packaged as `python -m goes_retention` with an independent service unit. |
| [Dashboard Feeder](dashboard-feeder.md) | Serves the per-minute dashboard with latest imagery, bulletins, and metadata. | Manifest files, direct filesystem access, websocket/HTTP endpoints. | Publishes updates to the web frontend and ensures data availability. |
| [Timelapse Generator](timelapse-generator.md) | Creates rolling animations from imagery sequences and stores them for web delivery. | Manifest files, encoder (ffmpeg), storage output directories. | Manages job queue for multiple products/bands. |
| [Health & Alert Monitor](health-alert-monitor.md) | Aggregates service health, watches SatDump logs, and dispatches Discord alerts for signal or filesystem issues. | systemd journal (`satdump.service`), manifests/status files, Discord webhook. | Combines health reporting and operator notification. |

Additional supporting modules (e.g., simple CLI tooling, data analysis tools, etc.) can be added later as needs emerge. Remote access remains via SSH; no web-based admin login is planned.
