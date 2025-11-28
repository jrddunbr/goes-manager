# NWS Facsimile Chart Imagery

Products represent human-generated forecast analyses and guidance disseminated via the LRIT broadcast (e.g., OPC surface charts, tropical outlooks, high-wind probability maps).

## Filename Pattern
```
20250408140000-atlsfc48_latestBW.lrit.gif
```
Elements:
- `YYYYMMDDhhmmss` — issue or relay time (UTC).
- `<product>` — mnemonic for the chart (examples below).
- `.lrit.gif` — indicates a downlinked LRIT facsimile graphic (8-bit, 1-bit, or grayscale GIF).

## Common Product Families
| Product stem                                                  | Count | Description                                         | Notes                                                 |
|---------------------------------------------------------------|------:|-----------------------------------------------------|-------------------------------------------------------|
| `atl48_latestBW`, `atl72_latestBW`, `atl72per_latestBW`       |   290 | Atlantic 48–72 h surface prognosis (black & white). | Updates every 6 h                                     |
| `pacsfc24_latestBW`, `pacsfc48_latestBW`, `pacsfc72_latestBW` |   173 | Pacific surface forecasts (24–72 h).                | Pair with marine forecasts from EMWIN (`MIS` family). |
| `USA_latest`, `USA_latestBW`                                  |   158 | CONUS synoptic analysis.                            | Core situational awareness charts.                    |
| `pac24_latestBW`, `pac48_latestBW`, `pac48per_latestBW`       |   141 | Pacific pressure/precip outlooks.                   | Useful for oceanic route planning dashboards.         |
| `hiwind_atl_latest`, `hiwind_pac_latest`                      |    26 | High-wind probability maps.                         | Feed aviation/marine alert side panels.               |
| `CAR_latest`, `GULF_latest`, `EPAC_latest`, `WATL_latest`     |    26 | Basin-specific tropical outlooks.                   | Tie to tropical monitoring dashboards.                |

## Future Enhancements
- Integrate chart metadata with EMWIN bulletin ingests so each graphic references the bulletin or forecast cycle that generated it.
