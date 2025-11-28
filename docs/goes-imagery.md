# GOES ABI Imagery

## Inventory Overview

| Branch                       | Notes                                                     |
|------------------------------|-----------------------------------------------------------|
| `IMAGES/GOES-18/Full Disk`   | Sparse sampling of GOES WEST feed for particular products |
| `IMAGES/GOES-19/Full Disk`   | Current operational full-disk feed                        |
| `IMAGES/GOES-19/Mesoscale 1` | Often pointed at the North East USA (≈1–5 min cadence).   |
| `IMAGES/GOES-19/Mesoscale 2` | Often pointed at the Mid East USA (≈1–5 min cadence).     |

> `product.cbor` appears once per timestamp folder and carries instrument geometry, calibration, and remap hints. Treat it as required sidecar metadata.

## Directory Layout
```
IMAGES/GOES-19/
  ├─ Full Disk/
  │   └─ 2025-10-31_20-30-20/
  │        ├─ G19_13_20251031T203020Z.png
  │        ├─ abi_rgb_Clean_Longwave_IR_Window_Band.png
  │        └─ product.cbor
  ├─ Mesoscale 1/
  └─ Mesoscale 2/
```
Timestamp folders (`YYYY-MM-DD_HH-MM-SS`) group all quicklook products for a single ABI scan. Mesoscale folders typically repeat every 60–90 seconds; full-disk scenes every ≈10 minutes in GOES-R series mode.

## ABI Band Imagery (`Gxx_<band>_<ISO>Z.png`)
- Pattern: `G19_13_20250531T140020Z.png` where `19` is the satellite number, `13` the ABI channel, and the suffix the scan nominal time (UTC).
- Band coverage observed:
  - `02` — red visible (0.64 µm) for daytime detail.
  - `07` — shortwave IR (3.9 µm) for fire/hot-spot detection.
  - `08/09` — upper & mid-level water vapor (6.2–6.9 µm).
  - `13` — clean longwave IR window (10.3 µm), core nighttime band.
  - `14/15` — longwave split-window pair supporting ash/SST applications.

## RGB Quicklooks (`abi_rgb_*`)
- Provided for clean/dirty IR window, shortwave, ABI false color, and water vapor composites; each offered with and without `_map` overlays.
- `_map` variants include coastlines/political boundaries and are suited to web dashboards.
- Maintain a regeneration path from base bands + `product.cbor` in case you cull redundant composites to save SSD space.

## Derivative Products
- Timelapse animations: generate MP4 sequences per band or RGB composite over selectable windows (e.g., latest 6 hours). Preserve frames participating in a timelapse in the same retention tier as the source imagery so they can be regenerated if encoding parameters change.
- Event highlights: create faster-cadence clips for significant weather (e.g., convective outbreaks) and publish alongside the raw directories via Nginx. Store manifest metadata (time range, band list, encoding settings) so the dashboard can link to pre-rendered media.
