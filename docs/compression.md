# Zstandard Compression Snapshot

This note compares the fully processed `current_usage7.tsv` crawl (captured after a completed retention/compression run) with the pre-compression snapshot `current_usage5.tsv`. For every `.zst` file observed in the new crawl we:

1. Stripped the `.zst` suffix to recover the seasonal path.
2. Matched that file by its dataset suffix (portion after `/IMAGES/`, `/L2/`, or `/EMWIN/`) to the older snapshot, which still contained the uncompressed counterpart in its original tier.
3. Grouped matches by product name (filename without timestamp/extension) and compared original vs compressed byte totals.

All sizes below are totals per product family and expressed in GiB.

| Product | Files | Original (GiB) | Compressed (GiB) | Ratio | Savings |
| --- | ---: | ---: | ---: | ---: | ---: |
| `product` | 4 370 | 0.032 | 0.021 | 0.6436 | 35.64 % |
| `abi_rgb_Upper-Level_Tropospheric_Water_Vapor_map` | 275 | 1.834 | 1.819 | 0.9919 | 0.81 % |
| `abi_rgb_Upper-Level_Tropospheric_Water_Vapor` | 274 | 1.799 | 1.789 | 0.9947 | 0.53 % |
| `abi_rgb_Mid-level_Tropospheric_Water_Vapor_map` | 275 | 2.137 | 2.127 | 0.9954 | 0.46 % |
| `abi_rgb_Mid-level_Tropospheric_Water_Vapor` | 274 | 2.103 | 2.093 | 0.9954 | 0.46 % |
| `abi_rgb_Dirty_Longwave_Window_-_CIRA` | 276 | 2.954 | 2.944 | 0.9966 | 0.34 % |
| `abi_rgb_Dirty_Longwave_Window_-_CIRA_map` | 275 | 2.958 | 2.949 | 0.9969 | 0.31 % |
| `abi_rgb_Dirty_Longwave_Window` | 276 | 3.376 | 3.366 | 0.9971 | 0.29 % |
| `abi_rgb_Infrared_Longwave_Window_Band` | 275 | 3.456 | 3.446 | 0.9972 | 0.28 % |
| `abi_rgb_Dirty_Longwave_Window_map` | 275 | 3.375 | 3.366 | 0.9973 | 0.27 % |
| `abi_rgb_Infrared_Longwave_Window_Band_map` | 276 | 3.479 | 3.470 | 0.9974 | 0.26 % |
| `abi_rgb_Clean_Longwave_IR_Window_Band` | 2 650 | 4.625 | 4.614 | 0.9976 | 0.24 % |
| `abi_rgb_Clean_Longwave_IR_Window_Band_map` | 2 650 | 4.637 | 4.626 | 0.9977 | 0.23 % |
| `G19_2` | 2 387 | 3.536 | 3.530 | 0.9984 | 0.16 % |
| `abi_rgb_Shortwave_Window_Band` | 2 388 | 4.000 | 3.995 | 0.9987 | 0.13 % |
| `abi_rgb_Shortwave_Window_Band_map` | 2 388 | 4.015 | 4.010 | 0.9987 | 0.13 % |
| `G19_8` | 274 | 1.355 | 1.354 | 0.9992 | 0.08 % |
| `G19_9` | 275 | 1.575 | 1.574 | 0.9994 | 0.06 % |
| `G19_7` | 2 388 | 2.924 | 2.924 | 0.9998 | 0.02 % |
| `G19_15` | 275 | 2.502 | 2.502 | 0.9998 | 0.02 % |
| `G19_13` | 2 385 | 2.712 | 2.711 | 0.9998 | 0.02 % |
| `G19_14` | 276 | 2.588 | 2.588 | 0.9998 | 0.02 % |
| `G18_13` | 264 | 0.721 | 0.721 | 1.0000 | -0.00 % |
| `abi_rgb_Cloud_top_Temperature_(ACHT)` | 568 | 8.213 | N/A | N/A | N/A |
| `EMWIN graphics` | 54 673 | 7.196 | N/A | N/A | N/A |
| `G19_ACHT` | 568 | 6.079 | N/A | N/A | N/A |
| `EMWIN bulletins` | 663 918 | 5.301 | N/A | N/A | N/A |
| `G19_SST` | 140 | 0.988 | N/A | N/A | N/A |
| `abi_rgb_Sea_Surface_Temperature` | 140 | 0.982 | N/A | N/A | N/A |
| `NWS LRIT charts` | 3 619 | 0.495 | N/A | N/A | N/A |
| `abi_rgb_AWG_Cloud_Height_Algorithm_(ACHA)` | 562 | 0.468 | N/A | N/A | N/A |
| `G19_ACHA` | 562 | 0.332 | N/A | N/A | N/A |
| `G19_RRQPE` | 563 | 0.291 | N/A | N/A | N/A |
| `abi_rgb_Rain_Rate_Per_Quarter_Hour` | 563 | 0.213 | N/A | N/A | N/A |
| `abi_rgb_Total_Precipitable_Water` | 463 | 0.128 | N/A | N/A | N/A |

**Totals (measured imagery only):** 62.69 GiB of source data shrank to 62.54 GiB once compressed, a net ratio of 0.9976 (≈0.24 % or ~150 MiB saved). The additional rows above represent uncompressed categories slated for future measurement.

## Observations

- Only the compact `product.cbor` manifests gain a meaningful benefit (~36 % reduction). Every other product in the seasonal tree remains a PNG/JPG/GIF asset and already arrives compressed, so Zstandard trims at most 0.8 % per family and, in the case of `G18_13`, still bloats slightly.
- Channel/band imagery (`G19_*`, RGB composites, etc.) accounts for essentially all of the seasonal footprint and yields just ~150 MiB reclaimed across the 62.7 GiB analyzed here. The computational cost of recompressing them is rarely justified on constrained hardware.
- Level-2 grids (`G19_ACHT`, `G19_RRQPE`, etc.), EMWIN bulletins/graphics, and NWS LRIT charts now appear in the table with `N/A` placeholders—they make up several additional gigabytes but have not yet reached the compression stage, so future runs should revisit them once `.zst` outputs exist.
