# Object Platform Architecture

This folder defines the container-first architecture for the next version of the project.

The platform is built around:

- `RustFS` as the S3-compatible object plane
- `CouchDB` as the document metadata and control plane
- queue-backed microservices, each running in its own container

The design goal is to make raw SatDump outputs, decoded products, retention policy, and derivative pipelines usable by multiple small project containers without requiring each project to understand local filesystem layouts or fragile path conventions.

## Implementation

The current branch includes a single-host Podman deployment:

- compose stack: [compose.object-platform.yml](../../../compose.object-platform.yml)
- shared base image: [containers/object-platform/Containerfile](../../../containers/object-platform/Containerfile)
- service packages under `src/object_platform_*`
- one-shot bootstrap to provision buckets, databases, count views, and queue topology
- `scripts/deploy_object_platform.py` for SSD setup, verified migration, and boot service generation

Start with the [deployment guide](deployment.md). Single-host credentials and networking
are deliberately simpler than the multi-server privilege design. Archive import and
reconciliation are implemented. Alerts, timelapse, analysis, and the dedicated
observability agent are planned extensions and are not deployed.

## Contents

- [System Overview](system-overview.md)
- [Microservices](microservices.md)
- [Privilege Boundaries](privilege-boundaries.md)
- [Storage Interfaces](storage-interfaces.md)
- [Queueing and Job Semantics](queueing.md)
- [Document Schemas](schemas.md)
- [Retention Policies](retention-policies.md)
- [Deployment Topology](deployment.md)
- [Operations and Lifecycle](operations.md)
- [Validation Record](validation.md)

## Architecture Principles

1. Raw blobs remain authoritative.
2. Metadata and projections are document-shaped and versioned.
3. Containers interact through stable storage and queue interfaces, not shared host scripts.
4. Materialized views are disposable and rebuildable.
5. Retention is split across:
   - object lifecycle policy
   - metadata lifecycle policy
   - derived-output lifecycle policy
6. Every stage is replay-safe and idempotent.
