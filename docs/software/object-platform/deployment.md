# Single Raspberry Pi deployment with Podman

This deployment targets **64-bit Raspberry Pi OS / Debian 12 with Podman 4.3.1**,
an SSD, and Python 3.11+ on the host for the deployment script. Application
packages and containers target Python 3.14; the Pi's OS Python can remain unchanged.
Arch with newer Podman can run the same deployment for testing. Install `podman` and `podman-compose` (not Docker Compose). The script
uses explicit health polling rather than newer Compose `up --wait` features.
Rootless Podman must work for the account that owns the deployment; check
`podman info` before starting. All image names include their registry.

## Storage layout

Example:

```
/mnt/ssd/                         # mounted SSD
  satellite_raw/                 # existing SatDump output, preserved
    EMWIN/
    IMAGES/
    ...
  goes-platform/                 # dedicated new directory
    rustfs/
    rustfs-logs/
    couchdb/
    rabbitmq/
    migration/latest.json
    migration/latest.errors.jsonl
    goes-object-platform.service
```

`--source` can be any existing data-only tree, including an archive containing
multiple product families and subdirectories. Every regular file is imported,
including binary imagery, text, compressed files, and metadata. Symlinks are
excluded; directories are traversed without following links. If several existing
directories need importing, select their common **data-only** parent. The object
key is the relative path under this root; keep the root stable on future runs.

Source and platform directories must be separate and cannot contain one another.
The SSD mount must exist. By default its mount point is the parent of `--data-dir`;
pass `--ssd-mount /mnt/ssd` if the platform directory is nested more deeply. An
unmounted SSD is a hard error, preventing accidental writes to the Pi's SD card.
The source remains mounted read-only. Only dedicated storage subdirectories use
Podman's `:U` ownership adjustment; source ownership is never changed.

Make the source readable by the deployment user. On SELinux hosts, configure
container access to these paths before deployment; the script does not relabel
an existing archive automatically.

## Preflight and deployment

From the repository, first run a read-only preflight:

```bash
python3 scripts/deploy_object_platform.py \
  --source /mnt/ssd/satellite_raw \
  --data-dir /mnt/ssd/goes-platform \
  --plan
```

The initial space estimate is source bytes plus 15% and 1 GiB of headroom. Metadata,
container images, and ongoing arrivals need additional space. Original files and
object copies coexist throughout migration. Container image storage follows
Podman's configuration; place its graphroot on the SSD as well if SD card space
is limited.

Deploy and import:

```bash
python3 scripts/deploy_object_platform.py \
  --source /mnt/ssd/satellite_raw \
  --data-dir /mnt/ssd/goes-platform
```

The script:

1. Checks paths, mount, available space, and required commands; takes a deployment lock.
2. Creates private `.env.object-platform` credentials once and preserves them on reruns.
3. Pulls infrastructure images and saves registry digests; builds the application
   image using pinned runtime dependencies.
4. Stops existing platform workers and controllers, starts the three stores,
   waits for health, and bootstraps databases, buckets, queue topology, and count views.
5. Imports files sequentially, records catalog metadata, reads each object back
   and checks its SHA-256 and size, then decodes supported EMWIN text and builds projections.
6. Starts live ingest, APIs, reconciliation, replay, and the existing filesystem dashboard.
   Writes a boot service for installation below.

Run this from a persistent terminal such as `tmux` for a large migration. Quiesce
legacy retention jobs during the import so they do not move or remove originals.
SatDump can continue writing; files changed during import fail verification and
are retried on the next run. For a clean complete archive report, pause source
writes during the final pass.

A failed import exits nonzero and leaves workers stopped with deletion disabled.
Fix the reported errors and rerun the same command. Already-indexed objects are
not uploaded again; every file is verified again. `migration/latest.json` contains
counts and bytes, and `latest.errors.jsonl` lists per-file errors. A successful
migration has `complete: true`, `failed: 0`, and `verified == files`. These reports describe the
files observed in that pass, not a filesystem snapshot. Source files are never
removed. Objects previously deleted by explicit retention require an intentional
restore policy; the importer does not silently resurrect them.

`--skip-migration` starts live ingest without the verified archive pass. It still
scans existing source files. Use the default migration for initial deployment.
The lock prevents two deployment scripts for the same data directory from running
at once; run only one platform stack against each source/store pair.

## Access and single-host privileges

The web dashboard is `http://127.0.0.1:18094`. It reads the same `/ingest` source
root as the uploader, preserving the existing browser UI during migration.
`http://127.0.0.1:18090/api/summary` exposes the new object-platform JSON summary.
They are separate interfaces; the old UI still requires the source filesystem.

Use `--dashboard-bind 0.0.0.0` to expose these interfaces to your LAN. They do not
implement user authentication. Use the existing reverse proxy for public access.

All services share one private bridge network and the same installation credentials
inside this single-host trust boundary. RustFS (`9000`), CouchDB (`5984`), and
RabbitMQ's management UI (`15672`) bind only to localhost; AMQP and worker health
ports are not published. This intentionally simplifies the multi-server design
in [Privilege Boundaries](privilege-boundaries.md). A multi-server deployment
still needs separate identities, network policy, TLS, and secret distribution.
Secrets remain outside images. Infrastructure runs under its image-specific user
inside rootless Podman. CouchDB uses single-node configuration and one shard replica.

The built image contains only package sources and required build inputs, excluding
satellite data, `.env`, virtualenvs, and Git metadata. Runtime package versions are
in `requirements.object-platform.lock`. Keep `.env.object-platform` backed up
securely; losing it can prevent access to existing stores.

## Retention and optional features

Automatic deletion is disabled by default. Migration starts retention clocks at
import time, retaining historical material for a full configured period instead
of immediately expiring old files. Source mtime is recorded separately for ordering.

After reviewing migration results, rerun with `--enable-retention` to enable both
controllers. This affects objects and metadata, never the source directory.
Defaults are 180 days for EMWIN text, 90 days for graphics, 400 days for CBOR, and
180 days for other files, followed by a seven-day cushion and a one-day deletion
grace. Metadata remains for seven days after object deletion. Pins and legal holds
are respected. Customize `retention_profile` documents in CouchDB's `control`
database before new uploads; existing object deadlines are retained. Profile
seeding preserves operator edits.

Reconciliation and replay execute real recovery work. Alerts, timelapse, analysis,
and the separate observability agent remain planned extensions: they are absent
from this deployment and fail explicitly if invoked. They do not consume and
acknowledge jobs while pretending to create outputs. The synthetic seeder is only
in the `development` profile and writes to a separate test-data directory.

## Start at boot

The deployment writes `/mnt/ssd/goes-platform/goes-object-platform.service`.
Install it under the same user who ran the deployment:

```bash
mkdir -p ~/.config/systemd/user
cp /mnt/ssd/goes-platform/goes-object-platform.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now goes-object-platform.service
sudo loginctl enable-linger "$USER"
```

Configure the SSD mount in the host's `/etc/fstab`. The generated unit checks that
the SSD is mounted before startup. It starts the existing stack without rerunning
migration. Infrastructure and workers restart after process failures; the user
service starts them again after a reboot.

## Operations and rollback

From the repository, use the saved environment:

```bash
podman-compose --in-pod false --env-file .env.object-platform -p goes-object-platform \
  -f compose.object-platform.yml ps
podman-compose --in-pod false --env-file .env.object-platform -p goes-object-platform \
  -f compose.object-platform.yml logs --tail 100
```

Stop the generated systemd service, or use the same Compose command with `stop`,
to return to the original filesystem services. Do not delete store directories
or reset credentials. Original source data is retained. Quiesce the stack before
backing up the dedicated SSD data directory, credentials, and deployment files;
file copies of live databases are not a consistent backup.

The application defaults to `docker.io/library/python:3.14-slim`. For an existing
installation whose `.env.object-platform` pins a Python 3.13 image, change
`PYTHON_IMAGE` to `docker.io/library/python:3.14-slim` before redeploying. Saved
pins are preserved until explicitly changed. The rebuilt containers use Python
3.14 without changing the host interpreter.

The deployment pins image digests on first use. Image upgrades are intentional:
back up stores, edit the corresponding image setting in `.env.object-platform`,
then rerun deployment. The script preserves the saved source and store locations
and refuses an accidental path switch.

References: [Podman Compose provider](https://docs.podman.io/en/v4.3/markdown/podman-compose.1.html),
[CouchDB single-node setup](https://docs.couchdb.org/en/stable/setup/single-node.html),
[RustFS volume permissions](https://docs.rustfs.com/en/installation/container/docker),
[RabbitMQ publishing guarantees](https://www.rabbitmq.com/docs/publishers).
