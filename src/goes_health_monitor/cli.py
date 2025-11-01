"""Command-line interface for the GOES health monitor."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Iterable, Optional

from goes_manager.config import AppConfig, load_health_app_config

from .service import HealthMonitor


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GOES health monitor")
    parser.add_argument("--common-config", default="config/common.json", help="Path to shared configuration file")
    parser.add_argument("--config", default="config/health_monitor.json", help="Path to health monitor configuration file")
    parser.add_argument("--log-level", dest="log_level", default=None, help="Optional logging level override")
    parser.add_argument("--once", action="store_true", help="Perform a single health check and exit")
    parser.add_argument("--interval", type=int, default=None, help="Override monitor loop interval (seconds)")
    return parser


def load_app_config(common_path: str, health_path: str) -> Optional[AppConfig]:
    try:
        return load_health_app_config(common_path, health_path)
    except FileNotFoundError as exc:
        print(f"Configuration file not found: {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to load configuration: {exc}", file=sys.stderr)
    return None


def health_main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    app_config = load_app_config(args.common_config, args.config)
    if app_config is None:
        return 2

    if not app_config.health:
        print("Health configuration missing in config file", file=sys.stderr)
        return 2

    setup_logging((args.log_level or app_config.log_level or "INFO").upper())

    monitor = HealthMonitor(app_config, app_config.health)

    if args.once:
        snapshot = monitor.run_once()
        logging.info("Health snapshot: status=%s issues=%s", snapshot.status, "; ".join(snapshot.issues))
        return 0

    interval = args.interval or app_config.health.interval_seconds
    asyncio.run(run_health_loop(monitor, interval))
    return 0


async def run_health_loop(monitor: HealthMonitor, interval: int) -> None:
    interval = max(5, interval)
    while True:
        try:
            monitor.run_once()
        except Exception:  # noqa: BLE001
            logging.exception("Health monitor iteration failed")
        await asyncio.sleep(interval)
