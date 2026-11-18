import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from object_platform_common.queue import RabbitQueueClient
from object_platform_common.runtime import build_job

spec = importlib.util.spec_from_file_location('deploy_platform', Path(__file__).resolve().parents[1] / 'scripts/deploy_object_platform.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def test_plan_is_read_only(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'raw').write_bytes(b'raw')
    data = tmp_path / 'new-data'
    env = tmp_path / 'new.env'
    assert deploy.main(['--source', str(source), '--data-dir', str(data), '--env-file', str(env), '--plan']) == 0
    assert not data.exists() and not env.exists()


def test_deploy_refuses_unmounted_ssd_before_writing(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'raw').write_bytes(b'raw')
    data = tmp_path / 'new-data'
    with pytest.raises(SystemExit):
        deploy.main(['--source', str(source), '--data-dir', str(data)])
    assert not data.exists()


def test_deploy_refuses_nested_data_and_source(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    with pytest.raises(SystemExit):
        deploy.main(['--source', str(source), '--data-dir', str(source / 'platform'), '--plan'])


def test_env_roundtrip_preserves_credentials_and_permissions(tmp_path):
    path = tmp_path / 'deployment.env'
    values = {'PASSWORD': '0123456789', 'PATH': '/ssd/data with spaces/$literal'}
    deploy.save_env(path, values)
    assert deploy.load_env(path) == values
    assert path.stat().st_mode & 0o777 == 0o600


def test_systemd_unit_uses_podman_and_quotes_paths():
    text = deploy.systemd_unit([], '/ssd/a b/deployment.env', '/ssd/source', '/ssd/platform')
    assert 'podman-compose' in text
    assert '"/ssd/a b/deployment.env"' in text
    assert '"up" "-d"' in text
    assert 'docker' not in text


def test_health_wait_accepts_podman_43_inspect_shape(monkeypatch):
    def run(command, **kwargs):
        if command[0] == 'podman':
            return json.dumps([{'State': {'Healthcheck': {'Status': 'healthy'}}}])
        return 'container-id'
    monkeypatch.setattr(deploy, 'run', run)
    deploy.wait_healthy(['podman-compose'], ['rustfs'], {}, 1)


@pytest.fixture
def fake_queue(monkeypatch):
    events = []
    class Channel:
        is_open = True
        reject_publish = False
        callback = None
        body = b'{}'
        def queue_declare(self, **kwargs): pass
        def basic_qos(self, **kwargs): pass
        def confirm_delivery(self): events.append('confirm')
        def basic_publish(self, **kwargs):
            events.append(('publish', kwargs))
            if self.reject_publish:
                raise RuntimeError('broker rejected publish')
        def basic_ack(self, **kwargs): events.append('ack')
        def basic_reject(self, **kwargs): events.append(('reject', kwargs))
        def basic_consume(self, queue, on_message_callback): self.callback = on_message_callback
        def start_consuming(self): self.callback(self, SimpleNamespace(delivery_tag=1), None, self.body)
    channel = Channel()
    class Connection:
        is_open = True
        def channel(self): return channel
        def close(self): events.append('close')
    monkeypatch.setitem(sys.modules, 'pika', SimpleNamespace(BasicProperties=lambda **kw: kw))
    client = RabbitQueueClient('amqp://localhost')
    monkeypatch.setattr(client, '_connect', lambda: Connection())
    return client, channel, events


def test_publish_uses_confirms_and_mandatory_routing(fake_queue):
    client, channel, events = fake_queue
    client.publish('ingest-jobs', build_job('ingest', {'path': 'x'}))
    assert events[0] == 'confirm'
    assert events[1][1]['mandatory'] is True


def test_malformed_message_is_dead_lettered(fake_queue):
    client, channel, events = fake_queue
    channel.body = b'not-json'
    client.consume_forever('ingest-jobs', lambda payload: pytest.fail('should not run'))
    assert ('reject', {'delivery_tag': 1, 'requeue': False}) in events
    assert 'ack' not in events


def test_retry_is_confirmed_before_ack(fake_queue):
    client, channel, events = fake_queue
    def fail(payload): raise RuntimeError('worker failure')
    client.consume_forever('ingest-jobs', fail)
    publish_index = next(i for i, event in enumerate(events) if isinstance(event, tuple) and event[0] == 'publish')
    assert publish_index < events.index('ack')
    assert events[publish_index][1]['exchange'] == 'retry'


def test_rejected_retry_keeps_original_unacked(fake_queue):
    client, channel, events = fake_queue
    channel.reject_publish = True
    def fail(payload): raise RuntimeError('worker failure')
    with pytest.raises(RuntimeError):
        client.consume_forever('ingest-jobs', fail)
    assert 'ack' not in events


def test_deployment_orders_import_before_workers_and_preserves_secrets(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'raw').write_bytes(b'raw')
    data, env_file = tmp_path / 'platform', tmp_path / 'deployment.env'
    monkeypatch.setattr(Path, 'is_mount', lambda path: True)
    monkeypatch.setattr(deploy.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setattr(deploy, 'wait_healthy', lambda *args: None)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[:3] == ['podman', 'image', 'inspect']:
            return json.dumps([{'RepoDigests': ['docker.io/example/image@sha256:' + 'a'*64]}])
        return ''
    monkeypatch.setattr(deploy, 'run', run)
    arguments = ['--source', str(source), '--data-dir', str(data), '--env-file', str(env_file)]
    assert deploy.main(arguments) == 0
    import_index = next(i for i, command in enumerate(calls) if command[-1] == 'migration')
    worker_index = next(i for i, command in enumerate(calls) if '--force-recreate' in command)
    assert import_index < worker_index
    assert all('false' in command for command in calls if command[0] == 'podman-compose')
    saved = deploy.load_env(env_file)
    assert saved['OBJECT_PLATFORM_RETENTION_ENABLED'] == 'false'
    assert len(saved['COUCHDB_PASSWORD']) == 48
    assert (data / 'goes-object-platform.service').is_file()
    assert deploy.main(arguments) == 0
    assert deploy.load_env(env_file)['COUCHDB_PASSWORD'] == saved['COUCHDB_PASSWORD']


def test_failed_import_leaves_retention_disabled_and_workers_stopped(tmp_path, monkeypatch):
    import subprocess
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'raw').write_bytes(b'raw')
    data, env_file = tmp_path / 'platform', tmp_path / 'deployment.env'
    monkeypatch.setattr(Path, 'is_mount', lambda path: True)
    monkeypatch.setattr(deploy.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setattr(deploy, 'wait_healthy', lambda *args: None)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[:3] == ['podman', 'image', 'inspect']:
            return json.dumps([{'RepoDigests': ['docker.io/example/image@sha256:' + 'a'*64]}])
        if command[-1] == 'migration':
            raise subprocess.CalledProcessError(1, command)
        return ''
    monkeypatch.setattr(deploy, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        deploy.main(['--source', str(source), '--data-dir', str(data), '--env-file', str(env_file), '--enable-retention'])
    assert deploy.load_env(env_file)['OBJECT_PLATFORM_RETENTION_ENABLED'] == 'false'
    assert not any('--force-recreate' in command for command in calls)
    assert (source / 'raw').read_bytes() == b'raw'


def test_container_processes_install_termination_handler(monkeypatch):
    import signal
    from object_platform_common import logging_utils
    registered = {}
    monkeypatch.setattr(logging_utils.signal, "signal", lambda sig, handler: registered.update({sig: handler}))
    logging_utils.configure_logging("test")
    with pytest.raises(SystemExit) as stopped:
        registered[signal.SIGTERM](signal.SIGTERM, None)
    assert stopped.value.code == 143
