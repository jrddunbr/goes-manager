# Retention Manager

## Purpose
Enforce storage policies across the GOES dataset by promoting/demoting files between retention classes, deleting expired artifacts, and compressing or relocating data according to the schedule defined in `docs/retention.md`.

## Responsibilities
- Inspect filesystem metadata or monitor manifests to identify file ages and product types.
- Apply policy rules (Hot 7d, Warm 30d, Seasonal 90d, Archive 400d, Indefinite) to determine actions.
- Execute filesystem operations: delete, compress, move to archival directories, or trigger object-storage uploads if introduced later.
- Maintain audit logs of actions (who/what/when) for traceability.
- Expose status metrics (e.g., bytes freed, files pending review).

## Inputs
- Filesystem metadata (mtime/ctime, sizes) and monitor-produced manifests.
- Policy configuration (YAML/JSON) describing class thresholds and per-product handling.

## Outputs
- Updated filesystem state (files removed, moved, or compressed according to policy).
- Logs/metrics (plain text or JSON) for operator review.
- Optional daily reports summarising retention actions.

## Implementation Notes
- Implement dry-run and approval modes for testing.
- Ensure atomic operations where possible to prevent partial moves.
- Validate file integrity (checksum/size) after moves when practical.
- Keep “indefinite” assets (admin messages, monitor state) read-only to avoid accidental purges.
