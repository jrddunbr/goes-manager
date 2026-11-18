"""Browser-facing dashboard API."""
from __future__ import annotations

from flask import Flask, jsonify

from object_platform_common.config import load_config
from object_platform_common.health import readiness_response


def create_app() -> Flask:
    config = load_config()
    app = Flask("object-platform-dashboard-api")

    @app.get("/readyz")
    def readyz():
        return readiness_response(config)

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "service": config.service_name, "role": config.role})

    @app.get("/api/summary")
    def summary():
        import requests

        def fetch(path):
            response = requests.get(f"{config.catalog_api_url}/{path}", timeout=60)
            response.raise_for_status()
            return response.json()

        try:
            counts = fetch("stats")
            products = fetch("products?limit=20").get("items", [])
            stations = fetch("stations?limit=20").get("items", [])
        except requests.RequestException:
            return jsonify({"error": "catalog unavailable"}), 503
        return jsonify(
            {
                "counts": {
                    "products": counts["products"],
                    "stations": counts["stations"],
                },
                "products": products[:20],
                "stations": stations[:20],
            }
        )

    return app
