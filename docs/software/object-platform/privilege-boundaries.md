# Privilege Boundaries

The platform assumes least-privilege service identities.

## Trust Model

- only a small number of services can write canonical source data
- most services are read-only against source blobs
- write access to projections and derivative buckets is scoped per service
- lifecycle changes are restricted to control-plane services

## RustFS Access Policy

| Service | `goes-source` | project buckets | lifecycle admin |
| --- | --- | --- | --- |
| `ingest-watcher` | none | none | no |
| `ingest-uploader` | read/write | none | no |
| `decoder-workers` | read | none | no |
| `materializer-workers` | read | optional write to `goes-dashboard` | no |
| `catalog-api` | read | read | no |
| `dashboard-api` | read | read `goes-dashboard` | no |
| `timelapse-worker` | read | write `goes-timelapse` | no |
| `alerts-worker` | read | write `goes-alerts` | no |
| `analysis-worker` | read | write `goes-analysis` | no |
| `retention-controller` | read | read | yes |
| `metadata-retention-controller` | none | none | no |
| `reconciler` | read | read | no |

## CouchDB Access Policy

| Service | Read | Write |
| --- | --- | --- |
| `ingest-watcher` | none | none |
| `ingest-uploader` | policy + dedupe views | `raw_product`, ingest audit |
| `decoder-workers` | `raw_product` | `decoded_product`, decode audit |
| `materializer-workers` | `raw_product`, `decoded_product` | projection docs |
| `catalog-api` | all queryable product/projection docs | none |
| `dashboard-api` | read via `catalog-api` preferred | none |
| `timelapse-worker` | source/projection docs | project docs |
| `alerts-worker` | source/projection docs | project docs, event docs |
| `analysis-worker` | source/projection docs | project docs |
| `retention-controller` | product + policy docs | retention state, retention events |
| `metadata-retention-controller` | all lifecycle-managed docs | tombstones, cleanup audit |
| `reconciler` | all platform docs | repair docs, state corrections |
| `backfill-runner` | all platform docs | replay audit docs |

## Administrative Boundaries

Three services are effectively privileged:

- `ingest-uploader`
- `retention-controller`
- `reconciler`

These should:

- run with separate credentials from app-facing services
- live on internal-only networks
- emit verbose audit logs
- require explicit operator review for destructive or repair-heavy modes

## Bucket/Database Isolation

- canonical source bucket is separate from derivative buckets
- project-specific documents should be identifiable by type and namespace
- lower-trust experimental workers should never share credentials with core services
- dashboard/browser-facing services should not hold broad write credentials anywhere
