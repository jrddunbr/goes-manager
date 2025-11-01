# GOES ABI Imagery

## Inventory Overview
Counts derived from the `files.txt` snapshot collected in SatDump. Refresh numbers after each ingest run.

| Branch | Timestamp folders (`product.cbor`) | Earliest scene | Latest scene | Approx size | Notes |
| --- | ---: | --- | --- | ---: | --- |
| `IMAGES/GOES-16/Full Disk` | 300 | 2025-02-21 13:30 UTC | 2025-03-09 20:00 UTC | 46.98 GiB | Legacy coverage; GOES-16 ceased transmission later in 2025. |
| `IMAGES/GOES-16/Mesoscale 1` | 509 | 2025-02-21 13:52 UTC | 2025-03-09 20:07 UTC | 1.75 GiB | High cadence legacy mesoscale sector. |
| `IMAGES/GOES-16/Mesoscale 2` | 504 | 2025-02-21 13:52 UTC | 2025-03-09 20:07 UTC | 1.59 GiB | High cadence legacy mesoscale sector. |
| `IMAGES/GOES-18/Full Disk` | 174 | 2025-02-21 13:50 UTC | 2025-11-01 01:50 UTC | 1.37 GiB | Sparse sampling; confirm requirement before allocating retention. |
| `IMAGES/GOES-19/Full Disk` | 130 | 2025-04-07 21:00 UTC | 2025-11-01 02:00 UTC | 19.57 GiB | Current operational full-disk feed replacing GOES-16. |
| `IMAGES/GOES-19/Mesoscale 1` | 183 | 2025-04-07 21:22 UTC | 2025-11-01 02:22 UTC | 0.79 GiB | Production mesoscale request stream (≈1–5 min cadence). |
| `IMAGES/GOES-19/Mesoscale 2` | 182 | 2025-04-07 21:22 UTC | 2025-11-01 02:22 UTC | 0.67 GiB | Companion mesoscale sector. |

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
- Recommendations:
  - Track availability of each band per timestamp in the catalog so gaps trigger retries.
  - Prioritise bands 2, 7, 8/9, and 13–15 for operational dashboards; archive others based on storage policy.
  - For quantitative workflows, convert PNG quicklooks to calibrated grids using the corresponding Level-2 products or raw GOES netCDF sources.

## RGB Quicklooks (`abi_rgb_*`)
- Provided for clean/dirty IR window, shortwave, ABI false color, and water vapor composites; each offered with and without `_map` overlays.
- `_map` variants include coastlines/political boundaries and are suited to web dashboards.
- Maintain a regeneration path from base bands + `product.cbor` in case you cull redundant composites to save SSD space.

## Metadata Handling
- Parse `product.cbor` once per scan into a structured store (e.g., SQLite/Parquet) capturing projection parameters, pixel resolution, satellite nadir, and LUT references.
- Link metadata records to dashboard layers so reprojection and hover-to-value conversions can occur server-side.

## Dashboard Alignment Notes
- Every-minute dashboard updates should poll the most recent GOES-19 mesoscale timestamps; maintain a pointer to the latest successful ingest to detect lapses quickly.
- Provide drill-down layers that toggle band/RGB combinations; the metadata catalog can drive layer availability in the side menu.
- Coordinate with Level-2 products to back tooltips (e.g., hovering a map could show cloud-top temperature or rain rate drawn from `L2/`).

## Derivative Products
- Timelapse animations: generate MP4/WEBM sequences per band or RGB composite over selectable windows (e.g., latest 6 hours). Preserve frames participating in a timelapse in the same retention tier as the source imagery so they can be regenerated if encoding parameters change.
- Event highlights: create faster-cadence clips for significant weather (e.g., convective outbreaks) and publish alongside the raw directories via Nginx. Store manifest metadata (time range, band list, encoding settings) so the dashboard can link to pre-rendered media.
- Downstream distribution: for web delivery keep encoded derivatives under `satellite_raw/derivatives/` (or similar) and reference them from the autoindex headers described in `web/` to guide visitors.

## Legacy Data (GOES-16/18)
- Keep legacy imagery available for historical comparison but assign them to colder retention classes (see `retention.md`).
- Flag GOES-16 as historical and GOES-18 as optional to avoid mixing with primary dashboard feeds.
