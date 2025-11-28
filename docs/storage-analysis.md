# Storage Utilization & Accrual Snapshot

## Data Capture Command

This command has been used for determining the utilization on the system.

```bash
sudo find /var/satellite -type f -printf '%s\t%TY-%Tm-%Td\t%TH:%TM:%TS\t%p\n' | sort -k2,2 -k3,3 > /var/satellite/current_usage.tsv
```

## Data-Type Run Rates (excl. `/ARCHIVE`)

| Data type | Avg GB/day | Peak GB/day | Notes |
| --- | ---: | ---: | --- |
| **GOES-19 Full Disk imagery** | 8.17 | 12.06 | Dominant consumer; every 30 min scan produces ~7–12 GB of PNGs/RGB composites. |
| **GOES-19 Mesoscale imagery** | 0.57 | 0.99 | Both Mesoscale sectors combined; cadence appears near-continuous during the sample. |
| **GOES-19 Level-2 grids** | 0.57 | 1.26 | Includes ACHT/ACHA/ACHT RGBs plus NetCDF-style PNG derivatives. |
| **GOES-18 Full Disk imagery** | 0.17 | 0.25 | Likely a subset for west-coast situational awareness. |
| **GOES-16 Level-2 grids** | 0.33 | 0.88 | Legacy ingest captured for two weeks; not observed after March. |
| **EMWIN graphics (.gif/.jpg/.png)** | 0.15 | 0.32 | CONUS composites (`Z_EINA*`, `Z_EIUS*`) dominate; growth roughly 150 MB/day. |
| **EMWIN text (.TXT)** | 0.10 | 0.23 | River statements and TAFs drive the larger bursts. |
| **NWS LRIT charts** | 0.01 | 0.02 | Hourly LRIT “USA_latest” set; footprint is negligible. |

### EMWIN Graphics Detail
The EMWIN tree splits naturally into static text and raster products. Graphics remain the primary growth vector (~0.15 GB/day steady state) while text bulletins add ~0.10 GB/day. Both spans exclude `/ARCHIVE`.

| EMWIN tier | Avg GB/day | Peak GB/day |
| --- | ---: | ---: |
| Graphics (`.gif/.jpg/.png`) | 0.15 | 0.32 |
| Text + miscellaneous | 0.10 | 0.23 |

Top EMWIN graphic products (identified by NOAA mnemonic at the tail of each filename) are below; 32 additional codes collectively contribute another **0.33 GiB** with <0.02 GB/day apiece.

| Product code | Example content | Avg GB/day | Peak GB/day |
| --- | --- | ---: | ---: |
| `G16CIRUS` | GOES-16 CONUS IR quicklooks | 0.03 | 0.06 |
| `G10CIRUS` | GOES West IR CONUS frames | 0.02 | 0.06 |
| `IMGWWAUS` | NWS watch/warning map (USA) | 0.02 | 0.03 |
| `G02HURUS` | Hurricane sector graphic | 0.02 | 0.03 |
| `G10FDIUS` | GOES West full-disk IR | 0.02 | 0.03 |
| `GPHJ88US` | Hemispheric precip/height panels | 0.01 | 0.02 |
| `IMGSJUPR` | San Juan PR regional graphic | 0.01 | 0.01 |
| `RADGRTLK` | Great Lakes radar mosaic | 0.01 | 0.01 |
| `RADNTHES` | Northern U.S. radar | 0.00 | 0.01 |
| `GMS008JA` | Himawari sector (Japan) | 0.00 | 0.01 |
| *Other 32 codes* | (e.g., `RADPACNW`, `RADREFUS`, `RADUMSVY`) | <0.02 | <0.01 |

### GOES-19 Sensor Mix

#### Full Disk ABI single-band frames
| Sensor (Full Disk) | Spectral class | Avg GB/day | Peak GB/day | Notes |
| --- | --- | ---: | ---: | --- |
| Band 07 Shortwave IR (3.9 µm) | LW IR | 0.33 | 0.49 | Key for fire/hotspot detection; produced every slot. |
| Band 14 IR Longwave (11.2 µm) | LW IR | 0.32 | 0.47 | Classic longwave window for cloud-top temp. |
| Band 13 Clean LW IR (10.3 µm) | LW IR | 0.31 | 0.46 | Severe-weather “Clean IR” band. |
| Band 15 Dirty LW IR (12.3 µm) | LW IR | 0.31 | 0.46 | Complements Band 13 for split-window products. |
| Band 02 Red (0.64 µm visible) | VIS | 0.25 | 0.36 | Primary visible reference; only major non-IR consumer. |
| Band 09 Mid-level WV (6.9 µm) | IR (water vapor) | 0.19 | 0.28 | Used for jet-level dynamics. |
| Band 08 Upper-level WV (6.2 µm) | IR (water vapor) | 0.17 | 0.24 | Completes the three-layer WV suite. |

#### Full Disk RGB composites
| Composite pair (base + `_map`) | Avg GB/day | Peak GB/day | Comment |
| --- | ---: | ---: | --- |
| ABI False Color | 1.17 | 1.78 | Situational awareness quicklook; doubled by map reprojection. |
| Shortwave Window Band | 0.92 | 1.34 | Differentiates snow/ice vs. clouds. |
| Infrared Longwave Window Band | 0.85 | 1.25 | Alternate paletting of Band 14. |
| Clean Longwave IR Window Band | 0.84 | 1.24 | Derived from Band 13; used by aviation products. |
| Dirty Longwave Window | 0.83 | 1.22 | Complements split-window thermal analysis. |
| Dirty Longwave Window – CIRA palette | 0.72 | 1.07 | Extra CIRA-tuned look applied to the same slots. |
| Mid-level Tropospheric WV | 0.52 | 0.76 | Matches ABI Band 09 dynamics. |
| Upper-level Tropospheric WV | 0.44 | 0.65 | Complements ABI Band 08. |

#### Mesoscale sectors (Mesos 1 + Mesos 2 combined)
| Sensor/composite | Avg GB/day | Peak GB/day | Notes |
| --- | ---: | ---: | --- |
| Band 02 Red (0.64 µm VIS) | 0.09 | 0.17 | Primary fast-cadence imagery for both mesos slots. |
| Band 07 Shortwave IR (3.9 µm) | 0.01 | 0.02 | Nighttime fire/hot-spot monitoring. |
| Band 13 Clean LW IR (10.3 µm) | 0.01 | 0.02 | Deep-convection view. |
| RGB ABI False Color / `_map` | 0.39 | 0.69 | Majority of mesos storage; two PNGs per scan. |
| RGB Shortwave Window Band / `_map` | 0.03 | 0.05 | Snow/ice vs. cloud differentiation. |
| RGB Clean Longwave IR Window Band / `_map` | 0.03 | 0.05 | Thermal rendering of the same frames. |
| Other mesos RGBs | <0.01 | <0.01 | Present but negligible in this capture. |

## Observations
- GOES production has settled into a sustained 14–15 GB/day pace.
- GOES-19 Full Disk scans dwarf every other stream
- Mesoscale sectors add a steady ~0.6 GB/day
- Level-2 products are relatively light at ~0.6 GB/day
- EMWIN and NWS combined continue to contribute <0.3 GB/day
