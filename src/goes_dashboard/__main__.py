"""CLI entrypoint for the EMWIN dashboard service."""

import signal
import sys

from .service import main


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    raise SystemExit(main())
