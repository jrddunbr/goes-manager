"""Filesystem monitoring that writes manifest summaries."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, Iterable

from goes_manager.config import AppConfig, MonitorConfig, MonitorRootConfig
from goes_manager.util import JsonWriter, load_state, posix_path, save_state, utc_now

logger = logging.getLogger(__name__)


@dataclass
class FileRecord:
    key: str
    manifest: Path
    payload: Dict[str, object]
    mtime: float


class FilesystemMonitor:
    """Poll directories and append structured manifest entries when files change."""

    def __init__(self, app_config: AppConfig, monitor_config: MonitorConfig) -> None:
        self.app_config = app_config
        self.config = monitor_config
        self.state_path = monitor_config.state_file or (app_config.state_dir / "monitor_state.json")
        self.state = load_state(self.state_path).get("files", {})
        if not isinstance(self.state, dict):
            self.state = {}

    def scan_once(self) -> int:
        if not self.config.enabled:
            logger.info("Filesystem monitor disabled in configuration")
            return 0

        total_written = 0
        state_modified = False

        for root in self.config.roots:
            new_records = list(self._scan_root(root))
            if not new_records:
                continue

            writer = JsonWriter(root.manifest)
            written = writer.append_many(record.payload for record in new_records)
            total_written += written
            if written:
                logger.info("Wrote %s entries to %s", written, root.manifest)

            for record in new_records:
                self.state[record.key] = record.mtime
                state_modified = True

        if state_modified:
            save_state(self.state_path, {"files": self.state})

        return total_written

    def _scan_root(self, root: MonitorRootConfig) -> Iterable[FileRecord]:
        path = root.path
        if not path.exists():
            logger.warning("Monitor root missing: %s", path)
            return []

        for item in path.rglob("*"):
            if not item.is_file():
                continue

            try:
                relative_to_root = item.relative_to(path)
            except ValueError:
                relative_to_root = item.name

            relative_str = posix_path(Path(relative_to_root))

            if not self._matches(relative_str, root.include):
                continue
            if self._matches(relative_str, root.exclude):
                continue

            try:
                stat_result = item.stat()
            except FileNotFoundError:
                continue

            key = self._state_key(item)
            mtime = stat_result.st_mtime
            previous_mtime = self.state.get(key)
            if previous_mtime is not None and mtime <= previous_mtime:
                continue

            payload = {
                "path": key,
                "root": posix_path(path),
                "size": stat_result.st_size,
                "mtime": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                "seen_at": utc_now().isoformat(),
            }
            yield FileRecord(key=key, manifest=root.manifest, payload=payload, mtime=mtime)

    def _state_key(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.app_config.data_root)
            return posix_path(relative)
        except ValueError:
            return posix_path(path.resolve())

    @staticmethod
    def _matches(value: str, patterns: Iterable[str]) -> bool:
        return any(fnmatch(value, pattern) for pattern in patterns)
