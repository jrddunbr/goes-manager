"""Seed a shared ingest volume with SatDump-like EMWIN files for smoke tests."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import time

from object_platform_common.logging_utils import configure_logging


LOGGER = logging.getLogger(__name__)

SAMPLES = {
    "A_FTUS80KWBC150010_C_KWIN_20260415001147_411405-2-TAFALLUS.txt": (
        "FTUS80 KWBC 150010\n"
        "\n"
        "TAF\n"
        "\n"
        "KZZV 150000Z 1500/1524 22008KT P6SM SCT060 BKN250 "
        "PROB30 1512/1515 6SM -SHRA BKN050\n"
    ),
    "A_SAUS70KWBC150010_C_KWIN_20260415001147_411405-2-SAHOURLY.txt": (
        "SAUS70 KWBC 150010\n"
        "\n"
        "METAR\n"
        "\n"
        "KAXV 150005Z AUTO 14006KT 7SM TSRA SCT011 BKN040 OVC100 15/13 A2989 RMK AO2=\n"
    ),
}


def write_samples(root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    written = 0
    marker = datetime.now(timezone.utc).isoformat()
    for filename, payload in SAMPLES.items():
        path = root / filename
        if path.exists():
            continue
        path.write_text(f"{payload}\n# seeded_at={marker}\n", encoding="utf-8")
        written += 1
        LOGGER.info("Seeded %s", path)
    return written


def main() -> int:
    configure_logging("testdata-seeder")
    root = Path(os.environ.get("OBJECT_PLATFORM_SEED_ROOT", "/seed-output"))
    interval = int(os.environ.get("OBJECT_PLATFORM_SEED_INTERVAL_SECONDS", "20"))
    while True:
        write_samples(root)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
