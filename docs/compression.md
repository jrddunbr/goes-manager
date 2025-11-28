# Zstandard Compression Snapshot

This note compares the in-progress `current_usage6.tsv` crawl (captured while the retention job was compressing imagery into `ARCHIVE/SEASONAL`) with the pre-compression snapshot `current_usage5.tsv`. For every `.zst` file observed in the new crawl we:

1. Stripped the `.zst` suffix to recover the seasonal path.
2. Matched that file by its dataset suffix (portion after `/IMAGES/`, `/L2/`, or `/EMWIN/`) to the older snapshot, which still contained the uncompressed counterpart in its original tier.
3. Grouped matches by product name (filename without timestamp/extension) and compared original vs compressed byte totals.

All sizes below are totals per product family and expressed in GiB.

| Product | Files | Original (GiB) | Compressed (GiB) | Ratio | Savings |
| --- | ---: | ---: | ---: | ---: | ---: |
| `product` | 2 408 | 0.014 | 0.010 | 0.7074 | 29.26 % |
| `abi_rgb_Upper-Level_Tropospheric_Water_Vapor` | 29 | 0.190 | 0.189 | 0.9947 | 0.53 % |
| `abi_rgb_Upper-Level_Tropospheric_Water_Vapor_map` | 29 | 0.193 | 0.192 | 0.9947 | 0.53 % |
| `abi_rgb_Infrared_Longwave_Window_Band` | 30 | 0.376 | 0.374 | 0.9952 | 0.48 % |
| `abi_rgb_Mid-level_Tropospheric_Water_Vapor` | 29 | 0.223 | 0.222 | 0.9954 | 0.46 % |
| `abi_rgb_Mid-level_Tropospheric_Water_Vapor_map` | 29 | 0.226 | 0.225 | 0.9955 | 0.45 % |
| `abi_rgb_Dirty_Longwave_Window_-_CIRA` | 29 | 0.310 | 0.309 | 0.9966 | 0.34 % |
| `abi_rgb_Dirty_Longwave_Window_-_CIRA_map` | 29 | 0.312 | 0.311 | 0.9969 | 0.31 % |
| `abi_rgb_Dirty_Longwave_Window` | 29 | 0.355 | 0.354 | 0.9971 | 0.29 % |
| `abi_rgb_Dirty_Longwave_Window_map` | 29 | 0.356 | 0.355 | 0.9973 | 0.27 % |
| `abi_rgb_Infrared_Longwave_Window_Band_map` | 29 | 0.364 | 0.364 | 0.9974 | 0.26 % |
| `G19_2` | 2 141 | 1.766 | 1.762 | 0.9977 | 0.23 % |
| `abi_rgb_Clean_Longwave_IR_Window_Band` | 2 405 | 1.577 | 1.575 | 0.9984 | 0.16 % |
| `abi_rgb_Clean_Longwave_IR_Window_Band_map` | 2 405 | 1.579 | 1.577 | 0.9984 | 0.16 % |
| `G19_8` | 29 | 0.143 | 0.143 | 0.9992 | 0.08 % |
| `abi_rgb_Shortwave_Window_Band` | 2 141 | 0.662 | 0.661 | 0.9992 | 0.08 % |
| `abi_rgb_Shortwave_Window_Band_map` | 2 141 | 0.663 | 0.663 | 0.9992 | 0.08 % |
| `G19_9` | 29 | 0.166 | 0.166 | 0.9995 | 0.05 % |
| `G19_15` | 29 | 0.264 | 0.264 | 0.9998 | 0.02 % |
| `G19_14` | 29 | 0.271 | 0.271 | 0.9999 | 0.01 % |
| `G19_7` | 2 141 | 0.483 | 0.483 | 0.9999 | 0.01 % |
| `G19_13` | 2 141 | 0.451 | 0.451 | 0.9999 | 0.01 % |
| `G18_13` | 264 | 0.721 | 0.721 | 1.0000 | -0.00 % |

**Totals:** 11.67 GiB of source data shrank to 11.64 GiB once compressed, a net ratio of 0.9978 (≈0.22 % or ~26 MiB saved).

## Observations

- Only the compact `product.cbor` manifests gain a meaningful benefit (~29 % reduction). All imagery assets are PNGs and already compressed, so Zstandard saves less than 0.6 % per product and, in the case of `G18_13`, slightly *increases* size (+0.002 %).
- Channel/band imagery (`G19_*` and related RGB composites) accounts for the bulk of the seasonal payload. Because these assets barely shrink, the storage benefit from compression is minimal (roughly 270 MiB reclaimed across the 11.7 GiB analyzed here).
- If seasonal capacity becomes tight, consider keeping only manifests compressed and simply moving PNGs without recompressing, or explore pre-converting imagery to formats that Zstandard can shrink (e.g., NetCDF tiles or raw arrays) before archiving.
