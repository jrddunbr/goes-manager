# Storage Utilisation & Accrual Snapshot

`current_usage.tsv` (Nov 14 snapshot, 47 MiB) and `current_usage2.tsv` (Nov 27 snapshot, 63 MiB) provided per-file sizes for everything under `/var/satellite/satellite_raw` but excluded `/ARCHIVE`. The new crawl `current_usage3.tsv` (Nov 27, 87 MiB) uses the updated `find` command and now includes `/ARCHIVE/WARM`. Pair it with the latest `df -h` (`/dev/sda1` 1 TB disk mounted at `/var/satellite`) which reports **440 GiB used / 429 GiB free / 916 GiB total** as of the same day.

## Data Capture Command

Re-run this crawl at least daily. For the next TSV capture we must include `/ARCHIVE` so that WARM/SEASONAL payloads are tracked alongside the hot tier:

```bash
sudo find /var/satellite/satellite_raw -type f -printf '%s\t%TY-%Tm-%Td\t%TH:%TM:%TS\t%p\n' | sort -k2,2 -k3,3 > /var/satellite/current_usage.tsv
```

## Data-Type Run Rates (excl. `/ARCHIVE`)

| Data type | Date span (UTC) | Days captured | Total (GiB) | Avg GB/day | Peak GB/day | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| **GOES-19 Full Disk imagery** | 2025-10-31 → 2025-11-14 | 14 | 114.39 | 8.17 | 12.06 | Dominant consumer; every 30 min scan produces ~7–12 GB of PNGs/RGB composites. |
| **GOES-19 Mesoscale imagery** | 2025-10-31 → 2025-11-14 | 15 | 8.54 | 0.57 | 0.99 | Both Mesoscale sectors combined; cadence appears near-continuous during the sample. |
| **GOES-19 Level-2 grids** | 2025-04-07 → 2025-11-14 | 24 | 13.64 | 0.57 | 1.26 | Includes ACHT/ACHA/ACHT RGBs plus NetCDF-style PNG derivatives. |
| **GOES-18 Full Disk imagery** | 2025-10-31 → 2025-11-14 | 14 | 2.41 | 0.17 | 0.25 | Likely a subset for west-coast situational awareness. |
| **GOES-16 Level-2 grids** | 2025-02-21 → 2025-03-07 | 14 | 4.62 | 0.33 | 0.88 | Legacy ingest captured for two weeks; not observed after March. |
| **EMWIN graphics (.gif/.jpg/.png)** | 2025-05-28 → 2025-11-14 | 21 | 3.14 | 0.15 | 0.32 | CONUS composites (`Z_EINA*`, `Z_EIUS*`) dominate; growth roughly 150 MB/day. |
| **EMWIN text (.TXT)** | 2025-05-27 → 2025-11-14 | 24 | 2.30 | 0.10 | 0.23 | River statements and TAFs drive the larger bursts. |
| **NWS LRIT charts** | 2025-02-21 → 2025-11-14 | 35 | 0.27 | 0.01 | 0.02 | Hourly LRIT “USA_latest” set; footprint is negligible. |

### EMWIN Graphics Detail
The EMWIN tree splits naturally into static text and raster products. Graphics remain the primary growth vector (~0.15 GB/day steady state) while text bulletins add ~0.10 GB/day. Both spans exclude `/ARCHIVE`.

| EMWIN tier | Date span (UTC) | Days | Total (GiB) | Avg GB/day | Peak GB/day |
| --- | --- | ---: | ---: | ---: | ---: |
| Graphics (`.gif/.jpg/.png`) | 2025-05-28 → 2025-11-14 | 21 | 3.14 | 0.15 | 0.32 |
| Text + miscellaneous | 2025-05-27 → 2025-11-14 | 24 | 2.30 | 0.10 | 0.23 |

Top EMWIN graphic products (identified by NOAA mnemonic at the tail of each filename) are below; 32 additional codes collectively contribute another **0.33 GiB** with <0.02 GB/day apiece.

| Product code | Example content | Date span | Days | Total (GiB) | Avg GB/day | Peak GB/day |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `G16CIRUS` | GOES-16 CONUS IR quicklooks | 2025-06-02 → 2025-11-14 | 18 | 0.60 | 0.03 | 0.06 |
| `G10CIRUS` | GOES West IR CONUS frames | 2025-05-31 → 2025-11-14 | 19 | 0.44 | 0.02 | 0.06 |
| `IMGWWAUS` | NWS watch/warning map (USA) | 2025-06-02 → 2025-11-14 | 18 | 0.33 | 0.02 | 0.03 |
| `G02HURUS` | Hurricane sector graphic | 2025-06-02 → 2025-11-14 | 18 | 0.31 | 0.02 | 0.03 |
| `G10FDIUS` | GOES West full-disk IR | 2025-05-31 → 2025-11-14 | 19 | 0.30 | 0.02 | 0.03 |
| `GPHJ88US` | Hemispheric precip/height panels | 2025-06-02 → 2025-11-14 | 17 | 0.16 | 0.01 | 0.02 |
| `IMGSJUPR` | San Juan PR regional graphic | 2025-05-31 → 2025-11-14 | 19 | 0.11 | 0.01 | 0.01 |
| `RADGRTLK` | Great Lakes radar mosaic | 2025-05-31 → 2025-11-14 | 19 | 0.10 | 0.01 | 0.01 |
| `RADNTHES` | Northern U.S. radar | 2025-05-31 → 2025-11-14 | 19 | 0.08 | 0.00 | 0.01 |
| `GMS008JA` | Himawari sector (Japan) | 2025-06-02 → 2025-11-14 | 18 | 0.08 | 0.00 | 0.01 |
| *Other 32 codes* | (e.g., `RADPACNW`, `RADREFUS`, `RADUMSVY`) | – | 12–19 | 0.33 | <0.02 | <0.01 |

### GOES-19 Sensor Mix
`current_usage.tsv` lets us split GOES-19 imagery by platform mode, ABI band, and derived RGB composite. Full Disk captures devote **≈22.8 GiB** to longwave IR channels (Bands 7/13/14/15) versus **3.4 GiB** for visible/near-IR Bands 1–6, while RGB composites add another **88 GiB**. Mesoscale sectors are lighter overall (~4.5 GiB per sector) but still dominated by Band 02 red-visible plus a False Color RGB pair that doubles storage by emitting both the projection and `_map` variant.

#### Full Disk ABI single-band frames
| Sensor (Full Disk) | Spectral class | Total (GiB) | Avg GB/day | Peak GB/day | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| Band 07 Shortwave IR (3.9 µm) | LW IR | 4.68 | 0.33 | 0.49 | Key for fire/hotspot detection; produced every slot. |
| Band 14 IR Longwave (11.2 µm) | LW IR | 4.44 | 0.32 | 0.47 | Classic longwave window for cloud-top temp. |
| Band 13 Clean LW IR (10.3 µm) | LW IR | 4.39 | 0.31 | 0.46 | Severe-weather “Clean IR” band. |
| Band 15 Dirty LW IR (12.3 µm) | LW IR | 4.30 | 0.31 | 0.46 | Complements Band 13 for split-window products. |
| Band 02 Red (0.64 µm visible) | VIS | 3.44 | 0.25 | 0.36 | Primary visible reference; only major non-IR consumer. |
| Band 09 Mid-level WV (6.9 µm) | IR (water vapor) | 2.69 | 0.19 | 0.28 | Used for jet-level dynamics. |
| Band 08 Upper-level WV (6.2 µm) | IR (water vapor) | 2.32 | 0.17 | 0.24 | Completes the three-layer WV suite. |

#### Full Disk RGB composites
| Composite pair (base + `_map`) | Total (GiB) | Avg GB/day | Peak GB/day | Comment |
| --- | ---: | ---: | ---: | --- |
| ABI False Color | 16.35 | 1.17 | 1.78 | Situational awareness quicklook; doubled by map reprojection. |
| Shortwave Window Band | 12.84 | 0.92 | 1.34 | Differentiates snow/ice vs. clouds. |
| Infrared Longwave Window Band | 11.93 | 0.85 | 1.25 | Alternate paletting of Band 14. |
| Clean Longwave IR Window Band | 11.80 | 0.84 | 1.24 | Derived from Band 13; used by aviation products. |
| Dirty Longwave Window | 11.58 | 0.83 | 1.22 | Complements split-window thermal analysis. |
| Dirty Longwave Window – CIRA palette | 10.13 | 0.72 | 1.07 | Extra CIRA-tuned look applied to the same slots. |
| Mid-level Tropospheric WV | 7.26 | 0.52 | 0.76 | Matches ABI Band 09 dynamics. |
| Upper-level Tropospheric WV | 6.22 | 0.44 | 0.65 | Complements ABI Band 08. |

#### Mesoscale sectors (Mesos 1 + Mesos 2 combined)
| Sensor/composite | Total (GiB) | Avg GB/day | Peak GB/day | Notes |
| --- | ---: | ---: | ---: | --- |
| Band 02 Red (0.64 µm VIS) | 1.42 | 0.09 | 0.17 | Primary fast-cadence imagery for both mesos slots. |
| Band 07 Shortwave IR (3.9 µm) | 0.17 | 0.01 | 0.02 | Nighttime fire/hot-spot monitoring. |
| Band 13 Clean LW IR (10.3 µm) | 0.16 | 0.01 | 0.02 | Deep-convection view. |
| RGB ABI False Color / `_map` | 5.86 | 0.39 | 0.69 | Majority of mesos storage; two PNGs per scan. |
| RGB Shortwave Window Band / `_map` | 0.48 | 0.03 | 0.05 | Snow/ice vs. cloud differentiation. |
| RGB Clean Longwave IR Window Band / `_map` | 0.43 | 0.03 | 0.05 | Thermal rendering of the same frames. |
| Other mesos RGBs | 0.00+ | <0.01 | <0.01 | Present but negligible in this capture. |

Combined GOES-19 production load (Full Disk imagery + Mesoscale imagery + Level-2 grids) has now stabilized near **14–15 GB/day**. The refreshed crawl `current_usage2.tsv` (captured 2025‑11‑27) inventories **≈347 GiB** of non-archive content spanning 53 ingest days (up from ≈149 GiB/40 days in the prior TSV). Daily production from 2025‑11‑05 onward rarely drops below 14 GB/day, with a recent peak of **14.96 GB/day**. With `/ARCHIVE` now included (`current_usage3.tsv`), the enumerated footprint rises to **≈416.6 GiB**: about **300 GiB** in hot `IMAGES`, **34.6 GiB** in `L2`, **12.5 GiB** in `EMWIN`, and **69.5 GiB** already tucked under `ARCHIVE/WARM/IMAGES`. This TSV sum still trails the filesystem usage from `df -h` (440 GiB), implying ~23 GiB of staging/temp data or directories not traversed.

### Inventory Snapshot (Nov 27 w/Archive)

| Tree | Size (GiB) | Share of TSV | Notes |
| --- | ---: | ---: | --- |
| `IMAGES/*` | 300.07 | 72 % | Active GOES-19/18 PNGs plus EMWIN graphics; largest growth vector. |
| `ARCHIVE/WARM/IMAGES/*` | 69.52 | 16.7 % | Only GOES imagery is landing in WARM; no Level-2/EMWIN payloads yet. |
| `L2/*` | 34.57 | 8.3 % | Mostly GOES-19 Level-2 grids plus legacy GOES-16 captures. |
| `EMWIN/*` | 12.46 | 3.0 % | Mix of graphics and bulletin text. |
| *Other (Admin, caches)* | <0.01 | <0.1 % | Negligible footprint. |

### Storage Exhaustion Forecast (Nov 27 snapshot, 429 GiB free)

| Rate scenario | Basis (Oct 29 → Nov 27) | GiB/day | Days until full (429 GiB free) | Projected run-out (UTC) |
| --- | --- | ---: | ---: | --- |
| Trailing 30-day mean | Includes Oct 29–Nov 04 lull | 11.34 | 37.8 | 2026-01-03 |
| Steady-state mean | Mean of Nov 05–Nov 27 days | 14.10 | 30.4 | 2025-12-27 |
| Median day | 50th percentile of steady window | 14.57 | 29.4 | 2025-12-26 |
| 75th percentile | Typical “busy but normal” day | 14.69 | 29.2 | 2025-12-26 |
| 90th percentile | High-load day that occurs weekly | 14.75 | 29.1 | 2025-12-26 |
| Peak observed | Max day in Nov 05–Nov 27 window | 14.96 | 28.7 | 2025-12-25 |

Even under the most optimistic (30-day average) model, `/var/satellite` runs out of room right after New Year’s. Using the more realistic steady-state behavior, exhaustion lands between **25–27 Dec 2025**, leaving ~30 days to implement offload/down-sampling.

### Archive Validation (Nov 27 snapshot)

With `current_usage3.tsv` we can now see `/ARCHIVE/WARM` content. The crawl shows **69.5 GiB** of GOES imagery already housed under `ARCHIVE/WARM/IMAGES/*` (mostly February–August GOES-16 Full Disk scenes), proving the warm-tier tree exists and is reachable via the standard path. No other archive tiers (e.g., `ARCHIVE/WARM/L2` or `ARCHIVE/SEASONAL/*`) were observed, so Level-2 grids and EMWIN bulletins are still sitting entirely in the hot tree.

| Hot-tier bucket | Oldest timestamp still outside `/ARCHIVE` | Data older than 90 d still online | Notes |
| --- | --- | ---: | --- |
| `L2/*` | 2025-02-21 | 6.40 GiB | Legacy GOES-16 Level-2 grids never moved to Archive/Seasonal. |
| `IMAGES/*` | 2025-02-21 | 0.10 GiB | A handful of Feb LRIT frames remain unarchived. |
| `EMWIN/*` | 2025-05-27 | 0.38 GiB | Backlog of EMWIN text products predating Aug 29. |

That `>90 d` residue totals **≈6.9 GiB** and confirms the archival move/compress step has not swept L2 or EMWIN trees for months. Because only GOES imagery appears in `ARCHIVE/WARM`, the retention workflow likely filters on directory names and needs additional rules for Level-2 and EMWIN content. Capture a retention-manager dry-run log plus the next TSV after the fix to prove those directories start migrating. Recent systemd logs show why this has been so flaky: the service first crash-looped (~95 k restarts) because it could not read `/var/satellite/state`, and even after fixing that permission the process now dies mid-run once it deletes the directory it is still iterating (see the FileNotFoundError issued while walking `/IMAGES/GOES-19/Full Disk/2025-11-13_04-00-20`). The engine needs to tolerate directories disappearing during traversal (e.g., refresh the iterator on `FileNotFoundError` or walk files via `os.walk` with `topdown=False`).

## Observations
- GOES production has settled into a sustained 14–15 GB/day pace; with only 429 GiB free on `/var/satellite`, that leaves roughly one month before the disk fills unless data is thinned or relocated.
- `/ARCHIVE/WARM` contains ~70 GiB of imagery, showing that part of the archive tree is reachable, but Level-2 and EMWIN content never move—retention rules need to be expanded beyond GOES imagery.
- `goes-retention.service` still exits non-zero: it now moves some GOES-19 directories before crashing when `Path.rglob` touches a directory that was just migrated/deleted; the iterator must be hardened so it skips missing directories instead of killing the run.
- GOES-19 Full Disk scans dwarf every other stream; retention policies must prioritize thinning that directory first (e.g., reduce to 6‑hour cadence once data ages beyond Warm tier).
- Mesoscale sectors add a steady ~0.6 GB/day; if both sectors remain pinned 24/7, consider gating Mesoscale retention to mission-critical hours.
- Level-2 products are relatively light (~0.6 GB/day each for GOES-19/16), but they extend farther back in time than recent imagery; ensure the archive job keeps only the metrics required for reanalysis.
- EMWIN and NWS combined continue to contribute <0.3 GB/day, so their footprint is not a storage risk.
- Data coverage remains uneven: GOES-16 Level-2 entries still stop on 2025‑03‑07, while GOES-19 imagery now spans 53 ingest days but depends on the daily TSV crawl continuing without gaps. Keep validating that capture so percentile trends stay trustworthy.

## Next Steps
1. Schedule the updated `find … -printf … > current_usage.tsv` crawl (now including `/ARCHIVE`) daily and diff successive runs to catch sudden growth.
2. Feed the GOES-19 run rates into the jobs outlined in `docs/retention.md` (e.g., purge or downsample Full Disk frames after 30 days, keep only hourly mesos beyond the Hot tier).
3. Reconcile the 23 GiB gap between the TSV tally (~416.6 GiB) and the `df` usage (440 GiB) so `/ARCHIVE`, staging, and mount metadata are all being measured consistently.
4. Fix `goes-retention.service` (restore read/write access to `/var/satellite/state`, then guard its directory walk against deletions) and run it in dry-run followed by a live pass to migrate the February GOES-16 Level-2 grids plus EMWIN backlog into `/ARCHIVE`; capture logs plus the next TSV to prove the archive pipeline is active.
