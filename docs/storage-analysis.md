# Storage Utilization & Accrual Snapshot

## Data Capture Command

This command has been used for determining the utilization on the system.

```bash
sudo find /var/satellite -type f -printf '%s\t%TY-%Tm-%Td\t%TH:%TM:%TS\t%p\n' | sort -k2,2 -k3,3 > /var/satellite/current_usage.tsv
```

## Data-Type Run Rates (excl. `/ARCHIVE`)
Rates below reflect the latest 7-day window (2026-01-16 to 2026-01-22) from `today_current_usage.tsv`. Peak values are all-time daily highs across the full dataset.

| Data type | Avg GB/day (7-day) | Peak GB/day (all-time) | Notes |
| --- | ---: | ---: | --- |
| **GOES-19 Full Disk imagery** | 5.38 | 11.63 | Dominant consumer; full-disk RGBs drive most of the variance. |
| **GOES-19 Mesoscale imagery** | 0.26 | 0.87 | Both Mesoscale sectors combined; cadence remains near-continuous. |
| **GOES-19 Level-2 grids** | 1.14 | 1.22 | Includes ACHT/ACHA/ACHT RGBs plus PNG derivatives. |
| **GOES-18 Full Disk imagery** | 0.12 | 0.24 | Subset retained for west-coast situational awareness. |
| **EMWIN graphics (.gif/.jpg/.png)** | 0.27 | 0.33 | CONUS composites (`Z_EINA*`, `Z_EIUS*`) remain the bulk of the footprint. |
| **EMWIN text (.TXT)** | 0.22 | 0.25 | River statements and TAFs continue to dominate spikes. |
| **NWS LRIT charts** | 0.01 | 0.02 | Hourly LRIT “USA_latest” set; footprint stays negligible. |

### EMWIN Graphics Detail
The EMWIN tree splits naturally into static text and raster products. Graphics remain the primary growth vector (~0.27 GB/day steady state) while text bulletins add ~0.22 GB/day. Both spans exclude `/ARCHIVE`.

| EMWIN tier | Avg GB/day (7-day) | Peak GB/day (all-time) |
| --- | ---: | ---: |
| Graphics (`.gif/.jpg/.png`) | 0.27 | 0.33 |
| Text + miscellaneous | 0.22 | 0.25 |

Top EMWIN graphic products (identified by NOAA mnemonic at the tail of each filename) are below; 30 additional codes collectively contribute another **0.06 GiB/day** with <0.02 GB/day peaks apiece.

| Product code | Example content | Avg GB/day (7-day) | Peak GB/day (all-time) |
| --- | --- | ---: | ---: |
| `G16CIRUS` | GOES-16 CONUS IR quicklooks | 0.05 | 0.06 |
| `G10CIRUS` | GOES West IR CONUS frames | 0.03 | 0.07 |
| `IMGWWAUS` | NWS watch/warning map (USA) | 0.03 | 0.03 |
| `G02HURUS` | Hurricane sector graphic | 0.02 | 0.03 |
| `G10FDIUS` | GOES West full-disk IR | 0.02 | 0.03 |
| `GPHJ88US` | Hemispheric precip/height panels | 0.01 | 0.02 |
| `RADGRTLK` | Great Lakes radar mosaic | 0.01 | 0.01 |
| `RADUMSVY` | Upper Mississippi Valley radar | 0.01 | 0.01 |
| `RADNTHES` | Northern U.S. radar | 0.01 | 0.01 |
| `IMGSJUPR` | San Juan PR regional graphic | 0.01 | 0.02 |
| *Other 30 codes* | (e.g., `RADPACNW`, `RADREFUS`, `GMS008JA`) | <0.01 | <0.02 |

### GOES-19 Sensor Mix

#### Full Disk ABI single-band frames
| Sensor (Full Disk) | Spectral class | Avg GB/day (7-day) | Peak GB/day (all-time) | Notes |
| --- | --- | ---: | ---: | --- |
| Band 07 Shortwave IR (3.9 µm) | LW IR | 0.24 | 0.48 | Key for fire/hotspot detection; produced every slot. |
| Band 14 IR Longwave (11.2 µm) | LW IR | 0.23 | 0.45 | Classic longwave window for cloud-top temp. |
| Band 13 Clean LW IR (10.3 µm) | LW IR | 0.23 | 0.45 | Severe-weather “Clean IR” band. |
| Band 15 Dirty LW IR (12.3 µm) | LW IR | 0.22 | 0.44 | Complements Band 13 for split-window products. |
| Band 02 Red (0.64 µm visible) | VIS | 0.18 | 0.35 | Primary visible reference; only major non-IR consumer. |
| Band 09 Mid-level WV (6.9 µm) | IR (water vapor) | 0.13 | 0.27 | Used for jet-level dynamics. |
| Band 08 Upper-level WV (6.2 µm) | IR (water vapor) | 0.11 | 0.23 | Completes the three-layer WV suite. |

#### Full Disk RGB composites
| Composite pair (base + `_map`) | Avg GB/day (7-day) | Peak GB/day (all-time) | Comment |
| --- | ---: | ---: | --- |
| ABI False Color | 0.39 | 1.75 | Situational awareness quicklook; doubled by map reprojection. |
| Shortwave Window Band | 0.67 | 1.32 | Differentiates snow/ice vs. clouds. |
| Infrared Longwave Window Band | 0.61 | 1.22 | Alternate paletting of Band 14. |
| Clean Longwave IR Window Band | 0.61 | 1.21 | Derived from Band 13; used by aviation products. |
| Dirty Longwave Window | 0.59 | 1.19 | Complements split-window thermal analysis. |
| Dirty Longwave Window – CIRA palette | 0.51 | 1.04 | Extra CIRA-tuned look applied to the same slots. |
| Mid-level Tropospheric WV | 0.36 | 0.72 | Matches ABI Band 09 dynamics. |
| Upper-level Tropospheric WV | 0.31 | 0.61 | Complements ABI Band 08. |

#### Mesoscale sectors (Mesos 1 + Mesos 2 combined)
| Sensor/composite | Avg GB/day (7-day) | Peak GB/day (all-time) | Notes |
| --- | ---: | ---: | --- |
| Band 02 Red (0.64 µm VIS) | 0.07 | 0.15 | Primary fast-cadence imagery for both mesos slots. |
| Band 07 Shortwave IR (3.9 µm) | 0.01 | 0.02 | Nighttime fire/hot-spot monitoring. |
| Band 13 Clean LW IR (10.3 µm) | 0.01 | 0.02 | Deep-convection view. |
| RGB ABI False Color / `_map` | 0.13 | 0.60 | Majority of mesos storage; two PNGs per scan. |
| RGB Shortwave Window Band / `_map` | 0.02 | 0.05 | Snow/ice vs. cloud differentiation. |
| RGB Clean Longwave IR Window Band / `_map` | 0.02 | 0.04 | Thermal rendering of the same frames. |
| Other mesos RGBs | <0.01 | <0.01 | Present but negligible in this capture. |

## Snapshot Comparison (Non-Archive, 7-Day Window)
- Latest 7-day ingest averages 7.40 GiB/day versus 6.65 GiB/day in the prior snapshot window (2025-11-21 to 2025-11-27).
- GOES-19 Full Disk imagery is up ~0.81 GiB/day; mesoscale imagery is up ~0.07 GiB/day.
- GOES-19 Level-2 grids are down ~0.07 GiB/day; EMWIN graphics are down ~0.02 GiB/day; EMWIN text is flat.
- No new non-archive stream families appeared; GOES-16 Level-2 grids are still absent in the latest window.

## Capacity Outlook
- Filesystem utilization from user-provided `df` on 2026-04-14.
- `current_usage10.tsv` captures 855.9 GiB on disk (including `/ARCHIVE`) through 2026-04-04 16:31:46; the non-archive working set is 99.8 GiB.
- From the previous snapshot (`current_usage9.tsv`, ending 2025-11-27 23:12:34) to `current_usage10.tsv`, net growth was +532.1 GiB over 127.7 days (4.17 GiB/day).
- `/var/satellite` reports 869.2 GiB used of 915.8 GiB total (100 % used), with 0.0 GiB free.
- At the recent 4.17 GiB/day growth rate, the filesystem has no remaining runway without immediate cleanup or additional retention.
- Retention settings in `docs/retention.md` remain the primary lever for reducing this net growth rate.

## Observations
- Current non-archive ingest runs ~7.4 GiB/day, led by GOES-19 Full Disk imagery.
- GOES-19 Level-2 grids now exceed mesoscale in average daily footprint.
- EMWIN graphics + text remain ~0.5 GiB/day combined, with minimal variance.
- NWS LRIT charts continue to be negligible (<0.01 GiB/day).
