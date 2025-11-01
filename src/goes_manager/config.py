"""Configuration loading helpers shared by GOES services."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .util import ensure_directory, parse_duration_to_seconds, resolve_path


@dataclass
class RetentionActionConfig:
    after_seconds: int
    type: str
    target: Optional[Path] = None
    compression: Optional[str] = None
    keep_original: bool = False


@dataclass
class RetentionRuleConfig:
    name: str
    directories: List[Path]
    include: List[str] = field(default_factory=lambda: ["**"])
    exclude: List[str] = field(default_factory=list)
    actions: List[RetentionActionConfig] = field(default_factory=list)


@dataclass
class RetentionConfig:
    enabled: bool = True
    interval_seconds: int = 3600
    rules: List[RetentionRuleConfig] = field(default_factory=list)


@dataclass
class MonitorRootConfig:
    path: Path
    manifest: Path
    include: List[str] = field(default_factory=lambda: ["**"])
    exclude: List[str] = field(default_factory=list)


@dataclass
class MonitorConfig:
    enabled: bool = True
    interval_seconds: int = 60
    roots: List[MonitorRootConfig] = field(default_factory=list)
    state_file: Optional[Path] = None


@dataclass
class AppConfig:
    config_path: Path
    data_root: Path
    state_dir: Path
    log_level: str = "INFO"
    dry_run: bool = False
    retention: Optional[RetentionConfig] = None
    monitor: Optional[MonitorConfig] = None


def _ensure_list(value, default):
    if value is None:
        return list(default)
    if isinstance(value, list):
        return value
    return [value]


def _load_retention_config(data: dict, data_root: Path) -> RetentionConfig:
    enabled = data.get("enabled", True)
    interval_seconds = int(data.get("interval_seconds", 3600))
    rule_configs: List[RetentionRuleConfig] = []

    for rule_data in data.get("rules", []):
        name = rule_data.get("name") or "unnamed-rule"
        directories_raw = _ensure_list(rule_data.get("directories") or rule_data.get("paths"), [])
        if not directories_raw:
            raise ValueError(f"Retention rule '{name}' must define at least one directory")
        directories = [resolve_path(data_root, entry) for entry in directories_raw]

        include = _ensure_list(rule_data.get("include"), ["**"])
        exclude = _ensure_list(rule_data.get("exclude"), [])

        actions: List[RetentionActionConfig] = []
        for action_data in rule_data.get("actions", []):
            after_value = action_data.get("after") or action_data.get("age")
            if not after_value:
                raise ValueError(f"Retention rule '{name}' action is missing an 'after' value")
            after_seconds = parse_duration_to_seconds(str(after_value))
            action_type = str(action_data.get("type") or "delete").lower()

            target_raw = action_data.get("target") or action_data.get("destination")
            target_path = resolve_path(data_root, target_raw) if target_raw else None

            compression = action_data.get("compression")
            keep_original = bool(action_data.get("keep_original", False))

            actions.append(
                RetentionActionConfig(
                    after_seconds=after_seconds,
                    type=action_type,
                    target=target_path,
                    compression=compression,
                    keep_original=keep_original,
                )
            )

        if not actions:
            raise ValueError(f"Retention rule '{name}' must define at least one action")

        rule_configs.append(
            RetentionRuleConfig(
                name=name,
                directories=directories,
                include=include,
                exclude=exclude,
                actions=sorted(actions, key=lambda a: a.after_seconds),
            )
        )

    return RetentionConfig(enabled=enabled, interval_seconds=interval_seconds, rules=rule_configs)


def _load_monitor_config(data: dict, data_root: Path, state_dir: Path) -> MonitorConfig:
    enabled = data.get("enabled", True)
    interval_seconds = int(data.get("interval_seconds", 60))
    roots: List[MonitorRootConfig] = []

    manifests_base = resolve_path(state_dir, data.get("manifests_dir", "manifests"))

    for root_data in data.get("roots", []):
        path_value = root_data.get("path") or root_data.get("directory")
        if not path_value:
            raise ValueError("Filesystem monitor root requires a 'path'")
        path = resolve_path(data_root, path_value)

        manifest_value = root_data.get("manifest")
        if manifest_value:
            manifest = resolve_path(manifests_base, manifest_value)
        else:
            manifest_name = Path(path_value).name or "manifest"
            manifest = manifests_base / f"{manifest_name}.ndjson"

        include = _ensure_list(root_data.get("include"), ["**"])
        exclude = _ensure_list(root_data.get("exclude"), [])

        roots.append(
            MonitorRootConfig(
                path=path,
                manifest=manifest,
                include=include,
                exclude=exclude,
            )
        )

    state_file = data.get("state_file")
    state_file_path = resolve_path(state_dir, state_file) if state_file else (state_dir / "monitor_state.json")

    return MonitorConfig(enabled=enabled, interval_seconds=interval_seconds, roots=roots, state_file=state_file_path)


def _load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _merge_payload(base: Dict, override: Dict) -> Dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_payload(result[key], value)
        else:
            result[key] = value
    return result


def _build_app_config(payload: Dict, *, base_dir: Path, config_path: Path) -> AppConfig:
    data_root_value = payload.get("data_root") or payload.get("root") or "."
    data_root = resolve_path(base_dir, data_root_value)

    state_dir_value = payload.get("state_dir") or payload.get("state") or "state"
    state_dir = resolve_path(base_dir, state_dir_value)
    ensure_directory(state_dir)

    dry_run = bool(payload.get("dry_run", False))
    log_level = str(payload.get("logging", {}).get("level", "INFO")).upper()

    retention_cfg = None
    if "retention" in payload:
        retention_cfg = _load_retention_config(payload["retention"], data_root)

    monitor_cfg = None
    if "monitor" in payload:
        monitor_cfg = _load_monitor_config(payload["monitor"], data_root, state_dir)

    return AppConfig(
        config_path=config_path,
        data_root=data_root,
        state_dir=state_dir,
        log_level=log_level,
        dry_run=dry_run,
        retention=retention_cfg,
        monitor=monitor_cfg,
    )


def load_retention_app_config(common_config: str | Path, retention_config: str | Path) -> AppConfig:
    common_path = Path(common_config).resolve()
    retention_path = Path(retention_config).resolve()

    payload = _load_json(common_path)
    payload = _merge_payload(payload, _load_json(retention_path))

    if "retention" not in payload:
        raise ValueError("Retention configuration file must include a 'retention' section")

    return _build_app_config(payload, base_dir=common_path.parent, config_path=retention_path)


def load_monitor_app_config(common_config: str | Path, monitor_config: str | Path) -> AppConfig:
    common_path = Path(common_config).resolve()
    monitor_path = Path(monitor_config).resolve()

    payload = _load_json(common_path)
    payload = _merge_payload(payload, _load_json(monitor_path))

    if "monitor" not in payload:
        raise ValueError("Monitor configuration file must include a 'monitor' section")

    return _build_app_config(payload, base_dir=common_path.parent, config_path=monitor_path)
