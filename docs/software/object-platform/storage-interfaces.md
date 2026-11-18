# Storage Interfaces

## RustFS Object Layout

RustFS stores authoritative raw blobs and derivative outputs.

### Canonical Buckets

| Bucket | Purpose |
| --- | --- |
| `goes-source` | canonical SatDump/EMWIN/LRIT/CBOR/text/image blobs |
| `goes-dashboard` | dashboard-specific cached assets and exports |
| `goes-timelapse` | timelapse outputs |
| `goes-alerts` | alert packages and event bundles |
| `goes-analysis` | experimental and analytical derivative outputs |

### Object Key Conventions

Key conventions should be deterministic and not depend on the local source path alone.

Examples:

```text
goes-source/emwin/2026/04/15/A_FTUS80KWBC150010_C_KWIN_20260415001147_411405-2-TAFALLUS.txt
goes-source/goes19/full-disk/2026/05/24/18/ABI_False_Color/...png
goes-timelapse/goes19/meso2/false-color/6h/latest.mp4
goes-alerts/events/2026/05/24/tornado-watch-kwx-001/package.json
```

Key rules:

- prefix by source family
- include UTC date partitions
- preserve enough original identity to support deterministic lookups
- avoid embedding host-specific path prefixes

## CouchDB Databases / Namespaces

CouchDB can use one database with typed documents or several databases by concern. Start simple but keep separation by document family.

Suggested logical groupings:

| Grouping | Typical docs |
| --- | --- |
| `catalog` | `raw_product`, `decoded_product`, lineage docs |
| `projections` | `station_view`, dashboard views, alert projections |
| `control` | policy docs, retention docs, replay docs, repair docs |
| `operations` | health docs, audit docs, dead-letter summaries |

## Queue Interface

RabbitMQ is the default queue broker for this architecture.

The queue layer must support:

- at-least-once delivery
- explicit ack/nack
- consumer ack and requeue semantics
- dead-letter routing
- delayed retries
- message TTL where appropriate
- queue length and age bounds
- per-queue policy controls

Job envelope:

```json
{
  "job_id": "uuid-or-deterministic-key",
  "job_type": "decode-product",
  "trace_id": "trace-123",
  "attempt": 1,
  "lease_until": "2026-05-24T20:00:00Z",
  "payload": {
    "raw_product_id": "raw:..."
  }
}
```

## API Interfaces

### `catalog-api`

Stable internal API for other containers.

Suggested endpoints:

- `GET /products/{id}`
- `GET /products?family=TAF&since=...`
- `GET /stations/{code}`
- `GET /lineage/{id}`
- `GET /objects/{product_id}/resolve`
- `POST /replay` for controlled internal use

### `dashboard-api`

Browser-facing API only. It should not expose raw CouchDB structure directly.
