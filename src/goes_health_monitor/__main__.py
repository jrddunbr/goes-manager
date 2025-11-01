"""Executable entry point for ``python -m goes_health_monitor``."""

from . import health_main


if __name__ == "__main__":
    raise SystemExit(health_main())
