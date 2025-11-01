# Retention Strategy

Storage planning assumes the working dataset resides on a 1 TB SSD and that `files.txt` represents a single SatDump snapshot (actual byte sizes should be confirmed with a fresh crawl). Retention classes below balance rapid dashboard access with long-term reference needs.

### Current Footprint (from `goes_file_sizes.txt`)
| Area | Approx size |
| --- | ---: |
| `satellite_raw/IMAGES` | 72.84 GiB (legacy GOES-16 Full Disk ≈47 GiB, GOES-19 Full Disk ≈19.6 GiB) |
| `satellite_raw/L2` | 6.61 GiB |
| `satellite_raw/EMWIN` | 0.50 GiB |
| `satellite_raw/Admin Messages` | <1 MiB |
| `satellite_raw/.composite_cache_do_not_delete.json` | <1 MiB |

## Retention Classes
| Class | Target span | Typical media | Purpose | Actions at rollover |
| --- | --- | --- | --- | --- |
| **Hot (7 days)** | Latest week | GOES-19 mesoscale bands (2/7/8/9/13/14/15), RGB `_map` composites, Level-2 CAPE/TPW/RRQPE, decoded EMWIN warnings (`WWA`, `TAF`) | Power the per-minute dashboard and operational alerting. | Promote essential frames to Warm; purge or archive redundant quicklooks; verify dashboard pointers. |
| **Warm (30 days)** | Past month | GOES-19 full-disk sets, Level-2 ACHT/ACHA, EMWIN hydrologic + marine bulletins, NWS charts for current season | Support incident review, QA, and short-term climatology. | Downsample imagery (retain every Nth scan), compress text bundles, move select items to Seasonal. |
| **Seasonal (90 days)** | Rolling quarter | Representative GOES-19 mesoscale sequences (hourly), GOES-18 full-disk samplers, decoded EMWIN climate/river data | Preserve context for quarterly reporting and algorithm tuning. | Filter to one scan per hour (imagery) and per product per day (text). Promote anomalies to Archive. |
| **Archive (400 days)** | ≈13 months | Key events, full-disk mosaics at 6‑hour cadence, Level-2 extremes, monthly EMWIN summaries | Maintain year-over-year comparables. | Export to compressed packages (e.g., Zarr/NetCDF tarballs, bz2 text) on external or slower storage. |
| **Indefinite** | No expiration | Admin messages, catalog metadata (`product.cbor` extracts), parsed EMWIN databases, curated event packages | Institutional knowledge, reproducibility. | Periodically verify checksums; optionally mirror to cloud/off-site backup. |
| *(Optional)* **Staging (24 hours)** | Current day | Raw SatDump transport chunks prior to conversion | Buffer for ingest/processing. | Empty daily after successful ingest. |

## Dataset-to-Class Mapping
- **GOES-19 imagery (production)**
  - Raw mesoscale quicklooks: Hot ➜ Warm (retain 1-min cadence for 7 days, thin to 5-min cadence for 30 days, hourlies for Seasonal).
  - Full-disk imagery: Warm ➜ Archive (keep every slot for 30 days; reduce to 6‑hour cadence beyond 90 days).
  - `product.cbor` metadata: copy to Indefinite store (parsed form) while keeping raw CBOR alongside retained imagery tiers.
- **GOES-16/18 legacy**
  - Place immediately into Seasonal with further thinning; move representative scenes to Archive/Indefinite for historical baselines.
- **Level-2 products**
  - Core severe-weather set (`ACHT`, `ACHA`, `DSI`, `TPW`, `RRQPE`): mirror the imagery retention but consider storing derived grids (NetCDF) in Archive for re-analysis.
  - Optional (`SST`, `LST`): Warm ➜ Seasonal only when needed for specific studies.
- **EMWIN bulletins**
  - Warnings/advisories (`WW`, `CFW`, `TAF`, `SPS`): Hot ➜ Warm ➜ Archive. Retain parsed/decoded records indefinitely; raw text can be compressed after 30 days.
  - Routine obs (`SAH`, `RWR`, `OBS`): Warm ➜ compress to daily bundles in Seasonal; ingest into a database kept Indefinitely.
  - Marine/climate (`MIS`, `CLI`, `PFM`): Warm ➜ Archive; keep statistical summaries indefinitely.
  - Graphics (`Z_*.gif`/`.jpg`): Warm ➜ Seasonal (retain most recent cycle and significant events).
- **NWS LRIT charts**
  - Keep in a dedicated pool (Warm). Maintain rolling 30 days online for dashboard use; sample weekly charts for Seasonal; push major events (e.g., hurricanes) to Archive/Indefinite paired with EMWIN discussions.
- **Administrative messages & structural metadata**
  - Store raw files and parsed notes in Indefinite tier; size impact is negligible.

## Implementation Notes
- **Catalog-driven purging**: Build a retention job that reads the ingest catalog, marks items by age + product type, and performs thinning/compression based on the schedule above.
- **Compression**: Use lossless PNG to Zarr/NetCDF for imagery if recalculating derivatives is cheaper than storing quicklooks. Text bulletins compress well with `xz`/`zstd` when bundling by day or product.
- **Integrity**: Before moving to Archive/Indefinite, record checksums and metadata (timestamp, WMO/AWIPS IDs, band availability) to simplify retrieval.
- **Dashboard feed**: Pin the dashboard to Hot-tier assets. Ensure background jobs downgrade items only after confirming the dashboard has advanced beyond them.
- **Growth monitoring**: Track SSD utilisation; if Hot + Warm tiers exceed 70 % capacity, increase thinning cadence (e.g., keep only 15 min mesoscale cadence in Warm) or expand storage.

Adjust the class thresholds as real ingest sizes become available; the table serves as a baseline for scripting retention policies.
