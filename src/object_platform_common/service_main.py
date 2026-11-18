"""Shared entrypoint for object platform services."""
from __future__ import annotations

from dataclasses import replace

from .config import load_config
from .logging_utils import configure_logging
from .runtime import run_service


def main(default_role: str = "service") -> int:
    config = load_config()
    if config.role == "service":
        config = replace(config, role=default_role, service_name=default_role)
    configure_logging(config.service_name)
    run_service(config)
    return 0
