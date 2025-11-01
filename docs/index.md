# GOES Data Catalog

Counts and timelines in this document come from the `files.txt` snapshot (63,333 paths captured via SatDump). Size figures derive from the investigative `goes_file_sizes.txt` dump. Refresh both reports after each new ingest—their contents are point-in-time observations rather than live manifests.

## Inventory Snapshot
| Top-level area | File count | Primary formats | Notes |
| --- | ---: | --- | --- |
| `EMWIN/` | 35,035 | `txt`, `gif`, `jpg`, `png` | Emergency Managers Weather Information Network bulletins. |
| `IMAGES/GOES-*` | 23,698 | `png`, `cbor` | GOES ABI full-disk & mesoscale imagery (GOES-19 is current production, GOES-16/18 legacy). |
| `IMAGES/NWS` | 930 | `gif` | Human-generated forecast facsimiles from LRIT. |
| `L2/` | 3,662 | `png`, `cbor` | GOES Level-2 derived fields (CAPE, TPW, cloud props, SST/LST). |
| `Admin Messages/` | 2 | `txt` | GOES-East operational notices. |

## Drill-down Documents
- [EMWIN bulletins](emwin.md)
- [GOES ABI imagery](goes-imagery.md)
- [NWS forecast charts](nws-charts.md)
- [Level-2 geophysical products](l2.md)
- [Administrative notices](admin-messages.md)
- [Retention strategy](retention.md)

## File System Pattern
SatDump organizes downlinks as:
- Root folders per product family (`EMWIN`, `IMAGES`, `L2`, `Admin Messages`).
- Satellite branches under imagery/Level-2 roots (`GOES-19`, legacy `GOES-16/18`).
- Domains (`Full Disk`, `Mesoscale 1/2`) preceding timestamp folders (`YYYY-MM-DD_HH-MM-SS`).
- Timestamp folders combining raw bands (`G19_13_...png`), RGB composites (`abi_rgb_*`), and `product.cbor` metadata.
- EMWIN files delivered individually with WMO/AWIPS identifiers encoded in the basename.

## Temporal Coverage Snapshot
| Category | First acquisition | Last acquisition | Notes |
| --- | --- | --- | --- |
| EMWIN text/graphics | 2025-05-28 02:32 UTC | 2025-11-01 02:28 UTC | Dense stream of CONUS, marine, and territorial bulletins. |
| GOES-16 imagery & L2 | 2025-02-21 13:30 UTC | 2025-03-09 20:07 UTC | Historical; useful for baseline comparisons. |
| GOES-18 imagery | 2025-02-21 13:50 UTC | 2025-11-01 01:50 UTC | Intermittent full-disk captures. |
| GOES-19 imagery & L2 | 2025-04-07 21:00 UTC | 2025-11-01 02:22 UTC | Current operational feed replacing GOES-16. |
| NWS LRIT charts | 2025-02-22 00:00 UTC | 2025-11-01 02:20 UTC | Human-curated forecast maps (surface analyses, tropical outlooks, high-wind). |
| Admin messages | 2023-01-04 | 2025-04-07 | Retain indefinitely for operational context. |

The gap between the November 2025 snapshot and present day should be factored into backfill or data re-acquisition plans.

## Operations Roadmap
- Maintain a structured catalog (database or Parquet) ingesting new `files.txt` exports to keep counts accurate.
- Refer to `retention.md` when assigning datasets to the 7-day/30-day/90-day/400-day/indefinite storage tiers (and any supplemental tiers).
- Use the drill-down docs to inform automation for the planned per-minute dashboard (e.g., GOES-19 mesoscale imagery + Level-2 tooltips + NWS charts in separate menu groups).
- Prototype a filesystem watcher (e.g., Python `watchdog`) that updates the catalog in real time so retention jobs and dashboard feeds react as new products arrive.
