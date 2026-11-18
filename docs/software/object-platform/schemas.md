# Document Schemas

These are planned document shapes, not rigid SQL schemas. All documents should carry version fields so services can evolve without migration-heavy workflows.

## Common Fields

Recommended common fields for most document types:

```json
{
  "type": "raw_product",
  "doc_version": 1,
  "created_at": "2026-05-24T20:00:00Z",
  "updated_at": "2026-05-24T20:00:05Z",
  "trace_id": "trace-123"
}
```

## `raw_product`

Authoritative metadata for one ingested blob.

```json
{
  "_id": "raw:emwin:A_FTUS80KWBC150010_C_KWIN_20260415001147_411405-2-TAFALLUS.txt",
  "type": "raw_product",
  "doc_version": 1,
  "source_system": "satdump",
  "source_family": "emwin",
  "product_kind": "emwin-text",
  "product_family": "TAF",
  "awips_id": "TAFALLUS",
  "wmo_header": "FTUS80",
  "originator": "KWBC",
  "receipt_time": "2026-04-15T00:11:47Z",
  "issued_code": "150010",
  "fingerprint": {
    "sha256": "abc123",
    "size": 10234
  },
  "object_store": {
    "bucket": "goes-source",
    "key": "emwin/2026/04/15/...",
    "etag": "etag123",
    "content_type": "text/plain"
  },
  "ingest": {
    "status": "indexed",
    "first_seen_at": "2026-04-15T00:11:48Z",
    "indexed_at": "2026-04-15T00:11:49Z",
    "uploader_version": "ingest-uploader/1.0.0"
  },
  "retention": {
    "profile": "emwin-text-180d",
    "retain_until": "2026-10-12T00:11:47Z",
    "delete_after": "2026-10-19T00:11:47Z",
    "pin_reason": null
  }
}
```

## `decoded_product`

Parsed or enriched view derived from `raw_product`.

```json
{
  "_id": "decoded:raw:emwin:A_FTUS80KWBC150010_C_KWIN_20260415001147_411405-2-TAFALLUS.txt:emwin-taf-v1",
  "type": "decoded_product",
  "doc_version": 1,
  "raw_product_id": "raw:emwin:A_FTUS80KWBC150010_C_KWIN_20260415001147_411405-2-TAFALLUS.txt",
  "decoder_family": "emwin-taf",
  "decoder_version": "v1",
  "station_codes": ["KZZV", "KWBC"],
  "title": "Terminal forecasts: 1 stations",
  "summary": "KZZV valid 1500/1524: 22008KT P6SM SCT060 BKN250 ...",
  "reports": [],
  "materialized_for": ["dashboard", "alerts"],
  "lineage": {
    "derived_from": [
      "raw:emwin:A_FTUS80KWBC150010_C_KWIN_20260415001147_411405-2-TAFALLUS.txt"
    ]
  }
}
```

## `station_view`

Disposable materialized view for one station.

```json
{
  "_id": "station:KZZV:v1",
  "type": "station_view",
  "doc_version": 1,
  "projection_version": "v1",
  "station_code": "KZZV",
  "latest_products": [
    "raw:emwin:A_FTUS80KWBC150010_C_KWIN_20260415001147_411405-2-TAFALLUS.txt"
  ],
  "weather_summary": {
    "headline": "Local terminal forecast issued 15:00 UTC on day 15",
    "summary": "Forecast valid 1500/1524 ..."
  },
  "source_docs": [
    "decoded:raw:emwin:A_FTUS80KWBC150010_C_KWIN_20260415001147_411405-2-TAFALLUS.txt:emwin-taf-v1"
  ],
  "rebuildable": true
}
```

## `derived_asset`

Metadata for one project-specific derivative object.

```json
{
  "_id": "derived:timelapse:goes19:false-color:2026-05-24T18:00:00Z",
  "type": "derived_asset",
  "doc_version": 1,
  "project": "timelapse",
  "asset_kind": "mp4",
  "lineage": {
    "derived_from": [
      "raw:goes19:..."
    ]
  },
  "object_store": {
    "bucket": "goes-timelapse",
    "key": "goes19/meso2/false-color/6h/latest.mp4"
  },
  "retention": {
    "profile": "timelapse-30d",
    "retain_until": "2026-06-23T18:00:00Z"
  }
}
```

## `retention_event`

Control-plane audit record.

```json
{
  "_id": "retention:2026-05-24T20:00:00Z:raw:emwin:...",
  "type": "retention_event",
  "doc_version": 1,
  "target_doc_id": "raw:emwin:...",
  "action": "expire",
  "policy": "emwin-text-180d",
  "status": "scheduled"
}
```

## `repair_record`

Reconciliation record for drift detection and repair.

```json
{
  "_id": "repair:2026-05-24T20:05:00Z:raw:emwin:...",
  "type": "repair_record",
  "doc_version": 1,
  "target_doc_id": "raw:emwin:...",
  "issue": "object_missing",
  "status": "open",
  "proposed_action": "mark_orphaned"
}
```

## Versioning Rules

- new optional fields do not require immediate migration
- incompatible reader/writer changes must bump `doc_version`
- decoder output changes must bump `decoder_version`
- projection shape changes must bump `projection_version`
- old documents may coexist with new ones during rolling upgrades
