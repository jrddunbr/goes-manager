"""Internal catalog API for object platform consumers."""
from __future__ import annotations

from flask import Flask, abort, jsonify, request

from object_platform_common.config import load_config
from object_platform_common.health import readiness_response
from object_platform_common.couchdb import CouchDBClient


def create_app() -> Flask:
    config = load_config()
    app = Flask("object-platform-catalog-api")

    @app.get("/readyz")
    def readyz():
        return readiness_response(config)

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "service": config.service_name, "role": config.role})

    @app.get("/stats")
    def stats():
        products = CouchDBClient(config.couchdb_url, "catalog").type_counts()
        stations = CouchDBClient(config.couchdb_url, "projections").type_counts()
        return jsonify({"products": products.get("raw_product", 0), "stations": stations.get("station_view", 0)})

    def read_limit():
        try:
            value = int(request.args.get("limit", "50"))
        except ValueError:
            abort(400, "limit must be an integer")
        if not 1 <= value <= 1000:
            abort(400, "limit must be between 1 and 1000")
        return value

    @app.get("/products")
    def products():
        limit = read_limit()
        catalog = CouchDBClient(config.couchdb_url, "catalog")
        docs = catalog.find_documents({"type": "raw_product", "retention.status": {"$ne": "deleted"}}, limit=limit)
        return jsonify({"items": docs})

    @app.get("/products/<path:doc_id>")
    def product(doc_id: str):
        catalog = CouchDBClient(config.couchdb_url, "catalog")
        doc = catalog.get_document(doc_id)
        if doc is None:
            abort(404)
        return jsonify(doc)

    @app.get("/stations")
    def stations():
        limit = read_limit()
        projections = CouchDBClient(config.couchdb_url, "projections")
        docs = projections.find_documents({"type": "station_view"}, limit=limit)
        return jsonify({"items": docs})

    @app.get("/stations/<path:doc_id>")
    def station(doc_id: str):
        projections = CouchDBClient(config.couchdb_url, "projections")
        doc = projections.get_document(doc_id)
        if doc is None:
            abort(404)
        return jsonify(doc)

    @app.get("/objects/<path:doc_id>/resolve")
    def resolve_object(doc_id: str):
        catalog = CouchDBClient(config.couchdb_url, "catalog")
        doc = catalog.get_document(doc_id)
        if doc is None:
            abort(404)
        object_store = doc.get("object_store") or {}
        return jsonify(
            {
                "bucket": object_store.get("bucket"),
                "key": object_store.get("key"),
                "endpoint": config.rustfs_endpoint,
            }
        )

    return app
