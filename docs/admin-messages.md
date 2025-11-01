# Administrative Messages

Two GOES-East administrative status bulletins are catalogued under `Admin Messages/`:

| File | Timestamp embedded | Description |
| --- | --- | --- |
| `GOES_EAST_Admin_message_updated_2025.04.07.txt` | 2025-04-07 | Operational notice (likely spacecraft scheduling/software update). |
| `GOES_EAST_Admin_message_updated_2023.01.04.txt` | 2023-01-04 | Legacy message retained from an earlier SatDump session. |

Administrative messages announce planned maintenance windows, data outages, instrument configuration changes, or product availability updates. They provide crucial context when interpreting gaps in imagery or Level-2 feeds.

## Management Recommendations
- Surface the most recent message in monitoring dashboards so operators are aware of scheduled outages or mode changes.
- Archive older messages for audit but link them to the time ranges where data gaps occur (e.g., annotate timelines in `files.txt`).
- If future ingestion runs capture additional admin messages, consider versioning them by date in a structured database or tagging system for quick retrieval.
