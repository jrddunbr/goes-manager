"""Command-line interface for the GOES retention manager."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Iterable, Optional

from goes_manager.config import AppConfig, load_retention_app_config

from .engine import RetentionManager, RetentionSummary


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GOES retention manager")
    parser.add_argument("--common-config", default="config/common.json", help="Path to shared configuration file")
    parser.add_argument("--config", default="config/retention.json", help="Path to retention configuration file")
    parser.add_argument("--log-level", dest="log_level", default=None, help="Optional logging level override")
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run mode irrespective of config")
    parser.add_argument("--execute", action="store_true", help="Apply changes even if dry-run is enabled in config")
    parser.add_argument("--summarize", action="store_true", help="Print a summary after execution")
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Loop retention with the provided interval (seconds); defaults to config when omitted",
    )
    return parser


def load_app_config(common_path: str, retention_path: str) -> Optional[AppConfig]:
    try:
        return load_retention_app_config(common_path, retention_path)
    except FileNotFoundError as exc:
        print(f"Configuration file not found: {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to load configuration: {exc}", file=sys.stderr)
    return None


def retention_main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    app_config = load_app_config(args.common_config, args.config)
    if app_config is None:
        return 2

    setup_logging((args.log_level or app_config.log_level or "INFO").upper())

    if not app_config.retention:
        logging.error("Retention configuration missing")
        return 2

    dry_run_override: Optional[bool] = None
    if args.dry_run:
        dry_run_override = True
    elif args.execute:
        dry_run_override = False

    manager = RetentionManager(app_config, app_config.retention, dry_run=dry_run_override)

    if args.interval is not None:
        interval = args.interval or app_config.retention.interval_seconds
        asyncio.run(run_retention_loop(manager, interval))
        return 0

    summary = manager.run_once()
    if args.summarize:
        print(format_summary(summary))
    return 0


async def run_retention_loop(manager: RetentionManager, interval: int) -> None:
    interval = max(1, interval)
    while True:
        try:
            manager.run_once()
        except Exception:  # noqa: BLE001
            logging.exception("Retention iteration failed")
        await asyncio.sleep(interval)


def format_summary(summary: RetentionSummary) -> str:
    lines = [
        f"files_evaluated={summary.files_evaluated}",
        f"files_matched={summary.files_matched}",
        f"actions_performed={summary.actions_performed}",
        f"bytes_freed={summary.bytes_freed}",
    ]
    for result in summary.results:
        lines.append(
            f"action={result.action} rule={result.rule} path={result.path} detail={result.detail} bytes_freed={result.bytes_freed}"
        )
    return "\n".join(lines)
