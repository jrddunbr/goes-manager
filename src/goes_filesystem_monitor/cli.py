"""Command-line interface for the GOES filesystem monitor."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Iterable, Optional

from goes_manager.config import AppConfig, load_monitor_app_config

from .monitor import FilesystemMonitor


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GOES filesystem monitor")
    parser.add_argument("--common-config", default="config/common.json", help="Path to shared configuration file")
    parser.add_argument("--config", default="config/filesystem_monitor.json", help="Path to monitor configuration file")
    parser.add_argument("--log-level", dest="log_level", default=None, help="Optional logging level override")
    parser.add_argument("--once", action="store_true", help="Perform a single scan and exit")
    parser.add_argument("--interval", type=int, default=None, help="Override monitor loop interval (seconds)")
    return parser


def load_app_config(common_path: str, monitor_path: str) -> Optional[AppConfig]:
    try:
        return load_monitor_app_config(common_path, monitor_path)
    except FileNotFoundError as exc:
        print(f"Configuration file not found: {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to load configuration: {exc}", file=sys.stderr)
    return None


def monitor_main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    app_config = load_app_config(args.common_config, args.config)
    if app_config is None:
        return 2

    setup_logging((args.log_level or app_config.log_level or "INFO").upper())

    if not app_config.monitor:
        logging.error("Filesystem monitor configuration missing")
        return 2

    monitor = FilesystemMonitor(app_config, app_config.monitor)

    if args.once:
        written = monitor.scan_once()
        logging.info("Monitor wrote %s new records", written)
        return 0

    interval = args.interval or app_config.monitor.interval_seconds
    asyncio.run(run_monitor_loop(monitor, interval))
    return 0


async def run_monitor_loop(monitor: FilesystemMonitor, interval: int) -> None:
    interval = max(1, interval)
    while True:
        try:
            monitor.scan_once()
        except Exception:  # noqa: BLE001
            logging.exception("Monitor iteration failed")
        await asyncio.sleep(interval)
