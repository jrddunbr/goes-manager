# NWS Facsimile Chart Imagery

## Snapshot Overview
- 930 LRIT GIFs catalogued under `IMAGES/NWS/` in the SatDump snapshot (`files.txt`).
- Aggregate footprint ≈140 MiB (GIF quicklooks are highly compressed).
- Time span: 2025-02-22 00:00 UTC through 2025-11-01 02:20 UTC.
- Products represent human-generated forecast analyses and guidance disseminated via the LRIT broadcast (e.g., OPC surface charts, tropical outlooks, high-wind probability maps).

## Filename Pattern
```
20250408140000-atlsfc48_latestBW.lrit.gif
```
Elements:
- `YYYYMMDDhhmmss` — issue or relay time (UTC).
- `<product>` — mnemonic for the chart (examples below).
- `.lrit.gif` — indicates a downlinked LRIT facsimile graphic (8-bit, 1-bit, or grayscale GIF).

## Common Product Families
| Product stem | Count | Description | Notes |
| --- | ---: | --- | --- |
| `atl48_latestBW`, `atl72_latestBW`, `atl72per_latestBW` | 290 | Atlantic 48–72 h surface prognosis (black & white). | Update every 6 h; keep recent cycles online for comparison. |
| `pacsfc24_latestBW`, `pacsfc48_latestBW`, `pacsfc72_latestBW` | 173 | Pacific surface forecasts (24–72 h). | Pair with marine forecasts from EMWIN (`MIS` family). |
| `USA_latest`, `USA_latestBW` | 158 | CONUS synoptic analysis. | Core situational awareness charts. |
| `pac24_latestBW`, `pac48_latestBW`, `pac48per_latestBW` | 141 | Pacific pressure/precip outlooks. | Useful for oceanic route planning dashboards. |
| `hiwind_atl_latest`, `hiwind_pac_latest` | 26 | High-wind probability maps. | Feed aviation/marine alert side panels. |
| `CAR_latest`, `GULF_latest`, `EPAC_latest`, `WATL_latest` | 26 | Basin-specific tropical outlooks. | Tie to tropical monitoring dashboards. |

## Management Guidance
- **Segregated handling**: Store human-generated charts separately from GOES imagery because refresh rate, provenance, and usage differ. This supports targeted retention and UI presentation (e.g., dedicated "Forecast Charts" side menu in the dashboard).
- **Retention rotation**: Because charts are superseded each cycle, keep a rolling window (e.g., last 30 days online) and archive older outputs to colder tiers while preserving at least one cycle per week for climatological comparison.
- **Metadata extraction**: Capture issue time and product stem into the catalog. Optionally parse region keywords (`atl`, `pac`, `usa`, `gulf`) to pre-group menus for the operator dashboard.
- **Image enhancement**: Consider re-rendering LRIT GIFs into higher-quality PNGs for the web UI if compression artifacts hinder readability. Retain the source GIF for auditing.
- **Dashboard hooks**: Provide a "Forecast products" panel listing available charts by timestamp. Hover/click actions can show chart annotations or links to relevant EMWIN textual forecasts (e.g., Surface Forecast discussions `PFM`, `MIS`).

## Future Enhancements
- Integrate chart metadata with EMWIN bulletin ingests so each graphic references the bulletin or forecast cycle that generated it.
- Automate verification of receipt cadence (expected every 3 or 6 hours). Flag missing cycles for manual recovery.
