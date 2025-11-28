"""Retention policy enforcement."""
from __future__ import annotations

import gzip
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, List, Optional

from goes_manager.config import (
    AppConfig,
    RetentionActionConfig,
    RetentionConfig,
    RetentionRuleConfig,
)
from goes_manager.util import ensure_directory, posix_path

logger = logging.getLogger(__name__)


@dataclass
class RetentionActionResult:
    rule: str
    action: str
    path: Path
    detail: str = ""
    bytes_freed: int = 0


@dataclass
class RetentionSummary:
    files_evaluated: int = 0
    files_matched: int = 0
    actions_performed: int = 0
    bytes_freed: int = 0
    results: List[RetentionActionResult] = field(default_factory=list)

    def record(self, result: RetentionActionResult) -> None:
        self.actions_performed += 1
        self.bytes_freed += result.bytes_freed
        self.results.append(result)


@dataclass
class ActionExecution:
    result: Optional[RetentionActionResult]
    new_path: Optional[Path] = None
    new_root: Optional[Path] = None
    deleted: bool = False
    success: bool = True


class RetentionManager:
    """Apply configured retention rules to the filesystem."""

    def __init__(self, app_config: AppConfig, retention_config: RetentionConfig, dry_run: Optional[bool] = None) -> None:
        self.app_config = app_config
        self.config = retention_config
        self.dry_run = app_config.dry_run if dry_run is None else dry_run

    def run_once(self) -> RetentionSummary:
        summary = RetentionSummary()
        if not self.config.enabled:
            logger.info("Retention manager disabled in configuration")
            return summary

        now = datetime.now(timezone.utc)

        for rule in self.config.rules:
            summary.files_evaluated += self._process_rule(rule, now, summary)

        if summary.actions_performed:
            logger.info(
                "Retention actions complete: %s files touched, %s bytes freed (dry_run=%s)",
                summary.actions_performed,
                summary.bytes_freed,
                self.dry_run,
            )
        else:
            logger.info("Retention run finished with no actions (dry_run=%s)", self.dry_run)

        return summary

    def _process_rule(self, rule: RetentionRuleConfig, now: datetime, summary: RetentionSummary) -> int:
        files_seen = 0
        stage_map = self._build_directory_stage_map(rule)
        base_directories = {path.resolve() for path in rule.directories}
        for directory in self._expand_rule_directories(rule):
            resolved_dir = directory.resolve()
            base_stage = stage_map.get(resolved_dir, -1)
            if not resolved_dir.exists():
                if resolved_dir in base_directories:
                    logger.warning("Retention rule '%s' directory does not exist: %s", rule.name, resolved_dir)
                    continue
                try:
                    ensure_directory(resolved_dir)
                    logger.info(
                        "Created missing action target directory for rule '%s': %s",
                        rule.name,
                        resolved_dir,
                    )
                except OSError as exc:
                    logger.warning(
                        "Unable to create target directory %s for rule '%s': %s",
                        resolved_dir,
                        rule.name,
                        exc,
                    )
                    continue

            for file_path in self._iter_files(resolved_dir):
                files_seen += 1
                relative = file_path.relative_to(resolved_dir)
                relative_str = posix_path(relative)

                if not self._matches(relative_str, rule.include):
                    continue
                if self._matches(relative_str, rule.exclude):
                    continue

                summary.files_matched += 1
                try:
                    stat_result = file_path.stat()
                except FileNotFoundError:
                    continue

                age_seconds = (now - datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)).total_seconds()

                current_path = file_path
                current_root = resolved_dir
                current_stage = base_stage

                for action_index, action in enumerate(rule.actions):
                    if action.after_seconds > age_seconds:
                        break
                    if action_index <= current_stage:
                        continue

                    try:
                        relative = current_path.relative_to(current_root)
                    except ValueError:
                        logger.warning(
                            "Skipping action '%s' for %s because path is outside root %s",
                            action.type,
                            current_path,
                            current_root,
                        )
                        break

                    execution = self._apply_action(
                        rule=rule,
                        action=action,
                        file_path=current_path,
                        relative=relative,
                        size=stat_result.st_size,
                        current_root=current_root,
                    )
                    if execution.result:
                        summary.record(execution.result)

                    if not execution.success:
                        break

                    if execution.deleted:
                        break

                    if execution.new_path is not None:
                        current_path = execution.new_path
                        if not self.dry_run:
                            try:
                                stat_result = current_path.stat()
                            except FileNotFoundError:
                                break

                    if execution.new_root is not None:
                        current_root = execution.new_root.resolve()

                    current_stage = action_index

        return files_seen

    def _expand_rule_directories(self, rule: RetentionRuleConfig) -> List[Path]:
        """Include action targets so staged files continue to be processed."""
        directories: List[Path] = []
        seen: set[Path] = set()

        for entry in rule.directories:
            resolved = entry.resolve()
            if resolved in seen:
                continue
            directories.append(entry)
            seen.add(resolved)

        for action in rule.actions:
            if not action.target:
                continue
            resolved = action.target.resolve()
            if resolved in seen:
                continue
            directories.append(action.target)
            seen.add(resolved)

        return directories

    def _build_directory_stage_map(self, rule: RetentionRuleConfig) -> dict[Path, int]:
        """Map action target directories to the index of the action that produced them."""
        stage_map: dict[Path, int] = {}
        for idx, action in enumerate(rule.actions):
            if not action.target:
                continue
            stage_map[action.target.resolve()] = idx
        return stage_map

    def _iter_files(self, directory: Path) -> Iterable[Path]:
        """Yield files under ``directory`` while tolerating concurrent deletions/moves."""
        stack = [directory]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                                continue
                            if entry.is_file(follow_symlinks=False):
                                yield Path(entry.path)
                        except FileNotFoundError:
                            # Entry vanished between scandir and metadata check; skip it.
                            continue
            except FileNotFoundError:
                # Directory was removed after being queued; nothing left to scan.
                continue

    @staticmethod
    def _matches(path: str, patterns: Iterable[str]) -> bool:
        return any(fnmatch(path, pattern) for pattern in patterns)

    def _apply_action(
        self,
        rule: RetentionRuleConfig,
        action: RetentionActionConfig,
        file_path: Path,
        relative: Path,
        size: int,
        current_root: Path,
    ) -> ActionExecution:
        action_type = action.type.lower()
        if action_type in {"delete", "remove"}:
            return self._delete(rule, file_path, size)
        if action_type in {"move", "archive"}:
            if not action.target:
                logger.error("Rule '%s' missing target for move action", rule.name)
                return ActionExecution(
                    result=RetentionActionResult(
                        rule=rule.name,
                        action=action.type,
                        path=file_path,
                        detail="missing target for move",
                    ),
                    success=False,
                )
            return self._move(rule, file_path, relative, action.target)
        if action_type in {"compress", "gzip"}:
            return self._compress(rule, file_path, relative, action, size, current_root)

        logger.error("Rule '%s' referenced unsupported action '%s'", rule.name, action.type)
        return ActionExecution(
            result=RetentionActionResult(
                rule=rule.name,
                action=action.type,
                path=file_path,
                detail="unsupported action",
            ),
            success=False,
        )

    def _delete(self, rule: RetentionRuleConfig, file_path: Path, size: int) -> ActionExecution:
        detail = ""
        success = True
        if self.dry_run:
            logger.info("[dry-run] Would delete %s (rule=%s)", file_path, rule.name)
        else:
            try:
                file_path.unlink()
                logger.info("Deleted %s (rule=%s)", file_path, rule.name)
            except FileNotFoundError:
                detail = "file already removed"
                success = False
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to delete %s: %s", file_path, exc)
                detail = f"error: {exc}"
                success = False
        return ActionExecution(
            result=RetentionActionResult(rule=rule.name, action="delete", path=file_path, detail=detail, bytes_freed=size),
            deleted=True,
            success=success,
        )

    def _move(self, rule: RetentionRuleConfig, file_path: Path, relative: Path, target_root: Path) -> ActionExecution:
        destination = target_root / relative
        detail = f"-> {destination}"
        success = True
        if self.dry_run:
            logger.info("[dry-run] Would move %s to %s (rule=%s)", file_path, destination, rule.name)
        else:
            ensure_directory(destination.parent)
            if destination.exists():
                logger.warning("Destination already exists, overwriting: %s", destination)
            try:
                source_parent = file_path.parent
                shutil.move(str(file_path), str(destination))
                logger.info("Moved %s -> %s (rule=%s)", file_path, destination, rule.name)
                # Remove empty parent directories after successful move
                self._cleanup_empty_directories(source_parent, rule)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to move %s -> %s: %s", file_path, destination, exc)
                detail = f"error: {exc}"
                success = False
        return ActionExecution(
            result=RetentionActionResult(rule=rule.name, action="move", path=file_path, detail=detail),
            new_path=destination if success or self.dry_run else None,
            new_root=target_root if success or self.dry_run else None,
            success=success,
        )

    def _cleanup_empty_directories(self, directory: Path, rule: RetentionRuleConfig) -> None:
        """Remove empty parent directories up to the rule's base directory."""
        try:
            # Only clean up directories that are under one of the rule's directories
            rule_directories = [d.resolve() for d in rule.directories]
            current = directory.resolve()

            # Walk up the directory tree
            while current != current.parent:
                # Stop if we've reached a rule base directory
                if current in rule_directories:
                    break

                # Check if this directory is under any rule directory
                under_rule_dir = any(current.is_relative_to(base) for base in rule_directories)
                if not under_rule_dir:
                    break

                # Try to remove if empty
                try:
                    if not any(current.iterdir()):
                        current.rmdir()
                        logger.info("Removed empty directory %s (rule=%s)", current, rule.name)
                    else:
                        # Directory not empty, stop walking up
                        break
                except OSError:
                    # Directory not empty or permission error, stop trying
                    break

                current = current.parent
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to cleanup empty directories from %s: %s", directory, exc)

    def _compress(
        self,
        rule: RetentionRuleConfig,
        file_path: Path,
        relative: Path,
        action: RetentionActionConfig,
        size: int,
        current_root: Path,
    ) -> ActionExecution:
        detail = ""
        target_root = action.target

        compression = (action.compression or "gz").lower()

        if target_root:
            destination = target_root / relative.with_suffix(relative.suffix)
        else:
            destination = file_path

        if compression in {"gz", "gzip"}:
            destination = destination.with_suffix(destination.suffix + ".gz")
            compress_result, success = self._compress_gzip(file_path, destination, rule, action)
        elif compression in {"zstd", "zst"}:
            destination = destination.with_suffix(destination.suffix + ".zst")
            compress_result, success = self._compress_zstd(file_path, destination, rule, action)
        else:
            logger.error("Unsupported compression '%s' in rule '%s'", compression, rule.name)
            return ActionExecution(
                result=RetentionActionResult(rule=rule.name, action="compress", path=file_path, detail="unsupported compression"),
                success=False,
            )

        detail = compress_result or ""
        bytes_freed = 0 if action.keep_original else size
        result = RetentionActionResult(rule=rule.name, action="compress", path=file_path, detail=detail, bytes_freed=bytes_freed)

        if not success:
            return ActionExecution(result=result, success=False)

        new_root = target_root or current_root
        new_path = None
        if not action.keep_original:
            new_path = destination
        elif target_root:
            new_path = destination

        return ActionExecution(result=result, new_path=new_path, new_root=new_root if new_path else None)

    def _compress_gzip(
        self,
        source_path: Path,
        destination: Path,
        rule: RetentionRuleConfig,
        action: RetentionActionConfig,
    ) -> tuple[Optional[str], bool]:
        if self.dry_run:
            logger.info("[dry-run] Would gzip %s -> %s (rule=%s)", source_path, destination, rule.name)
            return None, True

        try:
            ensure_directory(destination.parent)
            with source_path.open("rb") as source, gzip.open(destination, "wb") as sink:
                shutil.copyfileobj(source, sink)
            logger.info("Compressed %s -> %s (rule=%s)", source_path, destination, rule.name)
            if not action.keep_original:
                source_path.unlink()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to compress %s -> %s: %s", source_path, destination, exc)
            return (f"error: {exc}", False)
        return (None, True)

    def _compress_zstd(
        self,
        source_path: Path,
        destination: Path,
        rule: RetentionRuleConfig,
        action: RetentionActionConfig,
    ) -> tuple[Optional[str], bool]:
        if self.dry_run:
            logger.info("[dry-run] Would zstd %s -> %s (rule=%s)", source_path, destination, rule.name)
            return None, True

        try:
            import zstandard as zstd
        except ImportError:
            logger.error("Zstandard compression requested but 'zstandard' package is not installed")
            return ("missing zstandard dependency", False)

        try:
            ensure_directory(destination.parent)
            cctx = zstd.ZstdCompressor()
            with source_path.open("rb") as source, destination.open("wb") as sink:
                with cctx.stream_writer(sink) as compressor:
                    shutil.copyfileobj(source, compressor)
            logger.info("Compressed %s -> %s (rule=%s)", source_path, destination, rule.name)
            if not action.keep_original:
                source_path.unlink()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to zstd-compress %s -> %s: %s", source_path, destination, exc)
            return (f"error: {exc}", False)
        return (None, True)
