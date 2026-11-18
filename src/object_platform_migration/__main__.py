"""Resumable, verified archive import. Original files are never modified."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time

from object_platform_common.config import load_config
from object_platform_common.couchdb import CouchDBClient
from object_platform_common.logging_utils import configure_logging
from object_platform_common.runtime import (
    iter_source_files, process_upload_job, process_decode_job, process_materialize_job,
)
from object_platform_common.storage import RustFSClient, build_source_object_key, sha256_file

logger = logging.getLogger(__name__)


def migrate(config, report_path: Path, *, dry_run: bool = False, decode: bool = True) -> dict:
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "source": str(config.input_root),
              "files": 0, "bytes": 0, "verified": 0, "failed": 0,
              "dry_run": dry_run, "complete": False}
    catalog = CouchDBClient(config.couchdb_url, "catalog")
    storage = RustFSClient(config.rustfs_endpoint, config.rustfs_access_key, config.rustfs_secret_key)
    if not config.input_root.is_dir():
        raise ValueError(f"Source directory does not exist: {config.input_root}")
    if not dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
    # Stream errors separately; a large import must not accumulate a giant JSON array in RAM.
    errors_path = report_path.with_suffix(".errors.jsonl")
    errors = errors_path.open("w") if not dry_run else None
    try:
        for path in iter_source_files(config.input_root):
            report["files"] += 1
            try:
                before = path.stat()
                report["bytes"] += before.st_size
                if dry_run:
                    continue
                key = build_source_object_key(config.input_root, path)
                # Retry transient dependency failures in place, leaving a resumable catalog.
                for attempt in range(3):
                    try:
                        process_upload_job(config, {"path": str(path), "dispatch": False, "force": attempt > 0})
                        doc = catalog.get_document(f"raw:{key}")
                        if not doc or doc.get("retention", {}).get("status") == "deleted":
                            raise RuntimeError("Catalog marks this source deleted; use an explicit restore policy")
                        fingerprint = doc["fingerprint"]
                        checksum = sha256_file(path)
                        after = path.stat()
                        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            raise RuntimeError("Source changed during import; rerun after writes finish")
                        if checksum != fingerprint["sha256"] or before.st_size != fingerprint["size"]:
                            raise RuntimeError("Catalog fingerprint does not match source")
                        storage.verify_object(config.source_bucket, key, checksum, before.st_size)
                        if decode and doc.get("decode", {}).get("status") == "queued":
                            process_decode_job(config, {"raw_product_id": doc["_id"], "dispatch": False})
                            doc = catalog.get_document(doc["_id"])
                        decoded_id = doc.get("decode", {}).get("decoded_product_id")
                        if decode and decoded_id:
                            decoded = catalog.get_document(decoded_id)
                            if decoded and decoded.get("projection_status") != "complete":
                                process_materialize_job(config, {"decoded_product_id": decoded_id})
                        report["verified"] += 1
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        time.sleep(2 ** attempt)
            except Exception as exc:
                report["failed"] += 1
                logger.exception("Import failed: %s", path)
                if errors:
                    errors.write(json.dumps({"path": str(path), "error": str(exc)}) + "\n")
                    errors.flush()
            if report["files"] % 100 == 0:
                logger.info("Migration progress: %s", report)
                if not dry_run:
                    save_report(report_path, report)
        report["complete"] = True
    finally:
        if errors:
            errors.close()
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        if not dry_run:
            save_report(report_path, report)
    return report


def save_report(path: Path, report: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-decode", action="store_true", help="Import blobs and metadata; workers decode later")
    parser.add_argument("--report", type=Path, default=Path("/reports/latest.json"))
    args = parser.parse_args()
    configure_logging("migration")
    result = migrate(load_config(), args.report, dry_run=args.dry_run, decode=not args.no_decode)
    print(json.dumps(result, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
