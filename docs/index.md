# GOES Data Catalog

## Inventory Snapshot

| Top-level area    | Primary formats            | Notes                                                                                      |
|-------------------|----------------------------|--------------------------------------------------------------------------------------------|
| `EMWIN/`          | `txt`, `gif`, `jpg`, `png` | Emergency Managers Weather Information Network bulletins.                                  |
| `IMAGES/GOES-*`   | `png`, `cbor`              | GOES ABI full-disk & mesoscale imagery (GOES-19 is current production, GOES-16/18 legacy). |
| `IMAGES/NWS`      | `gif`                      | Human-generated forecast facsimiles from LRIT.                                             |
| `L2/`             | `png`, `cbor`              | GOES Level-2 derived fields (CAPE, TPW, cloud props, SST/LST).                             |
| `Admin Messages/` | `txt`                      | GOES-East operational notices.                                                             |

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
- Satellite branches under imagery/Level-2 roots (eg. `GOES-19`).
- Domains (`Full Disk`, `Mesoscale 1/2`) preceding timestamp folders (`YYYY-MM-DD_HH-MM-SS`).
- Timestamp folders combining raw bands (`G19_13_...png`), RGB composites (`abi_rgb_*`), and `product.cbor` metadata.
- EMWIN files delivered individually with WMO/AWIPS identifiers encoded in the basename.
