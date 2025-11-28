# Storage Utilisation & Accrual Snapshot

`current_usage.tsv` (47 MiB, generated via `find … -printf …`) now provides per-file sizes and UTC timestamps for everything under `/var/satellite/satellite_raw`, excluding the unreliable `/ARCHIVE` tree. `df -h` still reports `/var/satellite` at **242 G used / 629 G free / 916 G total**.

## Data Capture Command

Retain this crawl for future runs (it ignores `/ARCHIVE` while emitting bytes + UTC timestamps for every other file):

```bash
sudo find /var/satellite/satellite_raw -path '/var/satellite/satellite_raw/ARCHIVE' -prune -o -type f -printf '%s\t%TY-%Tm-%Td\t%TH:%TM:%TS\t%p\n' | sort -k2,2 -k3,3 > /var/satellite/current_usage.tsv
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

Combined GOES-19 production load (Full Disk imagery + Mesoscale imagery + Level-2 grids) averages **~9 GB/day** over the most recent 15-day window (Oct 31–Nov 14) with spikes to **14.2 GB/day**. At that cadence, the current **629 GB free** window would be exhausted in roughly **70 days** without thinning or offloading, even before accounting for GOES-18 or EMWIN additions. Across the entire TSV, the catalogued (non-archive) content sums to **≈149 GiB**, leaving ~93 GiB of the `df`-reported usage attributable to `/ARCHIVE`, staging, or assets outside `/var/satellite/satellite_raw`.

## Observations
- GOES-19 Full Disk scans dwarf every other stream; retention policies must prioritize thinning that directory first (e.g., reduce to 6‑hour cadence once data ages beyond Warm tier).
- Mesoscale sectors add a steady ~0.6 GB/day; if both sectors remain pinned 24/7, consider gating Mesoscale retention to mission-critical hours.
- Level-2 products are relatively light (~0.6 GB/day each for GOES-19/16), but they extend farther back in time than recent imagery; ensure the archive job keeps only the metrics required for reanalysis.
- EMWIN and NWS combined continue to contribute <0.3 GB/day, so their footprint is not a storage risk.
- Data coverage is uneven: GOES-16 Level-2 entries stop on 2025‑03‑07 and the GOES-19 imagery set only spans the most recent 15 days. Future analyses should confirm that the TSV capture runs daily so moving averages stay accurate.

## Next Steps
1. Schedule the `find … -printf … > current_usage.tsv` crawl (or equivalent) daily and diff successive runs to catch sudden growth.
2. Feed the GOES-19 run rates into the jobs outlined in `docs/retention.md` (e.g., purge or downsample Full Disk frames after 30 days, keep only hourly mesos beyond the Hot tier).
3. Break out the remaining 93 GiB (difference between the TSV tally and `df`) to confirm how much sits in `/ARCHIVE` vs. staging; extend the crawl scope cautiously if those areas need auditing.
