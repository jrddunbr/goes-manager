# Operations and Lifecycle

## Current single-host implementation

See [deployment and migration](deployment.md) for executable commands and the supported
service set. Automatic deletion is opt-in. Import is synchronous and verified; ongoing
processing uses confirmed RabbitMQ publishing and durable document state to recover
missing follow-up jobs. Reconciliation retries incomplete decode/projection work and
restores missing objects from the source when available, and recovers catalog records
for source-bucket objects left behind by interrupted uploads. It does not recover SatDump
data that never arrived. Object/metadata scans paginate instead of stopping at 10,000.

The sections below describe both current contracts and future operational goals.
Planned derivative and dedicated observability services are not deployed.

## Idempotency

Every stage must be safe to replay.

### Required Rules

- uploads are keyed deterministically
- `raw_product` upserts are based on canonical identity
- decoder jobs may run multiple times without duplicating equivalent state
- projections overwrite by deterministic target identity
- derivative assets use stable logical IDs where appropriate

## Replay and Backfill

Backfill does not recover data SatDump never received. It recovers work the platform did not complete or work that must be rerun after logic changes.

### Supported Replay Classes

- ingest replay
- decode replay
- projection rebuild
- derivative regeneration
- retention policy reapplication
- RustFS/CouchDB reconciliation sweep

### Example Control Jobs

- `replay-ingest`
- `redecode-products`
- `rebuild-projections`
- `regenerate-derivatives`
- `reconcile-storage`
- `reapply-retention-policy`

## Retention Responsibilities

### Blob Retention

Handled primarily by:

- RustFS lifecycle policy
- `retention-controller`

### Metadata Retention

Handled by:

- `metadata-retention-controller`

It must distinguish:

- authoritative product docs
- disposable projections
- long-lived audit/control docs

### Derived Retention

Each project bucket and `derived_asset` family needs its own profile.

See also:

- [Retention Policies](retention-policies.md)
- [Queueing and Job Semantics](queueing.md)
- [Deployment Topology](deployment.md)

## Failure Modes

### Object uploaded, doc missing

- detected by `reconciler`
- repaired by writing missing `raw_product` or flagging the object as orphaned

### Doc exists, object missing

- mark affected docs as orphaned
- suppress dependent work
- optionally requeue upload if source file still exists

### Decode failed

- write structured decode failure state
- retry through queue policy
- dead-letter after threshold

### Projection stale

- requeue materialization
- projections are disposable and may be rebuilt

## SLO-Oriented Metrics

Track at least:

- ingest lag from SatDump write to `raw_product`
- object upload success rate
- decode failure rate by decoder family
- queue depth by queue
- projection freshness age
- orphaned object/doc count
- retention drift count
- replay backlog size
