# EMWIN Bulletins

## Dataset Summary
- Text products follow the `A_` channel; graphical products use the `Z_` channel.
- Major WMO originators include `KWBC` (NWS HQ), `KWAL` (NESDIS Wallops), regional forecast offices (e.g. `KJAX`, `KAPX`), and Pacific offices (`PGUM`, `NSTU`).

## Filename Anatomy
Typical EMWIN entry (text bulletin):
```
A_SACN85CWAO030100_C_KWIN_20250603010710_600668-2-SAHOURLY.txt
```
Component breakdown:
- `A` — SatDump queue identifier (`A`=text stream, `Z`=graphics).
- `SACN85CWAO030100` — WMO header compressed into `TTAAiiCCCCDDHHMM`.
- `C` — literal separator used by SatDump.
- `KWIN` — uplink/source identifier (SatDump station code).
- `20250603010710` — receipt timestamp (`YYYYMMDDhhmmss`, UTC).
- `600668-2` — SatDump message/fragment identifier and priority channel.
- `SAHOURLY` — AWIPS/NNN identifier (`NNNXXX`), extension indicates payload type (`.txt`, `.gif`, `.png`, `.jpg`).

The structure is consistent for `Z_` graphics, with the AWIPS identifier mapping to an image name (e.g. `RADSTHES.GIF`, `G16CIRUS.JPG`).

## Dominant Text Bulletin Families (`A_` files)
| AWIPS prefix | Example AWIPS ID       | WMO header examples                           | Operational use                                                                                                                        |
|--------------|------------------------|-----------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `SAH`        | `SAHOURLY`             | `SAUS70`, `SACN85`                            | Surface hourly observation digests (METAR collections). High-volume; ideal for ingestion into obs databases then archival compression. |
| `RWR`        | `RWRLOTIL`             | `ASUS43`, `ASUS44`                            | Regional Weather Roundup summaries by forecast office. Capture synoptic snapshots; useful for situational awareness dashboards.        |
| `MIS`        | `MISA50US`, `MISDCPSV` | `SXPA50`, `SXMS50`                            | Ocean Prediction Center marine summaries and satellite-derived analyses distributed via EMWIN. Group under marine forecast workflows.  |
| `CLI`        | `CLISHVLA`             | `CDUS44`, `CDUS43`                            | Daily climate reports (CLI) from local weather offices. Feed climate archives; retention may be long-term.                             |
| `TAF`        | `TAFALLUS`, `TAFS31US` | `FTUS80`, `FTUS31`                            | Terminal Aerodrome Forecast bulletins. Consider decoding to aviation forecast stores; keep most recent cycles online.                  |
| `RAD`        | `RADALLHI`, `RADSTHES` | `QATA00`, `QGTA98` (graphics) & `SDUS` (text) | National radar mosaics and regional radar summaries. Coordinate with radar imagery holdings to avoid duplication.                      |
| `OBS`        | `OBSA31GU`, `OBSU01AU` | `SXUS71`, `SXAK79`                            | Surface observation strings from Pacific, Alaska, and overseas territories. Integrate with observation ingestion pipelines.            |
| `RRM`        | `RRMJAXFL`, `RRMSEWWA` | `SRUS42`, `SRUS56`                            | Hydrologic river/rainfall reports. Route into hydrology databases; consider alert triggers.                                            |
| `PFM`        | `PFMTAEFL`, `PFMLCHLA` | `FOUS52`, `FOUS54`                            | Point Forecast Matrix products containing gridded guidance. Large text payloads; parse for model verification.                         |
| `ZFP`        | `ZFPCAESC`, `ZFPAPXMI` | `FPUS52`, `FPUS53`                            | Zone Forecast Products (public forecasts). High-value for public dissemination archives.                                               |

Additional notable prefixes include `TID` (tides), `AFD` (Area Forecast Discussions), `CFW` (Coastal Flood Warnings), `WWA` (Weather Watches/Warnings), and `SPS` (Special Weather Statements). Use the WMO `TTAAii` string to refine routing; e.g., `WWUS` blocks should feed warning notification systems.

## Graphical Bulletins (`Z_` files)
- Mainly `gif`/`jpg`/`png` mosaics.
- Radar composites: AWIPS IDs such as `RADGRTLK`, `RADNTHES`, `RADALLHI` originate from `QATA00`/`QGTA98` WMO headers.
- Satellite quicklooks: `G16CIRUS.JPG`, `G10FDIUS.JPG`, `IMGWWAUS.PNG`.
- Marine/aviation graphics: `G02HURUS.JPG` (tropical outlooks), `IMGSJUPR.JPG` (satellite imagery for Puerto Rico).

### Management Considerations
- Many graphics duplicate higher-resolution imagery stored under `IMAGES/`; decide whether EMWIN copies should be deduplicated or retained as low-bandwidth alternatives.
- Group graphics by AWIPS prefix (`RAD`, `G1x`, `IMG`, etc.) for targeted dissemination (e.g., deliver radar mosaics to web apps, store hurricane graphics separately).

## Handling & Lifecycle Guidance
- Consider cross-referencing EMWIN timestamps with imagery acquisitions to correlate textual alerts with visual evidence.

## Dashboard Integration Notes
- Surface decoded bulletins in the planned minute-by-minute dashboard by linking AWIPS IDs to spatial features (e.g., airport locations for `TAF`, forecast zones for `ZFP`).
- Use the catalog metadata to attach hover tooltips or sidebar callouts; example: hovering an airport on the map could reveal the latest `TAF` and `SAH` observations for that station.
- Pair radar mosaics (`RAD*`) and tropical graphics (`G0x*`, `IMG*`) with corresponding GOES imagery timestamps to give operators a quick toggle between human-generated summaries and satellite observations.
