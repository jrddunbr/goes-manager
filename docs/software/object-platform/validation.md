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

## Python 3.14 update

The application now requires Python 3.14+ and defaults to the official
`python:3.14-slim` image. Revalidation passed all 56 tests on the Arch host's
Python 3.14.9 and inside a newly built Python 3.14.10 application container using
the installed package and pinned runtime dependencies. `pip check` reported no
broken requirements. The pinned native dependencies (Pillow, MarkupSafe, and
charset-normalizer) have Python 3.14 Linux ARM64 wheels compatible with the
Debian 12 target. These checks do not substitute for running the stack on the Pi.

The host deployment script still runs with Python 3.11+ and Podman 4.3.1. It
supplies the newer application runtime through containers. Existing saved
Python-image pins must be updated explicitly, as described in the deployment guide.

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
