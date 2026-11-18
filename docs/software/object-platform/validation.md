# Validation record

Validated on 2026-11-17 using Arch Linux, Podman 6.1.4, podman-compose 1.6.0,
and the Python 3.13 application image. The target Pi runs Podman 4.3.1; testing
on that host remains necessary before calling the deployment verified there.
The script avoids newer Compose wait features and supports both Podman health
inspection field names. The pinned RustFS 1.0.5 image index includes Linux ARM64.

- Built the application image with pinned Python dependencies.
- Started RustFS 1.0.5, CouchDB 3.5.0, and RabbitMQ 4.2.0 in an isolated Podman
  project with temporary storage and no published host ports.
- Bootstrapped buckets, databases, count views, and queue topology.
- Imported two EMWIN text products and one nested binary file; read back and
  verified all three objects, decoded text, and materialized two station views.
- Repeated the import with zero reuploads and zero verification failures.
- Added a third EMWIN product through the live watcher and confirmed upload,
  decode, projection, and API totals of four products and three stations.
- Reverified all four source files with zero failures using the final importer.
- Validated the final Compose configuration with the script's provider options.
- Removed isolated test containers and networking after validation; temporary
  reports and pulled images were retained.

The unit suite covers import resume, readback failure reporting, path confinement,
symlink exclusion, recovery of missing jobs and metadata, retention holds, profile
preservation, pagination during deletion, queue confirmation/acknowledgement order,
SSD mount refusal, deployment ordering and failure behavior, and credential reuse.

Run it from the checkout with:

```bash
PYTHONPATH=src python3 -m pytest -q
```

The four dashboard failures present in committed HEAD were resolved by using the
existing unified text analyzer in the file parser and correcting obsolete test
expectations, including the polygon coordinate mean of -87.923 degrees.

No production migration, source deletion, remote Git update, or Pi deployment was
performed during these tests. Follow the deployment guide to import the actual
SSD source tree and retain the resulting complete verification report.
