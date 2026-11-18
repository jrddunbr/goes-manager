from pathlib import Path
from urllib.parse import unquote, urlparse

from object_platform_common.couchdb import CouchDBClient
from object_platform_common.queue import payload_from_envelope
from object_platform_common.runtime import build_job
from object_platform_common.runtime import retention_for_source_family, source_family_for_path
from object_platform_common.storage import build_source_object_key
from object_platform_dashboard_api.app import create_app as create_dashboard_app


def test_build_source_object_key_uses_relative_path(tmp_path: Path) -> None:
    source_root = tmp_path / "ingest"
    source_root.mkdir()
    sample = source_root / "EMWIN" / "sample.txt"
    sample.parent.mkdir()
    sample.write_text("payload", encoding="utf-8")

    assert build_source_object_key(source_root, sample) == "EMWIN/sample.txt"


def test_build_job_is_deterministic_for_payload_path() -> None:
    job = build_job("ingest-source-file", {"path": "/ingest/EMWIN/sample.txt"})

    assert job.job_id == "ingest-source-file:/ingest/EMWIN/sample.txt"
    assert job.job_type == "ingest-source-file"
    assert job.created_at


def test_queue_payload_from_envelope_extracts_nested_payload() -> None:
    envelope = {
        "job_id": "ingest-source-file:/ingest/EMWIN/sample.txt",
        "job_type": "ingest-source-file",
        "attempt": 1,
        "payload": {"path": "/ingest/EMWIN/sample.txt"},
    }

    assert payload_from_envelope(envelope) == {"path": "/ingest/EMWIN/sample.txt"}


def test_couchdb_document_url_escapes_slashes_in_ids() -> None:
    client = CouchDBClient("http://goes:goes@couchdb:5984/", "catalog")
    url = client.document_url("raw:EMWIN/nested/sample.txt")

    assert url.endswith("/raw%3AEMWIN%2Fnested%2Fsample.txt")
    assert unquote(urlparse(url).path.rsplit("/", 1)[-1]) == "raw:EMWIN/nested/sample.txt"


def test_source_family_for_path_classifies_emwin_files() -> None:
    assert source_family_for_path(Path("A_TEST.txt")) == "emwin-text"
    assert source_family_for_path(Path("chart.gif")) == "emwin-graphic"
    assert source_family_for_path(Path("product.cbor")) == "metadata"


def test_retention_for_source_family_sets_delete_after() -> None:
    from datetime import datetime, timezone

    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    retention = retention_for_source_family("emwin-text", created_at)

    assert retention["profile"] == "emwin-text-180d"
    assert retention["status"] == "active"
    assert retention["retain_until"] < retention["delete_after"]


def test_dashboard_app_exposes_healthz() -> None:
    app = create_dashboard_app()
    client = app.test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
