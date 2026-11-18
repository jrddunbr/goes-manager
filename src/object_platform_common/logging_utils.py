"""Logging setup for object platform services."""
from __future__ import annotations

import logging
import signal


def terminate(signum, frame):
    # Python running as container PID 1 must install an explicit SIGTERM handler.
    raise SystemExit(128 + signum)


def configure_logging(service_name: str) -> None:
    signal.signal(signal.SIGTERM, terminate)
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s %(levelname)s [{service_name}] %(name)s: %(message)s",
    )

    # Connection lifecycle chatter otherwise overwhelms logs during large imports.
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
