"""Executable entry for ``python -m goes_manager``."""

import sys


if __name__ == "__main__":
    raise SystemExit(
        "Use the dedicated entry points: 'python -m goes_retention' or 'python -m goes_filesystem_monitor'."
    )
