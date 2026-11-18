# Retention Policies

Retention is not a single feature. The platform needs separate policies for blobs, metadata, and derived outputs.

## Policy Layers

| Layer | Enforced by | Typical target |
| --- | --- | --- |
| Blob retention | RustFS lifecycle + `retention-controller` | canonical source objects and derivative objects |
| Metadata retention | `metadata-retention-controller` | source docs, decoded docs, projections, audit docs |
| Projection retention | `metadata-retention-controller` | disposable materialized views |
| Derived-output retention | project workers + controllers | timelapses, alert bundles, analytical outputs |

## Retention Profile Registry

Profiles should be documents, not hardcoded constants in one service.

Example:

```json
{
  "_id": "retention-profile:emwin-text-180d",
  "type": "retention_profile",
  "doc_version": 1,
  "applies_to": {
    "source_family": "emwin",
    "product_kind": "emwin-text"
  },
  "blob_policy": {
    "bucket": "goes-source",
    "retain_days": 180
  },
  "metadata_policy": {
    "raw_product_days": 187,
    "decoded_product_days": 187,
    "projection_mode": "rebuild"
  }
}
```

## Metadata Lifetimes

Recommended defaults:

| Document type | Retention posture |
| --- | --- |
| `raw_product` | retain slightly longer than blob expiry for reconciliation |
| `decoded_product` | retain same as or slightly longer than `raw_product` |
| `station_view` | disposable; rebuild instead of long-term retention |
| `derived_asset` | retain by project-specific policy |
| `retention_event` | keep long-term for audit |
| `repair_record` | keep medium to long term for operator review |
| health/projection caches | short-lived and replaceable |

## Pinning and Exceptions

Some objects and docs must override broad lifecycle policy.

Support fields such as:

- `pin_reason`
- `legal_hold`
- `event_id`
- `superseded_by`
- `retain_until`
- `delete_after`

Examples:

- severe weather event package pinned indefinitely
- representative imagery pinned for one year
- alert bundle retained while its source blob already expired

## Reconciliation Rules

Controllers must account for these states:

- blob exists, metadata exists
- blob exists, metadata missing
- metadata exists, blob missing
- projection exists, source doc missing
- derived asset exists, lineage incomplete

## Destructive Actions

Deletion should normally be two-step:

1. mark as pending deletion or tombstoned
2. purge after grace period

This is especially important for metadata cleanup, where accidental immediate deletion can make diagnosis harder.
