# Software Components Overview

This section outlines the planned services required to ingest GOES data, manage retention, generate derivative media, and drive the public dashboards. Each component will eventually live under `src/` or associated infrastructure tooling.

## Core Daemons

| Service | Role | Key Interfaces | Notes |
| --- | --- | --- | --- |
| [Filesystem Monitor](filesystem-monitor.md) | Watches `satellite_raw/` for new files and writes lightweight manifests for other daemons. | Filesystem watchers (inotify/watchdog), manifest files on disk. | Provides a single place to translate filenames into structured metadata. |
| [Retention Manager](retention-manager.md) | Applies retention policies (7d/30d/90d/400d/indefinite) directly against the filesystem. | Manifest files, filesystem operations, logging/metrics. | Executes deletions, moves, or compressions based on policy. |
| [Dashboard Feeder](dashboard-feeder.md) | Serves the per-minute dashboard with latest imagery, bulletins, and metadata. | Manifest files, direct filesystem access, websocket/HTTP endpoints. | Publishes updates to the web frontend and ensures data availability. |
| [Timelapse Generator](timelapse-generator.md) | Creates rolling animations from imagery sequences and stores them for web delivery. | Manifest files, encoder (ffmpeg), storage output directories. | Manages job queue for multiple products/bands. |
| [Derivative Publisher](derivative-publisher.md) | Handles other derivative products (e.g., quicklook composites, statistical summaries) and posts them under `satellite_raw/derivatives/`. | Manifest files, transformation pipelines. | Optional; scope depends on future product roadmap. |
| [Health & Alert Monitor](health-alert-monitor.md) | Aggregates service health, watches SatDump logs, and dispatches Discord alerts for signal or filesystem issues. | systemd journal (`satdump.service`), manifests/status files, Discord webhook. | Combines health reporting and operator notification. |

Additional supporting modules (e.g., simple CLI tooling or schedulers) can be added later as needs emerge. Remote access remains via SSH; no web-based admin login is planned.
