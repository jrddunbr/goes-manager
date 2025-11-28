from __future__ import annotations

import os
import time
from pathlib import Path

from goes_manager.config import (
    AppConfig,
    RetentionActionConfig,
    RetentionConfig,
    RetentionRuleConfig,
)
from goes_retention.engine import RetentionManager


def build_manager(tmp_path: Path) -> tuple[RetentionManager, dict[str, Path]]:
    data_root = tmp_path / "data"
    hot_dir = data_root / "IMAGES/GOES-16"
    warm_dir = data_root / "ARCHIVE/WARM/IMAGES"
    seasonal_dir = data_root / "ARCHIVE/SEASONAL/IMAGES"

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    rule = RetentionRuleConfig(
        name="images",
        directories=[hot_dir],
        include=["**/*.png"],
        actions=[
            RetentionActionConfig(after_seconds=3, type="move", target=warm_dir),
            RetentionActionConfig(
                after_seconds=6,
                type="compress",
                target=seasonal_dir,
                compression="gz",
                keep_original=False,
            ),
        ],
    )

    retention_config = RetentionConfig(enabled=True, rules=[rule])
    app_config = AppConfig(
        config_path=tmp_path / "config.json",
        data_root=data_root,
        state_dir=state_dir,
    )

    manager = RetentionManager(app_config, retention_config, dry_run=False)
    return manager, {"hot": hot_dir, "warm": warm_dir, "seasonal": seasonal_dir}


def make_file(path: Path, age_seconds: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"payload")
    ts = time.time() - age_seconds
    os.utime(path, (ts, ts))


def test_retention_pipeline_moves_and_compresses(tmp_path) -> None:
    manager, roots = build_manager(tmp_path)
    hot_file = roots["hot"] / "Full Disk" / "sample.png"
    make_file(hot_file, age_seconds=8)

    summary = manager.run_once()

    compressed = roots["seasonal"] / "Full Disk" / "sample.png.gz"
    assert compressed.exists(), "file should be compressed into the seasonal tier"
    assert not hot_file.exists(), "original hot file should be removed after compression"
    assert any(result.action == "move" for result in summary.results)
    assert any(result.action == "compress" for result in summary.results)


def test_retention_resumes_from_intermediate_target(tmp_path) -> None:
    manager, roots = build_manager(tmp_path)
    warm_file = roots["warm"] / "Mesoscale" / "sample.png"
    make_file(warm_file, age_seconds=8)

    manager.run_once()

    compressed = roots["seasonal"] / "Mesoscale" / "sample.png.gz"
    assert compressed.exists(), "engine should continue processing files already in the warm tier"
    assert not warm_file.exists(), "warm tier source should be removed after compression"
