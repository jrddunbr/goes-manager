# Microservices

Each microservice runs in its own container. Services communicate through:

- RabbitMQ queues for work dispatch
- CouchDB for durable metadata and projections
- RustFS for object IO
- internal HTTP APIs for selected read and control surfaces

## Core Services

| Service | Purpose | Reads | Writes | Notes |
| --- | --- | --- | --- | --- |
| `ingest-watcher` | Detect incoming SatDump outputs and enqueue canonical ingest work. | SatDump input volume, optional manifest push API | queue | No RustFS/CouchDB write access required. |
| `platform-init` | Bootstrap core platform state. | RustFS, CouchDB, RabbitMQ config | buckets, databases, queue topology | Runs before worker steady state. |
| `ingest-uploader` | Classify files, hash them, upload canonical blobs, write `raw_product`. | SatDump input volume, queue | RustFS `goes-source`, CouchDB `raw_product`, queue | Primary object ingress path. |
| `decoder-workers` | Parse EMWIN text, CBOR, imagery metadata, and normalized extracts. | queue, CouchDB `raw_product`, RustFS `goes-source` | CouchDB `decoded_product`, queue | Versioned decoder families. |
| `materializer-workers` | Build disposable projections for dashboards, alerts, and catalog views. | queue, CouchDB `raw_product`/`decoded_product` | CouchDB projections, queue | Rebuildable at any time. |
| `catalog-api` | Stable internal API for product lookup, lineage, and object resolution. | CouchDB, RustFS | HTTP API | Shields consumers from raw document details. |
| `dashboard-api` | Browser-facing dashboard backend. | `catalog-api`, RustFS | optional dashboard bucket assets | Read-mostly service. |
| `timelapse-worker` | Build timelapse derivatives from source imagery. | queue, `catalog-api`, RustFS `goes-source` | RustFS `goes-timelapse`, CouchDB project docs | Queue-driven and replay-safe. |
| `alerts-worker` | Produce alert packages, summaries, notifications, and event bundles. | queue, `catalog-api`, decoded docs | RustFS `goes-alerts`, CouchDB project docs, webhooks | Writes enriched operational outputs. |
| `analysis-worker` | Generate experimental or analytical derivative products. | queue, `catalog-api`, RustFS `goes-source` | RustFS `goes-analysis`, CouchDB project docs | Lower trust tier than core services. |
| `retention-controller` | Manage object lifecycle profiles and policy reconciliation. | CouchDB policy docs, RustFS lifecycle state | RustFS lifecycle config, CouchDB retention state | Blob lifecycle control. |
| `metadata-retention-controller` | Expire/tombstone metadata and disposable projections. | CouchDB docs | CouchDB tombstones/audit docs | Metadata lifecycle control. |
| `reconciler` | Detect and repair drift between RustFS objects, CouchDB docs, and queue outcomes. | RustFS, CouchDB, queue | CouchDB repair docs, queue | Core integrity service. |
| `backfill-runner` | Re-enqueue ingest, decode, projection, or derivative jobs for historical data. | CouchDB, RustFS, queue | queue, audit docs | Explicit replay path. |
| `observability-agent` | Emit metrics, consistency summaries, and service health state. | service health endpoints, CouchDB, queue, RustFS | metrics backend, CouchDB health docs, alerts | Platform health, not just SatDump logs. |

## Queue Topics / Streams

The execution plane should provide at least these RabbitMQ queues and dead-letter bindings:

| Queue | Producers | Consumers |
| --- | --- | --- |
| `ingest-jobs` | `ingest-watcher`, `backfill-runner` | `ingest-uploader` |
| `decode-jobs` | `ingest-uploader`, `backfill-runner` | `decoder-workers` |
| `materialize-jobs` | `decoder-workers`, `backfill-runner` | `materializer-workers` |
| `derivative-jobs` | `materializer-workers`, `backfill-runner` | `timelapse-worker`, `alerts-worker`, `analysis-worker` |
| `retention-jobs` | `retention-controller`, `metadata-retention-controller` | control-plane workers |
| `reconcile-jobs` | `observability-agent`, `retention-controller`, `backfill-runner` | `reconciler` |
| `dead-letter` | any worker | operator review / replay |

## Service Contracts

### `ingest-watcher`

- never performs object uploads itself
- emits deterministic work items keyed by source path and first-seen time
- must tolerate duplicate notifications

### `platform-init`

- ensures canonical buckets exist
- ensures required CouchDB databases exist
- ensures RabbitMQ primary, retry, and dead-letter queues are declared
- should be safe to rerun

### `ingest-uploader`

- computes file fingerprint before upload
- uploads canonical blob once
- writes or upserts `raw_product`
- emits follow-up decode work only after object write succeeds

### `decoder-workers`

- read authoritative blob refs from `raw_product`
- write versioned `decoded_product`
- never mutate source object metadata except through controlled state transitions

### `materializer-workers`

- produce disposable projections
- may be rerun without side effects beyond overwriting newer equivalent projections
- must declare `projection_version`

### `reconciler`

- can re-enqueue work safely
- can mark docs as orphaned, stale, missing, or superseded
- must never delete source-of-truth blobs directly
