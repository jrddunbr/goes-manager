from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

from goes_health_monitor.service import (
    MountProbe,
    MountWatcher,
    SystemdUnitWatcher,
)


def _probe_sequence(values: Iterator[MountProbe]):
    def _inner(_: Path) -> MountProbe:
        return next(values)

    return _inner


def test_mount_watcher_flags_unmounted_path() -> None:
    path = Path("/var/satellite")
    probes = iter(
        [
            MountProbe(True, True, 100, True, True),
            MountProbe(True, False, 1, True, True),
        ]
    )
    watcher = MountWatcher([path], probe=_probe_sequence(probes))
    severity, issues, report = watcher.evaluate(datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc))

    assert severity == "error"
    assert any("not mounted" in issue for issue in issues)
    assert report[0]["severity"] == "error"


def test_systemd_unit_watcher_detects_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, capture_output, text, check, timeout):  # type: ignore[no-untyped-def]
        assert cmd[:3] == ["systemctl", "show", "satdump.service"]
        return SimpleNamespace(stdout="ActiveState=inactive\nSubState=dead\nResult=exit-code\n")

    monkeypatch.setattr("goes_health_monitor.service.subprocess.run", fake_run)

    watcher = SystemdUnitWatcher("satdump.service")
    severity, issues, info = watcher.evaluate(datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc))

    assert severity == "error"
    assert any("inactive" in issue for issue in issues)
    assert info.get("activestate") == "inactive"
