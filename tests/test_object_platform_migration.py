from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from object_platform_common import runtime
from object_platform_common.config import load_config
from object_platform_common.couchdb import CouchDBClient
from object_platform_common.storage import RustFSClient
from object_platform_migration import __main__ as migration


@pytest.fixture
def platform(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    config = replace(load_config(), input_root=source)
    databases = {name: {} for name in ['catalog', 'control', 'operations', 'projections']}
    objects = {}
    published = []

    class Couch:
        def __init__(self, url, database='catalog'):
            self.docs = databases[database]
        def get_document(self, key):
            return deepcopy(self.docs.get(key))
        def upsert_document(self, key, doc):
            self.docs[key] = deepcopy(doc)
        def create_document(self, key, doc):
            self.docs.setdefault(key, deepcopy(doc))
        def iter_documents(self):
            yield from deepcopy(list(self.docs.values()))
        def delete_document(self, key):
            self.docs.pop(key, None)

    class Store:
        uploads = 0
        deletes = 0
        def __init__(self, *args):
            pass
        def put_object(self, bucket, key, path, checksum=None):
            Store.uploads += 1
            objects[bucket, key] = path.read_bytes()
            return {'bucket': bucket, 'key': key, 'size': path.stat().st_size}
        def object_exists(self, bucket, key):
            return (bucket, key) in objects
        def iter_objects(self, bucket):
            for (object_bucket, key), value in list(objects.items()):
                if object_bucket == bucket:
                    yield {"Key": key, "Size": len(value), "LastModified": datetime.now(timezone.utc)}
        def head_object(self, bucket, key):
            return {"ContentLength": len(objects[bucket, key]), "Metadata": {}}
        def get_object_bytes(self, bucket, key):
            return objects[bucket, key]
        def verify_object(self, bucket, key, checksum, size):
            value = objects[bucket, key]
            assert len(value) == size
            assert hashlib.sha256(value).hexdigest() == checksum
        def delete_object(self, bucket, key):
            Store.deletes += 1
            objects.pop((bucket, key), None)

    class Queue:
        fail = False
        def __init__(self, *args):
            pass
        def publish(self, name, job):
            if Queue.fail:
                raise RuntimeError('broker unavailable')
            published.append((name, job))
        def close(self):
            pass

    for module in [runtime, migration]:
        monkeypatch.setattr(module, 'CouchDBClient', Couch)
        monkeypatch.setattr(module, 'RustFSClient', Store)
    monkeypatch.setattr(runtime, 'RabbitQueueClient', Queue)
    monkeypatch.setattr(migration.time, 'sleep', lambda seconds: None)
    return config, databases, objects, published, Store, Queue


def test_import_recurses_verifies_and_resumes_without_reupload(platform, tmp_path):
    config, db, objects, jobs, store, _ = platform
    (config.input_root / 'nested').mkdir()
    (config.input_root / 'nested' / 'image.bin').write_bytes(b'raw\x00data')
    (config.input_root / 'empty').touch()
    report = tmp_path / 'reports' / 'latest.json'
    first = migration.migrate(config, report)
    assert (first['files'], first['verified'], first['failed']) == (2, 2, 0)
    assert not jobs  # Synchronous import does not build a second queue backlog.
    assert store.uploads == 2
    assert migration.migrate(config, report)['verified'] == 2
    assert store.uploads == 2
    assert json.loads(report.read_text())['failed'] == 0
    assert (config.input_root / 'nested' / 'image.bin').read_bytes() == b'raw\x00data'


def test_import_dry_run_has_no_writes_or_storage_calls(platform, tmp_path):
    config, db, objects, jobs, store, _ = platform
    (config.input_root / 'image').write_bytes(b'image')
    report = tmp_path / 'absent' / 'report.json'
    assert migration.migrate(config, report, dry_run=True)['files'] == 1
    assert not report.parent.exists()
    assert not objects and not db['catalog'] and not jobs


def test_upload_retry_recovers_missing_decode_publication(platform):
    config, db, objects, jobs, store, queue = platform
    path = config.input_root / 'weather.txt'
    path.write_text('bulletin')
    queue.fail = True
    with pytest.raises(RuntimeError):
        runtime.process_upload_job(config, {'path': str(path)})
    assert db['catalog']['raw:weather.txt']['decode']['status'] == 'queued'
    queue.fail = False
    runtime.process_upload_job(config, {'path': str(path)})
    assert store.uploads == 1
    assert [name for name, _ in jobs] == ['decode-jobs']


def test_reconcile_requeues_projection_after_decode_commit(platform):
    config, db, objects, jobs, *_ = platform
    objects[config.source_bucket, 'x.txt'] = b'x'
    db['catalog']['raw:x.txt'] = {'_id': 'raw:x.txt', 'type': 'raw_product',
        'object_store': {'bucket': config.source_bucket, 'key': 'x.txt'},
        'decode': {'status': 'decoded', 'decoded_product_id': 'decoded:x'}}
    db['catalog']['decoded:x'] = {'_id': 'decoded:x', 'projection_status': 'pending'}
    runtime.process_reconcile_scan(config)
    assert [name for name, _ in jobs] == ['materialize-jobs']


def test_corrupt_object_fails_import_with_error_report(platform, tmp_path, monkeypatch):
    config, db, objects, jobs, store, _ = platform
    (config.input_root / 'image').write_bytes(b'valid')
    def corrupt(*args):
        raise RuntimeError('checksum mismatch')
    monkeypatch.setattr(store, 'verify_object', corrupt)
    report = tmp_path / 'report.json'
    result = migration.migrate(config, report)
    assert result['failed'] == 1 and result['verified'] == 0
    assert 'checksum mismatch' in report.with_suffix('.errors.jsonl').read_text()


def test_import_rejects_links_and_source_escape(platform, tmp_path):
    config, *_ = platform
    outside = tmp_path / 'private'
    outside.write_bytes(b'private')
    (config.input_root / 'link').symlink_to(outside)
    assert list(runtime.iter_source_files(config.input_root)) == []
    with pytest.raises(ValueError):
        runtime.process_upload_job(config, {'path': str(outside)})


def test_retention_disabled_by_default_and_deleted_objects_stay_deleted(platform):
    config, db, objects, jobs, store, _ = platform
    now = datetime.now(timezone.utc)
    db['catalog']['raw:old'] = {'_id': 'raw:old', 'type': 'raw_product',
        'object_store': {'bucket': config.source_bucket, 'key': 'old'},
        'retention': {'delete_after': (now-timedelta(days=1)).isoformat(), 'status': 'deleted'}}
    assert runtime.process_retention_scan(config) == 0
    assert runtime.process_retention_scan(replace(config, retention_enabled=True)) == 0
    assert store.deletes == 0


def test_retention_defaults_preserve_operator_profiles(platform):
    config, db, *_ = platform
    runtime.seed_retention_profiles(config)
    db['control']['retention-profile:emwin-text-180d']['blob_policy']['retain_days'] = 42
    runtime.seed_retention_profiles(config)
    assert db['control']['retention-profile:emwin-text-180d']['blob_policy']['retain_days'] == 42
    path = config.input_root / 'weather.txt'
    path.write_text('weather')
    runtime.process_upload_job(config, {'path': str(path), 'dispatch': False})
    retention = db['catalog']['raw:weather.txt']['retention']
    assert datetime.fromisoformat(retention['retain_until']) > datetime.now(timezone.utc) + timedelta(days=41)
    assert datetime.fromisoformat(retention['retain_until']) < datetime.now(timezone.utc) + timedelta(days=43)


def test_metadata_cleanup_removes_decoded_children_of_expired_raw(platform):
    config, db, *_ = platform
    old = (datetime.now(timezone.utc)-timedelta(days=30)).isoformat()
    db['catalog']['raw:x'] = {'_id': 'raw:x', 'type': 'raw_product', 'retention': {'status': 'deleted', 'deleted_at': old}}
    db['catalog']['decoded:x'] = {'_id': 'decoded:x', 'type': 'decoded_product', 'raw_product_id': 'raw:x', 'updated_at': old}
    runtime.process_metadata_retention_scan(replace(config, retention_enabled=True, metadata_retention_days=7))
    assert not db['catalog']


def test_pagination_reaches_documents_beyond_first_page(monkeypatch):
    import requests
    pages = [
        {'rows': [{'id': 'a', 'doc': {'_id': 'a'}}, {'id': 'b', 'doc': {'_id': 'b'}}]},
        {'rows': [{'id': 'c', 'doc': {'_id': 'c'}}]},
    ]
    calls = []
    class Response:
        def raise_for_status(self): pass
        def json(self): return pages.pop(0)
    def get(url, params, timeout):
        calls.append(params)
        return Response()
    monkeypatch.setattr(CouchDBClient, 'ensure_database', lambda self: None)
    monkeypatch.setattr(requests, 'get', get)
    docs = list(CouchDBClient('http://couchdb').iter_documents(page_size=2))
    assert [d['_id'] for d in docs] == ['a', 'b', 'c']
    assert calls[1]['startkey'] == '"b"' and 'skip' not in calls[1]


def test_verify_reads_stream_and_rejects_multipart_etag_as_checksum(monkeypatch):
    class Body:
        def iter_chunks(self, chunk_size): yield b'correct'
        def close(self): pass
    class Client:
        def get_object(self, **kwargs): return {'Body': Body()}
    storage = RustFSClient('', '', '')
    monkeypatch.setattr(storage, '_client', lambda: Client())
    storage.verify_object('bucket', 'key', hashlib.sha256(b'correct').hexdigest(), 7)
    with pytest.raises(RuntimeError):
        storage.verify_object('bucket', 'key', hashlib.sha256(b'wrong').hexdigest(), 7)


def test_unimplemented_extensions_fail_explicitly():
    with pytest.raises(NotImplementedError):
        runtime.run_service(replace(load_config(), role='timelapse-worker'))


def test_reconcile_recovers_metadata_for_blob_without_source(platform):
    config, db, objects, jobs, *_ = platform
    objects[config.source_bucket, 'orphan.bin'] = b'archived'
    assert runtime.process_reconcile_scan(config) == 1
    assert db['catalog']['raw:orphan.bin']['fingerprint']['size'] == 8
    assert not jobs


def test_object_repair_preserves_holds_and_original_retention(platform):
    config, db, objects, jobs, store, _ = platform
    path = config.input_root / 'data.bin'
    path.write_bytes(b'data')
    runtime.process_upload_job(config, {'path': str(path), 'dispatch': False})
    original = db['catalog']['raw:data.bin']
    original['retention']['pin_reason'] = 'important event'
    retained = deepcopy(original['retention'])
    objects.clear()
    runtime.process_upload_job(config, {'path': str(path), 'dispatch': False})
    assert db['catalog']['raw:data.bin']['retention'] == retained
    assert store.uploads == 2


def test_pagination_does_not_skip_successor_when_cursor_was_deleted(monkeypatch):
    import requests
    pages = [
        {"rows": [{"id": "a", "doc": {"_id": "a"}}, {"id": "b", "doc": {"_id": "b"}}]},
        {"rows": [{"id": "c", "doc": {"_id": "c"}}, {"id": "d", "doc": {"_id": "d"}}]},
    ]
    class Response:
        def raise_for_status(self): pass
        def json(self): return pages.pop(0)
    monkeypatch.setattr(CouchDBClient, 'ensure_database', lambda self: None)
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: Response())
    assert [d['_id'] for d in CouchDBClient('http://couchdb').iter_documents(2)] == ['a', 'b', 'c', 'd']
