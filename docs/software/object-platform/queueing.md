# Queueing and Job Semantics

The platform requires a real execution fabric. Durable metadata in CouchDB is not a substitute for job dispatch, leasing, retries, or dead-letter handling.

RabbitMQ is the default queue broker for this platform because the desired semantics are queue-shaped rather than log-shaped:

- processed items should not accumulate indefinitely
- work items should be acked and removed
- dead-lettering should be explicit
- bounded queue growth matters more than retaining a long event log in the broker

## Current single-host behavior

Primary publications require broker confirmation and mandatory routing. Failed jobs
are republished with a 15-second delay and acknowledged only after the retry or
terminal publication is confirmed. After eight failed attempts they enter the
dead-letter queue with worker, error, and timestamp fields. Invalid JSON is rejected
to the dead-letter exchange. The deployment sets a 256 MiB limit per queue with
`reject-publish`, so an overflowing queue applies backpressure rather than silently
evicting old jobs. Document state plus reconciliation repairs missed follow-up work.

The derivative queues are reserved for future extensions; no placeholder consumers
are deployed. The remaining sections describe the broader architecture and goals.

## Purpose

The queue plane exists to:

- decouple ingest from decode and projection workloads
- provide retries and backpressure
- support replay and backfill
- prevent duplicate work from being executed concurrently
- make worker failure observable instead of silent

## Broker Requirements

Any selected broker should support:

- at-least-once delivery
- explicit acknowledgement
- redelivery after consumer failure or timeout
- delayed retry
- dead-letter routing
- consumer groups or durable subscriptions
- metrics for queue depth and age

Alternative brokers could be used later, but they would need to preserve the same operational model. `Redis Streams` is intentionally not the default because it behaves more like a retained log and requires active trimming discipline to prevent unnecessary disk growth.

## Queue Layout

| Queue | Purpose | Typical payload |
| --- | --- | --- |
| `ingest-jobs` | canonical source ingest | source path, manifest id, trace id |
| `decode-jobs` | decode supported products | `raw_product_id`, decoder family |
| `materialize-jobs` | rebuild projections | source doc ids, projection family |
| `derivative-jobs` | create project outputs | project name, lineage ids, template |
| `reconcile-jobs` | state consistency checks | scope, object/doc refs |
| `retention-jobs` | lifecycle reconciliation | retention profile, target refs |
| `replay-jobs` | historical reprocessing | replay class, selector |
| `dead-letter` | failed work | original envelope + failure context |

Recommended RabbitMQ features in use:

- dead-letter exchanges for all primary queues
- TTL or bounded retry queues for delayed retry
- per-queue max length or byte policy where useful
- lazy queues only if memory pressure requires them
- quorum queues if higher durability is needed

## Job Envelope

Every queue message should use a standard envelope.

```json
{
  "job_id": "ingest:sha256:abc123",
  "job_type": "ingest-source-file",
  "trace_id": "trace-20260524-0001",
  "attempt": 1,
  "created_at": "2026-05-24T20:00:00Z",
  "payload": {
    "source_path": "/ingest/EMWIN/A_FTUS80....txt",
    "source_family": "emwin"
  }
}
```

## Idempotency Rules

- `job_id` should be deterministic when possible.
- Consumers must tolerate duplicate deliveries.
- Any write side effect must be guarded by canonical identity:
  - object key + checksum
  - target document id
  - projection version
- Requeued jobs must not produce duplicate source objects or duplicate logical derivatives.

## Retry Policy

Recommended job handling:

- transient failure: requeue with backoff
- persistent parser failure: dead-letter after threshold
- dependency missing: delayed retry
- poisoned payload: dead-letter immediately with validation reason

Suggested attempt classes:

- `0-3`: short exponential backoff
- `4-8`: longer delayed retries
- `>8`: dead-letter unless operator explicitly replays

Suggested implementation:

- primary queue
- retry queue with TTL
- dead-letter exchange

The scaffold implements this with:

- `<queue>` as the primary durable queue
- `<queue>.retry` as the delayed retry queue
- `dead-letter` as the terminal operator-visible queue

The worker republishes failed jobs to the retry or dead-letter exchange and acknowledges the original only after the broker confirms the replacement.

## Dead-Letter Handling

The dead-letter queue is not a trash can. It is an operator-visible backlog of unresolved failures.

Each dead-letter entry should include:

- original message envelope
- worker identity
- failure class
- last error string
- timestamps of each attempt
- replay recommendation

## Replay Semantics

Replay jobs must be first-class rather than ad hoc scripts.

Examples:

- replay ingest for a date range
- redecode all `TAFALLUS` products with `decoder_version=v2`
- rebuild all `station_view` documents
- regenerate timelapses for one satellite/band/window

## Queue Retention and Disk Control

Queue storage must be bounded. RabbitMQ should not become a long-term system of record.

Controls to set:

- queue TTL where appropriate
- max queue length or max queue bytes
- dead-letter retention policy
- alerting on queue growth and oldest-message age

Durable history belongs in CouchDB, not in RabbitMQ.

## Observability

Track:

- queue depth by queue
- oldest message age by queue
- retry rate by job type
- dead-letter rate by worker and payload family
- consumer timeout or redelivery count
- replay throughput
