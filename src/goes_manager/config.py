"""Configuration loading helpers shared by GOES services."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .util import ensure_directory, parse_duration_to_seconds, resolve_path

LOGGER = logging.getLogger(__name__)


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
class HealthAlertConfig:
    webhook_url: str
    username: Optional[str] = None
    min_severity: str = "warning"
    cooldown_seconds: int = 600


@dataclass
class SatdumpApiConfig:
    base_url: str = "http://localhost:8000"
    status_endpoint: str = "/api/status"
    timeout_seconds: float = 5.0


@dataclass
class SatdumpSignalThresholds:
    min_snr_warning: float = 2.0
    min_snr_error: float = 1.0
    min_peak_snr_warning: float = 3.0
    min_peak_snr_error: float = 2.0
    max_viterbi_ber_warning: float = 0.12
    max_viterbi_ber_error: float = 0.2
    require_deframer_lock: bool = True
    require_viterbi_lock: bool = True


@dataclass
class HealthConfig:
    enabled: bool = True
    interval_seconds: int = 60
    state_file: Path = Path("state/health.json")
    satdump_unit: str = "satdump.service"
    journal_lookback_seconds: int = 600
    journal_max_gap_seconds: int = 900
    journal_recent_limit: int = 50
    error_keywords: List[str] = field(
        default_factory=lambda: ["error", "critical", "cannot", "failed", "fatal"]
    )
    warning_keywords: List[str] = field(default_factory=lambda: ["warning", "degraded", "retry"])
    satdump_api: Optional[SatdumpApiConfig] = None
    signal_thresholds: SatdumpSignalThresholds = field(default_factory=SatdumpSignalThresholds)
    storage_mounts: List[Path] = field(default_factory=list)
    alert: Optional[HealthAlertConfig] = None


@dataclass
class AppConfig:
    config_path: Path
    data_root: Path
    state_dir: Path
    log_level: str = "INFO"
    dry_run: bool = False
    retention: Optional[RetentionConfig] = None
    monitor: Optional[MonitorConfig] = None
    health: Optional[HealthConfig] = None


def _ensure_list(value, default):
    if value is None:
        return list(default)
    if isinstance(value, list):
        return value
    return [value]


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


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


def _load_health_config(data: dict, state_dir: Path) -> HealthConfig:
    enabled = data.get("enabled", True)
    interval_seconds = int(data.get("interval_seconds", 60))

    state_file_value = data.get("state_file", "health.json")
    state_file = resolve_path(state_dir, state_file_value)

    satdump_unit = str(data.get("satdump_unit", "satdump.service"))

    lookback_seconds = int(data.get("journal", {}).get("lookback_seconds", data.get("journal_lookback_seconds", 600)))
    max_gap_seconds = int(data.get("journal", {}).get("max_gap_seconds", data.get("journal_max_gap_seconds", 900)))
    recent_limit = int(data.get("journal", {}).get("recent_limit", data.get("journal_recent_limit", 50)))

    error_keywords = _ensure_list(
        data.get("journal", {}).get("error_keywords"),
        ["error", "critical", "cannot", "failed", "fatal"],
    )
    warning_keywords = _ensure_list(
        data.get("journal", {}).get("warning_keywords"),
        ["warning", "degraded", "retry"],
    )

    api_cfg = None
    api_data = data.get("satdump_api")
    if api_data:
        base_url = str(api_data.get("base_url", "http://localhost:8000"))
        status_endpoint = str(api_data.get("status_endpoint", "/api/status"))
        timeout_seconds = float(api_data.get("timeout", api_data.get("timeout_seconds", 5.0)))
        api_cfg = SatdumpApiConfig(
            base_url=base_url.rstrip("/"),
            status_endpoint=status_endpoint if status_endpoint.startswith("/") else f"/{status_endpoint}",
            timeout_seconds=timeout_seconds,
        )

    threshold_data = data.get("satdump_thresholds") or (api_data.get("thresholds") if api_data else None) or {}
    thresholds = SatdumpSignalThresholds(
        min_snr_warning=float(threshold_data.get("min_snr_warning", 2.0)),
        min_snr_error=float(threshold_data.get("min_snr_error", 1.0)),
        min_peak_snr_warning=float(threshold_data.get("min_peak_snr_warning", 3.0)),
        min_peak_snr_error=float(threshold_data.get("min_peak_snr_error", 2.0)),
        max_viterbi_ber_warning=float(threshold_data.get("max_viterbi_ber_warning", 0.12)),
        max_viterbi_ber_error=float(threshold_data.get("max_viterbi_ber_error", 0.2)),
        require_deframer_lock=_coerce_bool(threshold_data.get("require_deframer_lock"), True),
        require_viterbi_lock=_coerce_bool(threshold_data.get("require_viterbi_lock"), True),
    )

    storage_mounts_raw = data.get("storage_mounts") or data.get("mounts") or []
    storage_mounts: List[Path] = []
    for entry in _ensure_list(storage_mounts_raw, []):
        storage_mounts.append(resolve_path(state_dir, entry))

    alert_cfg = None
    alert_data = data.get("alert") or data.get("alerts")
    if alert_data and alert_data.get("webhook_url"):
        alert_cfg = HealthAlertConfig(
            webhook_url=str(alert_data.get("webhook_url")),
            username=alert_data.get("username"),
            min_severity=str(alert_data.get("min_severity", "warning")).lower(),
            cooldown_seconds=int(alert_data.get("cooldown_seconds", 600)),
        )

    return HealthConfig(
        enabled=enabled,
        interval_seconds=interval_seconds,
        state_file=state_file,
        satdump_unit=satdump_unit,
        journal_lookback_seconds=lookback_seconds,
        journal_max_gap_seconds=max_gap_seconds,
        journal_recent_limit=recent_limit,
        error_keywords=[str(item).lower() for item in error_keywords],
        warning_keywords=[str(item).lower() for item in warning_keywords],
        satdump_api=api_cfg,
        signal_thresholds=thresholds,
        storage_mounts=storage_mounts,
        alert=alert_cfg,
    )


def _build_app_config(payload: Dict, *, base_dir: Path, config_path: Path) -> AppConfig:
    data_root_value = payload.get("data_root") or payload.get("root") or "."
    data_root = resolve_path(base_dir, data_root_value)

    state_dir_value = payload.get("state_dir") or payload.get("state") or "state"
    state_dir = resolve_path(base_dir, state_dir_value)
    try:
        ensure_directory(state_dir)
    except OSError as exc:
        fallback_state_dir = (base_dir / "state").resolve()
        try:
            ensure_directory(fallback_state_dir)
        except OSError:
            raise
        LOGGER.warning(
            "Unable to access configured state_dir %s (%s); using fallback %s",
            state_dir,
            exc,
            fallback_state_dir,
        )
        state_dir = fallback_state_dir

    dry_run = bool(payload.get("dry_run", False))
    log_level = str(payload.get("logging", {}).get("level", "INFO")).upper()

    retention_cfg = None
    if "retention" in payload:
        retention_cfg = _load_retention_config(payload["retention"], data_root)

    monitor_cfg = None
    if "monitor" in payload:
        monitor_cfg = _load_monitor_config(payload["monitor"], data_root, state_dir)

    health_cfg = None
    if "health" in payload:
        health_cfg = _load_health_config(payload["health"], state_dir)

    return AppConfig(
        config_path=config_path,
        data_root=data_root,
        state_dir=state_dir,
        log_level=log_level,
        dry_run=dry_run,
        retention=retention_cfg,
        monitor=monitor_cfg,
        health=health_cfg,
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


def load_health_app_config(common_config: str | Path, health_config: str | Path) -> AppConfig:
    common_path = Path(common_config).resolve()
    health_path = Path(health_config).resolve()

    payload = _load_json(common_path)
    payload = _merge_payload(payload, _load_json(health_path))

    if "health" not in payload:
        raise ValueError("Health configuration file must include a 'health' section")

    return _build_app_config(payload, base_dir=common_path.parent, config_path=health_path)
