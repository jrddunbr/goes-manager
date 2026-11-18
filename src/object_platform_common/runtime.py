"""Shared service runtime."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import logging
import os
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from goes_dashboard.service import load_airport_index, parse_product
from .config import PlatformConfig
from .couchdb import CouchDBClient
from .health import build_health_app
from .queue import JobEnvelope, RabbitQueueClient, queue_name_for_role
from .storage import RustFSClient, build_source_object_key, sha256_file

logger = logging.getLogger(__name__)
UTC = timezone.utc


@lru_cache(maxsize=1)
def airport_index():
    return load_airport_index()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def source_family_for_path(path: Path) -> str:
    suffix = path.suffix.lstrip(".").lower()
    if any(part.upper().startswith("GOES-") for part in path.parts) and suffix in {"png", "jpg", "jpeg", "gif"}:
        return "goes-imagery"
    if suffix in {"txt", "text"}:
        return "emwin-text"
    if suffix in {"gif", "jpg", "jpeg", "png"}:
        return "emwin-graphic"
    if suffix == "cbor":
        return "metadata"
    return suffix or "unknown"


def retention_for_source_family(source_family: str, created_at: datetime) -> dict[str, object]:
    retention_days = {
        "emwin-text": 180,
        "emwin-graphic": 90,
        "metadata": 400,
    }.get(source_family, 180)
    retain_until = created_at + timedelta(days=retention_days)
    delete_after = retain_until + timedelta(days=7)
    return {
        "profile": f"{source_family}-{retention_days}d",
        "retain_until": retain_until.isoformat(),
        "delete_after": delete_after.isoformat(),
        "pin_reason": None,
        "status": "active",
    }


def is_decode_supported(source_family: str, key: str) -> bool:
    suffix = Path(key).suffix.lower()
    return source_family == "emwin-text" and suffix in {".txt", ".text"}


def source_file_matches_catalog(config: PlatformConfig, couch: CouchDBClient, path: Path, file_size: int) -> bool:
    key = build_source_object_key(config.input_root, path)
    existing = couch.get_document(f"raw:{key}")
    if existing is None:
        return False
    fingerprint = existing.get("fingerprint")
    if not isinstance(fingerprint, dict) or fingerprint.get("size") != file_size:
        return False
    return (
        fingerprint.get("sha256") == sha256_file(path)
        and existing.get("decode", {}).get("status") in {"decoded", "unsupported", "parse_failed"}
        and existing.get("retention", {}).get("status") != "deleted"
    )


def start_health_server(config: PlatformConfig) -> threading.Thread:
    app = build_health_app(config.service_name, config.role, config)
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=config.health_port, debug=False, use_reloader=False),
        name=f"{config.service_name}-health",
        daemon=True,
    )
    thread.start()
    return thread


def build_job(job_type: str, payload: dict[str, object]) -> JobEnvelope:
    job_id = f"{job_type}:{payload.get('path') or payload.get('raw_product_id') or payload.get('decoded_product_id') or payload.get('selector') or utc_now_iso()}"
    return JobEnvelope(
        job_id=job_id,
        job_type=job_type,
        trace_id=f"trace-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        attempt=1,
        payload=payload,
        created_at=utc_now_iso(),
    )


def enqueue_scan_results(config: PlatformConfig) -> int:
    queue = RabbitQueueClient(config.rabbitmq_url)
    queue.declare_standard_queues()
    count = 0
    for path in iter_source_files(config.input_root):
        if not path.is_file():
            continue
        envelope = build_job("ingest-source-file", {"path": str(path)})
        queue.publish("ingest-jobs", envelope)
        count += 1
    logger.info("Enqueued %s ingest jobs from %s", count, config.input_root)
    return count


def iter_source_files(root: Path):
    """Stream a tree without following links or buffering an entire archive."""
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
        for name in names:
            path = Path(directory) / name
            if not path.is_symlink() and path.is_file():
                yield path


def run_ingest_watch_loop(config: PlatformConfig) -> None:
    queue = RabbitQueueClient(config.rabbitmq_url)
    queue.declare_standard_queues()
    couch = CouchDBClient(config.couchdb_url, "catalog")
    seen: dict[str, tuple[int, int]] = {}
    candidates: dict[str, tuple[int, int]] = {}
    while True:
        current = {}
        for path in iter_source_files(config.input_root):
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                key = str(path)
                current[key] = signature
                # Require two observations before publishing a file SatDump may be writing.
                if seen.get(key) == signature or candidates.get(key) != signature:
                    continue
                if not source_file_matches_catalog(config, couch, path, stat.st_size):
                    queue.publish("ingest-jobs", build_job("ingest-source-file", {
                        "path": key, "source_family": source_family_for_path(path),
                        "first_seen_at": utc_now_iso(),
                    }))
                # Only mark seen after a confirmed publication or catalog match.
                seen[key] = signature
            except FileNotFoundError:
                continue
        seen = {key: value for key, value in seen.items() if key in current}
        candidates = current
        time.sleep(config.scan_interval_seconds)


def publish_followup(config: PlatformConfig, document: dict) -> None:
    """Durable document state is the outbox; reconciliation retries unfinished work."""
    decode = document.get("decode", {})
    queue = RabbitQueueClient(config.rabbitmq_url)
    try:
        if decode.get("status") == "queued":
            queue.publish("decode-jobs", build_job("decode-product", {
                "raw_product_id": document["_id"], "key": document["object_store"]["key"],
            }))
        elif decode.get("status") == "decoded":
            decoded_id = decode["decoded_product_id"]
            decoded = CouchDBClient(config.couchdb_url, "catalog").get_document(decoded_id)
            if decoded and decoded.get("projection_status") != "complete":
                queue.publish("materialize-jobs", build_job("materialize-projection", {
                    "decoded_product_id": decoded_id,
                }))
    finally:
        queue.close()


def process_upload_job(config: PlatformConfig, payload: dict[str, object]) -> None:
    path = Path(str(payload["path"]))
    if path.is_symlink():
        raise ValueError("Symbolic links are not ingest sources")
    path.resolve().relative_to(config.input_root.resolve())
    before = path.stat()
    rustfs = RustFSClient(config.rustfs_endpoint, config.rustfs_access_key, config.rustfs_secret_key)
    couch = CouchDBClient(config.couchdb_url, "catalog")
    key = build_source_object_key(config.input_root, path)
    doc_id = f"raw:{key}"
    file_size = path.stat().st_size
    file_sha256 = sha256_file(path)
    existing = couch.get_document(doc_id)
    same_content = False
    if existing is not None:
        fingerprint = existing.get("fingerprint")
        same_content = isinstance(fingerprint, dict) and fingerprint.get("sha256") == file_sha256 and fingerprint.get("size") == file_size
        if same_content:
            object_store = existing.get("object_store", {})
            if existing.get("retention", {}).get("status") == "deleted":
                return
            if not payload.get("force") and rustfs.object_exists(str(object_store.get("bucket", config.source_bucket)), key):
                if payload.get("dispatch", True):
                    publish_followup(config, existing)
                return
    created_at = datetime.now(UTC)
    source_family = str(payload.get("source_family") or source_family_for_path(path))
    profile_id = str(retention_for_source_family(source_family, created_at)["profile"])
    profile = CouchDBClient(config.couchdb_url, "control").get_document(f"retention-profile:{profile_id}")
    retention = retention_for_source_family(source_family, created_at)
    if profile:
        days = int(profile.get("blob_policy", {}).get("retain_days", 180))
        retention["retain_until"] = (created_at + timedelta(days=days)).isoformat()
        retention["delete_after"] = (created_at + timedelta(days=days + 7)).isoformat()
    object_meta = rustfs.put_object(config.source_bucket, key, path, checksum=file_sha256)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"Source changed during upload: {path}")
    document = {
        "_id": doc_id,
        "type": "raw_product",
        "doc_version": 1,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "source_system": "satdump",
        "source_family": source_family,
        "source_path": str(path),
        "source_time": datetime.fromtimestamp(before.st_mtime, UTC).isoformat(),
        "fingerprint": {
            "sha256": file_sha256,
            "size": file_size,
        },
        "object_store": object_meta,
        "ingest": {
            "status": "indexed",
            "first_seen_at": payload.get("first_seen_at") or utc_now_iso(),
            "indexed_at": utc_now_iso(),
            "uploader_version": "ingest-uploader/0.1.0",
        },
        "decode": {
            "status": "queued" if is_decode_supported(source_family, key) else "unsupported",
            "reason": None if is_decode_supported(source_family, key) else "no decoder registered for source family",
        },
        "retention": retention,
    }
    if existing:
        # Pins and holds survive both object repair and updates at the same logical path.
        if same_content:
            document.update(created_at=existing.get("created_at", document["created_at"]),
                            retention=existing.get("retention", document["retention"]),
                            decode=existing.get("decode", document["decode"]))
        else:
            for field in ("pin_reason", "legal_hold"):
                if existing.get("retention", {}).get(field):
                    document["retention"][field] = existing["retention"][field]
    couch.upsert_document(doc_id, document)
    if payload.get("dispatch", True):
        publish_followup(config, document)


def process_decode_job(config: PlatformConfig, payload: dict[str, object]) -> None:
    couch = CouchDBClient(config.couchdb_url, "catalog")
    raw_product_id = str(payload["raw_product_id"])
    raw_product = couch.get_document(raw_product_id)
    if raw_product is None:
        raise RuntimeError(f"Missing raw_product {raw_product_id}")
    object_store = raw_product.get("object_store") or {}
    bucket = str(object_store.get("bucket") or config.source_bucket)
    key = str(object_store.get("key") or payload.get("key") or "")
    if not key:
        raise RuntimeError(f"Missing object key for {raw_product_id}")
    source_family = str(raw_product.get("source_family") or "")
    if not is_decode_supported(source_family, key):
        raw_product["decode"] = {
            "status": "unsupported",
            "updated_at": utc_now_iso(),
            "reason": f"no decoder registered for source_family={source_family} key={key}",
        }
        raw_product["updated_at"] = utc_now_iso()
        couch.upsert_document(raw_product_id, raw_product)
        logger.info("Skipping unsupported decode for %s", raw_product_id)
        return

    rustfs = RustFSClient(config.rustfs_endpoint, config.rustfs_access_key, config.rustfs_secret_key)
    with TemporaryDirectory() as td:
        root = Path(td)
        product_path = root / Path(key)
        product_path.resolve().relative_to(root.resolve())
        product_path.parent.mkdir(parents=True, exist_ok=True)
        product_path.write_bytes(rustfs.get_object_bytes(bucket, key))
        parsed = parse_product(product_path, airport_index(), root)
    if parsed is None:
        raw_product["decode"] = {
            "status": "parse_failed",
            "updated_at": utc_now_iso(),
            "reason": "EMWIN parser returned no product",
        }
        raw_product["updated_at"] = utc_now_iso()
        couch.upsert_document(raw_product_id, raw_product)
        logger.info("Parser did not recognize %s; marked parse_failed", raw_product_id)
        return

    decoded_doc_id = f"decoded:{raw_product_id}:emwin-v1"
    document = {
        "_id": decoded_doc_id,
        "type": "decoded_product",
        "doc_version": 1,
        "raw_product_id": raw_product_id,
        "decoder_family": "emwin",
        "decoder_version": "v1",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "title": parsed.title,
        "summary": parsed.summary,
        "product_type": parsed.product_type,
        "station_codes": list(parsed.station_codes),
        "detail_sections": [{"label": label, "value": value} for label, value in parsed.detail_sections],
        "related_reports": [
            {"code": code, "summary": summary, "plain": plain}
            for code, summary, plain in parsed.related_reports
        ],
        "materialized_for": ["dashboard"],
        "lineage": {"derived_from": [raw_product_id]},
        "source_sha256": raw_product.get("fingerprint", {}).get("sha256"),
        "source_time": raw_product.get("source_time") or raw_product.get("created_at"),
        "projection_status": "pending",
    }
    couch.upsert_document(decoded_doc_id, document)
    raw_product["decode"] = {
        "status": "decoded",
        "updated_at": utc_now_iso(),
        "decoded_product_id": decoded_doc_id,
    }
    raw_product["updated_at"] = utc_now_iso()
    couch.upsert_document(raw_product_id, raw_product)
    if not payload.get("dispatch", True):
        return
    queue = RabbitQueueClient(config.rabbitmq_url)
    try:
        queue.publish("materialize-jobs", build_job("materialize-projection", {"decoded_product_id": decoded_doc_id}))
    finally:
        queue.close()


def process_materialize_job(config: PlatformConfig, payload: dict[str, object]) -> None:
    decoded_id = str(payload["decoded_product_id"])
    catalog = CouchDBClient(config.couchdb_url, "catalog")
    projections = CouchDBClient(config.couchdb_url, "projections")
    decoded = catalog.get_document(decoded_id)
    if decoded is None:
        raise RuntimeError(f"Missing decoded_product {decoded_id}")

    station_codes = decoded.get("station_codes") or []
    if not station_codes:
        station_codes = ["UNSPECIFIED"]
    for station_code in station_codes:
        station_doc_id = f"station:{station_code}:v1"
        existing = projections.get_document(station_doc_id)
        source_time = decoded.get("source_time") or decoded.get("created_at") or ""
        if existing and str(existing.get("source_time", "")) > str(source_time):
            continue
        document = {
            "_id": station_doc_id,
            "type": "station_view",
            "doc_version": 1,
            "projection_version": "v1",
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "station_code": station_code,
            "source_time": source_time,
            "latest_products": [decoded.get("raw_product_id"), decoded_id],
            "weather_summary": {
                "headline": decoded.get("title"),
                "summary": decoded.get("summary"),
            },
            "source_docs": [decoded_id],
            "rebuildable": True,
        }
        projections.upsert_document(station_doc_id, document)
    decoded["projection_status"] = "complete"
    catalog.upsert_document(decoded_id, decoded)


def seed_retention_profiles(config: PlatformConfig) -> None:
    control = CouchDBClient(config.couchdb_url, "control")
    profiles = [
        ("emwin-text-180d", "emwin-text", 180),
        ("emwin-graphic-90d", "emwin-graphic", 90),
        ("metadata-400d", "metadata", 400),
    ]
    for profile_id, source_family, retain_days in profiles:
        control.create_document(
            f"retention-profile:{profile_id}",
            {
                "_id": f"retention-profile:{profile_id}",
                "type": "retention_profile",
                "doc_version": 1,
                "updated_at": utc_now_iso(),
                "applies_to": {"source_family": source_family},
                "blob_policy": {"bucket": config.source_bucket, "retain_days": retain_days},
                "metadata_policy": {"raw_product_days": retain_days + 7, "decoded_product_days": retain_days + 7},
            },
        )


def write_retention_event(
    config: PlatformConfig,
    target_doc_id: str,
    action: str,
    status: str,
    detail: str = "",
) -> None:
    control = CouchDBClient(config.couchdb_url, "control")
    now = utc_now_iso()
    event_id = f"retention:{now}:{target_doc_id}".replace("/", "_")
    control.upsert_document(
        event_id,
        {
            "_id": event_id,
            "type": "retention_event",
            "doc_version": 1,
            "created_at": now,
            "updated_at": now,
            "target_doc_id": target_doc_id,
            "action": action,
            "status": status,
            "detail": detail,
        },
    )


def process_retention_scan(config: PlatformConfig, payload: dict[str, object] | None = None) -> int:
    seed_retention_profiles(config)
    if not config.retention_enabled:
        return 0
    catalog = CouchDBClient(config.couchdb_url, "catalog")
    rustfs = RustFSClient(config.rustfs_endpoint, config.rustfs_access_key, config.rustfs_secret_key)
    now = datetime.now(UTC)
    processed = 0
    for document in catalog.iter_documents():
        doc_id = str(document.get("_id") or "")
        if document.get("type") not in {"raw_product", "derived_asset"}:
            continue
        retention = dict(document.get("retention") or {})
        if retention.get("pin_reason") or retention.get("legal_hold"):
            continue
        delete_after = parse_iso_datetime(retention.get("delete_after"))
        if delete_after is None or delete_after > now:
            continue

        object_store = document.get("object_store") or {}
        bucket = str(object_store.get("bucket") or "")
        key = str(object_store.get("key") or "")
        if not bucket or not key:
            continue

        status = str(retention.get("status") or "active")
        pending_at = parse_iso_datetime(retention.get("pending_delete_at"))
        if status == "deleted":
            continue
        if status != "pending_delete" or pending_at is None:
            retention["status"] = "pending_delete"
            retention["pending_delete_at"] = utc_now_iso()
            document["retention"] = retention
            document["updated_at"] = utc_now_iso()
            catalog.upsert_document(doc_id, document)
            write_retention_event(config, doc_id, "mark-pending-delete", "pending")
            processed += 1
            continue

        if pending_at is not None and now - pending_at < timedelta(seconds=config.retention_grace_seconds):
            continue

        rustfs.delete_object(bucket, key)
        retention["status"] = "deleted"
        retention["deleted_at"] = utc_now_iso()
        document["retention"] = retention
        document["updated_at"] = utc_now_iso()
        catalog.upsert_document(doc_id, document)
        write_retention_event(config, doc_id, "delete-object", "complete")
        processed += 1
    logger.info("Retention scan processed %s expired objects", processed)
    return processed


def process_metadata_retention_scan(config: PlatformConfig, payload: dict[str, object] | None = None) -> int:
    if not config.retention_enabled:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=int((payload or {}).get("metadata_retention_days", config.metadata_retention_days)))
    processed = 0
    for database in ["catalog", "projections", "operations"]:
        couch = CouchDBClient(config.couchdb_url, database)
        for document in couch.iter_documents():
            doc_id = str(document.get("_id") or "")
            doc_type = str(document.get("type") or "")
            if doc_type in {"retention_event", "repair_record", "retention_profile"}:
                continue
            retention = dict(document.get("retention") or {})
            if retention.get("pin_reason") or retention.get("legal_hold"):
                continue
            updated_at = parse_iso_datetime(document.get("updated_at") or document.get("created_at"))
            deleted_at = parse_iso_datetime(retention.get("deleted_at"))
            if doc_type == "decoded_product":
                parent = couch.get_document(str(document.get("raw_product_id", "")))
                if parent and (parent.get("retention", {}).get("pin_reason") or parent.get("retention", {}).get("legal_hold")):
                    continue
                if parent:
                    deleted_at = parse_iso_datetime(parent.get("retention", {}).get("deleted_at"))
                elif updated_at and updated_at < cutoff:
                    deleted_at = updated_at
            if deleted_at and deleted_at < cutoff:
                couch.delete_document(doc_id)
                write_retention_event(config, doc_id, "purge-metadata", "complete", detail=f"database={database}")
                processed += 1
            elif doc_type == "station_view" and updated_at and updated_at < cutoff:
                couch.delete_document(doc_id)
                write_retention_event(config, doc_id, "purge-projection", "complete", detail=f"database={database}")
                processed += 1
    logger.info("Metadata retention scan purged %s documents", processed)
    return processed


def process_reconcile_scan(config: PlatformConfig, payload: dict | None = None) -> int:
    catalog = CouchDBClient(config.couchdb_url, "catalog")
    storage = RustFSClient(config.rustfs_endpoint, config.rustfs_access_key, config.rustfs_secret_key)
    repaired = 0
    for document in catalog.iter_documents():
        if document.get("type") != "raw_product" or document.get("retention", {}).get("status") in {"deleted", "pending_delete"}:
            continue
        location = document.get("object_store", {})
        key = str(location.get("key", ""))
        if not key:
            continue
        if not storage.object_exists(str(location.get("bucket", config.source_bucket)), key):
            path = config.input_root / key
            path.resolve().relative_to(config.input_root.resolve())
            if path.is_file() and not path.is_symlink():
                process_upload_job(config, {"path": str(path)})
                repaired += 1
            else:
                document.setdefault("ingest", {})["status"] = "orphaned"
                catalog.upsert_document(document["_id"], document)
                logger.error("Missing object and source for %s", document["_id"])
            continue
        if document.get("ingest", {}).get("status") == "orphaned":
            document["ingest"]["status"] = "indexed"
            catalog.upsert_document(document["_id"], document)
        publish_followup(config, document)
    # An interrupted upload may have left a blob without a catalog document.
    for item in storage.iter_objects(config.source_bucket):
        key = item["Key"]
        doc_id = f"raw:{key}"
        if catalog.get_document(doc_id):
            continue
        path = config.input_root / key
        path.resolve().relative_to(config.input_root.resolve())
        if path.is_file() and not path.is_symlink():
            process_upload_job(config, {"path": str(path)})
        else:
            head = storage.head_object(config.source_bucket, key)
            source_family = source_family_for_path(Path(key))
            now = utc_now_iso()
            document = {
                "_id": doc_id, "type": "raw_product", "doc_version": 1,
                "created_at": now, "updated_at": now, "source_time": item["LastModified"].isoformat(),
                "source_system": "satdump", "source_family": source_family,
                "source_path": str(path), "fingerprint": {
                    "size": head["ContentLength"], "sha256": head.get("Metadata", {}).get("sha256"),
                },
                "object_store": {"bucket": config.source_bucket, "key": key, "size": head["ContentLength"]},
                "ingest": {"status": "indexed", "recovered_at": now},
                "decode": {"status": "queued" if is_decode_supported(source_family, key) else "unsupported"},
                "retention": retention_for_source_family(source_family, datetime.now(UTC)),
            }
            catalog.create_document(doc_id, document)
            publish_followup(config, document)
        write_retention_event(config, doc_id, "repair-missing-metadata", "complete")
        repaired += 1
    return repaired


def process_replay(config: PlatformConfig, payload: dict) -> int:
    """Replay selected catalog work; migrations use the synchronous importer."""
    action = payload.get("action", "decode")
    if action not in {"decode", "materialize", "reconcile"}:
        raise ValueError("Replay action must be decode, materialize, or reconcile")
    if action == "reconcile":
        return process_reconcile_scan(config)
    catalog = CouchDBClient(config.couchdb_url, "catalog")
    count = 0
    for document in catalog.iter_documents():
        if payload.get("raw_product_id") and document.get("raw_product_id", document["_id"]) != payload["raw_product_id"]:
            continue
        if action == "decode" and document.get("type") == "raw_product" and document.get("retention", {}).get("status") == "active":
            if is_decode_supported(str(document.get("source_family", "")), str(document.get("object_store", {}).get("key", ""))):
                process_decode_job(config, {"raw_product_id": document["_id"]})
                count += 1
        elif action == "materialize" and document.get("type") == "decoded_product":
            process_materialize_job(config, {"decoded_product_id": document["_id"]})
            count += 1
    return count


def run_periodic_controller(config: PlatformConfig, callback) -> None:
    RabbitQueueClient(config.rabbitmq_url).declare_standard_queues()
    while True:
        try:
            callback(config, {"limit": 10000})
        except Exception:
            logger.exception("Periodic controller failed for role=%s", config.role)
        time.sleep(config.retention_interval_seconds)


def run_consumer(config: PlatformConfig, handler_name: str) -> None:
    queue_name = queue_name_for_role(config.role)
    if not queue_name:
        raise RuntimeError(f"No queue mapped for role {config.role}")
    queue = RabbitQueueClient(config.rabbitmq_url)
    queue.declare_standard_queues()
    handlers = {
        "ingest-uploader": lambda payload: process_upload_job(config, payload),
        "decoder-worker": lambda payload: process_decode_job(config, payload),
        "materializer-worker": lambda payload: process_materialize_job(config, payload),
        "retention-controller": lambda payload: process_retention_scan(config, payload),
        "metadata-retention-controller": lambda payload: process_metadata_retention_scan(config, payload),
        "reconciler": lambda payload: process_reconcile_scan(config, payload),
        "backfill-runner": lambda payload: process_replay(config, payload),
    }
    import pika

    while True:
        try:
            queue.consume_forever(queue_name, handlers[config.role])
        except (pika.exceptions.AMQPError, OSError):
            logger.exception("Consumer disconnected; reconnecting")
            time.sleep(5)


def run_service(config: PlatformConfig) -> None:
    if config.role in {"observability-agent", "alerts-worker", "timelapse-worker", "analysis-worker"}:
        raise NotImplementedError(f"{config.role} is a planned extension, not a deployed service")
    if config.role != "bootstrap":
        start_health_server(config)
    logger.info("Starting role=%s service=%s", config.role, config.service_name)
    if config.role == "ingest-watcher":
        run_ingest_watch_loop(config)
    elif config.role == "bootstrap":
        RabbitQueueClient(config.rabbitmq_url).declare_standard_queues()
        CouchDBClient(config.couchdb_url, "catalog").ensure_databases(["catalog", "projections", "control", "operations"])
        for database in ["catalog", "projections"]:
            CouchDBClient(config.couchdb_url, database).ensure_type_view()
        rustfs = RustFSClient(config.rustfs_endpoint, config.rustfs_access_key, config.rustfs_secret_key)
        for bucket in [
            config.source_bucket,
            config.dashboard_bucket,
            config.timelapse_bucket,
            config.alerts_bucket,
            config.analysis_bucket,
        ]:
            rustfs.ensure_bucket(bucket)
        seed_retention_profiles(config)
        logger.info("Bootstrap complete")
        return
    elif config.role == "reconciler":
        run_periodic_controller(config, process_reconcile_scan)
    elif config.role == "backfill-runner":
        run_consumer(config, config.role)
    elif config.role == "retention-controller":
        run_periodic_controller(config, process_retention_scan)
    elif config.role == "metadata-retention-controller":
        run_periodic_controller(config, process_metadata_retention_scan)
    elif config.role == "catalog-api":
        threading.Event().wait()
    elif config.enable_queue_consumer or queue_name_for_role(config.role):
        run_consumer(config, config.role)
    else:
        threading.Event().wait()
