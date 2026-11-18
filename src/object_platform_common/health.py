"""Liveness and dependency readiness for platform services."""
from __future__ import annotations

import socket
from urllib.parse import urlsplit

from flask import Flask, jsonify


def readiness_response(config):
    import requests

    try:
        if config.role == 'dashboard-api':
            requests.get(f'{config.catalog_api_url}/readyz', timeout=2).raise_for_status()
        else:
            requests.get(f'{config.couchdb_url.rstrip("/")}/_up', timeout=2).raise_for_status()
            requests.get(f'{config.rustfs_endpoint}/health', timeout=2).raise_for_status()
            if config.role not in {'catalog-api', 'materializer-worker', 'metadata-retention-controller'}:
                broker = urlsplit(config.rabbitmq_url)
                with socket.create_connection((broker.hostname, broker.port or 5672), timeout=2):
                    pass
    except (requests.RequestException, OSError):
        return jsonify({'ok': False, 'ready': False, 'service': config.service_name}), 503
    return jsonify({'ok': True, 'ready': True, 'service': config.service_name})


def build_health_app(service_name: str, role: str, config=None) -> Flask:
    app = Flask(service_name)

    @app.get('/healthz')
    def healthz():
        return jsonify({'ok': True, 'service': service_name, 'role': role})

    @app.get('/readyz')
    def readyz():
        if config is None:
            return jsonify({'ok': False, 'ready': False}), 503
        return readiness_response(config)

    return app
