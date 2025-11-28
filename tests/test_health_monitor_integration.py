"""Optional integration tests for SatDump API monitoring.

These tests attempt to contact the real SatDump API configured for the
test environment and also validate the "unreachable" path so crashes are
surfaced instead of silently skipped.

To exercise the test API from the Pi lab network set the environment
variable `GOES_SATDUMP_TEST_API` if you need a different URL and then run

```
pytest -k integration --maxfail=1
```
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from goes_health_monitor.service import SatdumpApiClient, SatdumpApiEvaluator
from goes_manager.config import SatdumpApiConfig, SatdumpSignalThresholds


@pytest.mark.integration
def test_satdump_api_analysis_live_endpoint() -> None:
    """Fetch the live SatDump API and ensure evaluation completes."""

    base_url = os.environ.get("GOES_SATDUMP_TEST_API", "http://10.0.0.101:8000")
    config = SatdumpApiConfig(base_url=base_url, status_endpoint="/api", timeout_seconds=3.0)
    client = SatdumpApiClient(config)

    result = client.fetch_status()
    status = str(result.get("status", "unknown")).lower()
    if status == "ok":
        data = result.get("data")
        if not isinstance(data, dict):
            pytest.fail("SatDump API payload missing 'data' object")

        thresholds = SatdumpSignalThresholds()
        evaluator = SatdumpApiEvaluator(thresholds)
        evaluation = evaluator.evaluate(data, datetime.now(tz=timezone.utc))

        assert evaluation.metrics, "Expected decoded metrics from SatDump API"
        assert "severity" in evaluation.metrics.get("demod", {}), "Demod metrics should include severity flag"
    else:
        assert status in {
            "unreachable",
            "timeout",
            "http-error",
            "empty-response",
            "invalid-json",
        }, f"Unexpected SatDump API status {status}"
        # The client should include context for operators when degraded.
        assert any(key in result for key in {"detail", "code"}), "Expected diagnostic details for degraded API"
