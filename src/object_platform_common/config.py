"""Environment-driven configuration for object platform services."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class PlatformConfig:
    service_name: str
    role: str
    input_root: Path
    rabbitmq_url: str
    couchdb_url: str
    rustfs_endpoint: str
    rustfs_access_key: str
    rustfs_secret_key: str
    catalog_api_url: str
    health_port: int
    enable_queue_consumer: bool
    scan_interval_seconds: int
    retention_interval_seconds: int
    retention_grace_seconds: int
    metadata_retention_days: int
    retention_enabled: bool = False
    source_bucket: str = "goes-source"
    dashboard_bucket: str = "goes-dashboard"
    timelapse_bucket: str = "goes-timelapse"
    alerts_bucket: str = "goes-alerts"
    analysis_bucket: str = "goes-analysis"


def load_config() -> PlatformConfig:
    return PlatformConfig(
        service_name=os.environ.get("OBJECT_PLATFORM_SERVICE_NAME", "object-platform-service"),
        role=os.environ.get("OBJECT_PLATFORM_ROLE", "service"),
        input_root=Path(os.environ.get("OBJECT_PLATFORM_INPUT_ROOT", "/ingest")),
        rabbitmq_url=os.environ.get("OBJECT_PLATFORM_RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
        couchdb_url=os.environ.get("OBJECT_PLATFORM_COUCHDB_URL", "http://admin:admin@localhost:5984/"),
        rustfs_endpoint=os.environ.get("OBJECT_PLATFORM_RUSTFS_ENDPOINT", "http://localhost:9000"),
        rustfs_access_key=os.environ.get("OBJECT_PLATFORM_RUSTFS_ACCESS_KEY", ""),
        rustfs_secret_key=os.environ.get("OBJECT_PLATFORM_RUSTFS_SECRET_KEY", ""),
        catalog_api_url=os.environ.get("OBJECT_PLATFORM_CATALOG_API_URL", "http://localhost:8080"),
        health_port=int(os.environ.get("OBJECT_PLATFORM_HEALTH_PORT", "8080")),
        enable_queue_consumer=os.environ.get("OBJECT_PLATFORM_ENABLE_QUEUE_CONSUMER", "").lower() in {"1", "true", "yes"},
        scan_interval_seconds=int(os.environ.get("OBJECT_PLATFORM_SCAN_INTERVAL_SECONDS", "30")),
        retention_interval_seconds=int(os.environ.get("OBJECT_PLATFORM_RETENTION_INTERVAL_SECONDS", "3600")),
        retention_grace_seconds=int(os.environ.get("OBJECT_PLATFORM_RETENTION_GRACE_SECONDS", "86400")),
        retention_enabled=os.environ.get("OBJECT_PLATFORM_RETENTION_ENABLED", "false").lower() == "true",
        metadata_retention_days=int(os.environ.get("OBJECT_PLATFORM_METADATA_RETENTION_DAYS", "7")),
    )
