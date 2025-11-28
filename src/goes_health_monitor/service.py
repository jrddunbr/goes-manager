"""Health monitoring service components."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Sequence
from urllib import error, request

from goes_manager.config import (
    AppConfig,
    HealthAlertConfig,
    HealthConfig,
    SatdumpApiConfig,
    SatdumpSignalThresholds,
)
from goes_manager.util import ensure_directory, save_state, utc_now

try:
    from systemd import journal
except Exception:  # noqa: BLE001
    journal = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)

SEVERITY_ORDER = {"ok": 0, "warning": 1, "error": 2}
PRIORITY_LABELS = {
    0: "emerg",
    1: "alert",
    2: "crit",
    3: "err",
    4: "warning",
    5: "notice",
    6: "info",
    7: "debug",
}

_STARTUP_RE = re.compile(r"Starting\s+SatDump\s+v(?P<version>[0-9][0-9A-Za-z.\-]*)")
_PLUGIN_ERROR_RE = re.compile(r"Error loading (?P<path>[^!]+)!\s*Error\s*:\s*(?P<detail>.+)")
_SNR_RE = re.compile(
    r"SNR\s*: ?(?P<snr>-?\d+(?:\.\d+)?)dB(?:,?\s*Peak\s*SNR\s*: ?(?P<peak>-?\d+(?:\.\d+)?))?",
    re.IGNORECASE,
)
_RTLSDR_ERROR_RE = re.compile(r"rtlsdr_\w+\s+failed", re.IGNORECASE)
_TRANSFER_STATUS_RE = re.compile(r"cb\s+transfer\s+status\s*:\s*(?P<code>\d+)", re.IGNORECASE)


@dataclass
class SatdumpLogInsight:
    timestamp: datetime
    category: str
    severity: str
    summary: str
    details: Dict[str, Any] = field(default_factory=dict)
    source_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "timestamp": self.timestamp.isoformat(),
            "category": self.category,
            "severity": self.severity,
            "summary": self.summary,
        }
        if self.details:
            payload["details"] = self.details
        if self.source_message:
            payload["message"] = self.source_message
        return payload


@dataclass
class JournalEvent:
    timestamp: datetime
    priority: int
    message: str
    cursor: Optional[str]
    identifier: Optional[str] = None

    def to_display(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority,
            "priority_label": PRIORITY_LABELS.get(self.priority, str(self.priority)),
            "identifier": self.identifier,
            "message": self.message,
        }


class SatdumpJournalReader:
    """Read SatDump logs from journald."""

    def __init__(self, unit: str, lookback_seconds: int) -> None:
        if journal is None:
            raise RuntimeError("python-systemd is required to read journald entries")

        self._reader = journal.Reader()
        self._reader.this_boot()
        self._reader.log_level(journal.LOG_DEBUG)
        self._reader.add_match(_SYSTEMD_UNIT=unit)

        if lookback_seconds > 0:
            since = utc_now() - timedelta(seconds=lookback_seconds)
            self._reader.seek_realtime(since)
        else:
            self._reader.seek_tail()
            self._reader.get_previous()

    def poll(self) -> List[JournalEvent]:
        events: List[JournalEvent] = []
        for entry in self._reader:  # type: ignore[not-an-iterable]
            try:
                events.append(self._build_event(entry))
            except Exception:  # noqa: BLE001
                LOGGER.exception("Failed to parse journal entry")
        return events


class SatdumpLogAnalyzer:
    """Decode SatDump log lines into actionable insights."""

    def __init__(self, thresholds: SatdumpSignalThresholds, insight_limit: int = 50) -> None:
        self._thresholds = thresholds
        self._insights: Deque[SatdumpLogInsight] = deque(maxlen=max(1, insight_limit))
        self._latest_by_category: Dict[str, SatdumpLogInsight] = {}
        self.version: Optional[str] = None
        self.last_start: Optional[datetime] = None
        self.last_signal: Optional[SatdumpLogInsight] = None

    def observe(self, event: JournalEvent) -> Optional[SatdumpLogInsight]:
        insight = self._decode(event)
        if insight is None:
            return None

        self._insights.append(insight)
        self._latest_by_category[insight.category] = insight

        if insight.category == "startup":
            self.version = insight.details.get("version") if insight.details else None
            self.last_start = insight.timestamp
        elif insight.category == "signal_quality":
            self.last_signal = insight

        return insight

    def evaluate(self, now: datetime, error_window: int, warning_window: int) -> tuple[str, List[str]]:
        severity = "ok"
        issues: List[str] = []

        for insight in self._latest_by_category.values():
            if insight.severity == "ok":
                continue

            age_seconds = (now - insight.timestamp).total_seconds()
            window = error_window if insight.severity == "error" else warning_window
            if age_seconds > window:
                continue

            if SEVERITY_ORDER[insight.severity] > SEVERITY_ORDER[severity]:
                severity = insight.severity

            detail = insight.details.get("detail") if insight.details else None
            summary = insight.summary
            if detail and detail not in summary:
                summary = f"{summary} ({detail})"
            if summary not in issues:
                issues.append(summary)

        return severity, issues

    def snapshot(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if self.version:
            payload["version"] = self.version
        if self.last_start:
            payload["last_start_time"] = self.last_start.isoformat()

        if self.last_signal:
            signal_data = {
                "timestamp": self.last_signal.timestamp.isoformat(),
                "severity": self.last_signal.severity,
            }
            signal_data.update(self.last_signal.details)
            payload["signal_quality"] = signal_data

        if self._insights:
            payload["recent_insights"] = [insight.to_dict() for insight in self._insights]

        active_alerts: List[Dict[str, Any]] = []
        for insight in self._latest_by_category.values():
            if insight.severity == "ok":
                continue
            entry: Dict[str, Any] = {
                "category": insight.category,
                "severity": insight.severity,
                "summary": insight.summary,
                "timestamp": insight.timestamp.isoformat(),
            }
            if insight.details:
                entry["details"] = insight.details
            active_alerts.append(entry)

        if active_alerts:
            payload["active_alerts"] = active_alerts

        return payload

    def _decode(self, event: JournalEvent) -> Optional[SatdumpLogInsight]:
        message = event.message.strip()
        if not message:
            return None

        startup_match = _STARTUP_RE.search(message)
        if startup_match:
            version = startup_match.group("version")
            return SatdumpLogInsight(
                timestamp=event.timestamp,
                category="startup",
                severity="ok",
                summary=f"SatDump started (v{version})",
                details={"version": version},
                source_message=message,
            )

        plugin_match = _PLUGIN_ERROR_RE.search(message)
        if plugin_match:
            raw_path = plugin_match.group("path").strip()
            detail = plugin_match.group("detail").strip()
            plugin = Path(raw_path).stem
            summary = f"Plugin {plugin} failed to load"
            return SatdumpLogInsight(
                timestamp=event.timestamp,
                category="plugin_load_failure",
                severity="error",
                summary=summary,
                details={"plugin": plugin, "path": raw_path, "detail": detail},
                source_message=message,
            )

        snr_match = _SNR_RE.search(message)
        if snr_match:
            try:
                snr_value = float(snr_match.group("snr"))
            except (TypeError, ValueError):
                snr_value = None
            peak_raw = snr_match.group("peak")
            peak_value: Optional[float]
            try:
                peak_value = float(peak_raw) if peak_raw is not None else None
            except (TypeError, ValueError):
                peak_value = None

            if snr_value is None and peak_value is None:
                return None

            severity = "ok"
            flags: List[str] = []

            if snr_value is not None:
                if snr_value < self._thresholds.min_snr_error:
                    severity = "error"
                    flags.append("snr")
                elif snr_value < self._thresholds.min_snr_warning and severity != "error":
                    severity = "warning"
                    flags.append("snr")

            if peak_value is not None:
                if peak_value < self._thresholds.min_peak_snr_error:
                    severity = "error"
                    if "peak_snr" not in flags:
                        flags.append("peak_snr")
                elif peak_value < self._thresholds.min_peak_snr_warning and severity != "error":
                    severity = "warning"
                    if "peak_snr" not in flags:
                        flags.append("peak_snr")

            summary_parts = ["Signal SNR"]
            metrics_desc: List[str] = []
            if snr_value is not None:
                metrics_desc.append(f"{snr_value:.2f} dB")
            if peak_value is not None:
                metrics_desc.append(f"peak {peak_value:.2f} dB")
            summary = " ".join(summary_parts) + (" (" + ", ".join(metrics_desc) + ")" if metrics_desc else "")

            details: Dict[str, Any] = {}
            if snr_value is not None:
                details["snr"] = snr_value
            if peak_value is not None:
                details["peak_snr"] = peak_value
            if flags:
                details["flags"] = flags
                thresholds: Dict[str, Any] = {}
                if "snr" in flags:
                    thresholds["snr"] = {
                        "warning": self._thresholds.min_snr_warning,
                        "error": self._thresholds.min_snr_error,
                    }
                if "peak_snr" in flags:
                    thresholds["peak_snr"] = {
                        "warning": self._thresholds.min_peak_snr_warning,
                        "error": self._thresholds.min_peak_snr_error,
                    }
                if thresholds:
                    details["thresholds"] = thresholds

            return SatdumpLogInsight(
                timestamp=event.timestamp,
                category="signal_quality",
                severity=severity,
                summary=summary,
                details=details,
                source_message=message,
            )

        lowered = message.lower()
        if _RTLSDR_ERROR_RE.search(message):
            return SatdumpLogInsight(
                timestamp=event.timestamp,
                category="sdr_io",
                severity="error",
                summary="RTL-SDR communication failure",
                details={"message": message},
                source_message=message,
            )

        transfer_match = _TRANSFER_STATUS_RE.search(message)
        if transfer_match:
            code_text = transfer_match.group("code")
            try:
                code = int(code_text)
            except (TypeError, ValueError):
                code = None
            severity = "warning" if code and code != 0 else "ok"
            if severity != "ok":
                summary = "RTL-SDR transfer aborted"
                details: Dict[str, Any] = {"code": code}
                return SatdumpLogInsight(
                    timestamp=event.timestamp,
                    category="sdr_transfer",
                    severity=severity,
                    summary=summary,
                    details=details,
                    source_message=message,
                )

        if "pll not locked" in lowered:
            return SatdumpLogInsight(
                timestamp=event.timestamp,
                category="tuner_lock",
                severity="error",
                summary="Tuner PLL not locked",
                details={"message": message},
                source_message=message,
            )

        return None


@dataclass
class SatdumpApiEvaluation:
    severity: str
    issues: List[str]
    metrics: Dict[str, Any]
    evaluated_at: datetime
    messages: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "issues": self.issues,
            "evaluated_at": self.evaluated_at.isoformat(),
            "metrics": self.metrics,
            "messages": self.messages,
        }


class SatdumpApiEvaluator:
    """Analyse SatDump API responses for signal quality issues."""

    def __init__(self, thresholds: SatdumpSignalThresholds) -> None:
        self._thresholds = thresholds

    def evaluate(self, data: Dict[str, Any], evaluated_at: datetime) -> SatdumpApiEvaluation:
        severity = "ok"
        issues: List[str] = []
        messages: List[str] = []
        metrics: Dict[str, Any] = {}
        component_levels: Dict[str, str] = {}

        def flag(level: str, message: str, component: Optional[str] = None) -> None:
            nonlocal severity
            if level not in SEVERITY_ORDER:
                return
            if message not in issues:
                issues.append(message)
            if SEVERITY_ORDER[level] > SEVERITY_ORDER.get(severity, 0):
                severity = level
            if component:
                current = component_levels.get(component, "ok")
                if SEVERITY_ORDER[level] > SEVERITY_ORDER.get(current, 0):
                    component_levels[component] = level

        demod = data.get("psk_demod") or data.get("pskDemod") or {}
        if isinstance(demod, dict) and demod:
            demod_metrics: Dict[str, Any] = {}
            snr_value = self._get_float(demod, "snr")
            peak_snr = self._get_float(demod, "peak_snr", "peakSNR")
            frequency = self._get_float(demod, "freq", "frequency")

            if snr_value is not None:
                demod_metrics["snr"] = snr_value
                snr_level = "ok"
                if snr_value < self._thresholds.min_snr_error:
                    flag(
                        "error",
                        f"Demod SNR {snr_value:.2f} dB below error threshold {self._thresholds.min_snr_error:.2f} dB",
                        component="demod",
                    )
                    snr_level = "error"
                elif snr_value < self._thresholds.min_snr_warning:
                    flag(
                        "warning",
                        f"Demod SNR {snr_value:.2f} dB below warning threshold {self._thresholds.min_snr_warning:.2f} dB",
                        component="demod",
                    )
                    snr_level = "warning"
                messages.append(
                    (
                        "Demod SNR {value:.2f} dB (warning < {warn:.2f}, error < {err:.2f}) -> {level}"
                    ).format(
                        value=snr_value,
                        warn=self._thresholds.min_snr_warning,
                        err=self._thresholds.min_snr_error,
                        level=snr_level.upper(),
                    )
                )

            if peak_snr is not None:
                demod_metrics["peak_snr"] = peak_snr
                peak_level = "ok"
                if peak_snr < self._thresholds.min_peak_snr_error:
                    flag(
                        "error",
                        (
                            "Demod peak SNR "
                            f"{peak_snr:.2f} dB below error threshold {self._thresholds.min_peak_snr_error:.2f} dB"
                        ),
                        component="demod",
                    )
                    peak_level = "error"
                elif peak_snr < self._thresholds.min_peak_snr_warning:
                    flag(
                        "warning",
                        (
                            "Demod peak SNR "
                            f"{peak_snr:.2f} dB below warning threshold {self._thresholds.min_peak_snr_warning:.2f} dB"
                        ),
                        component="demod",
                    )
                    peak_level = "warning"
                messages.append(
                    (
                        "Demod peak SNR {value:.2f} dB (warning < {warn:.2f}, error < {err:.2f}) -> {level}"
                    ).format(
                        value=peak_snr,
                        warn=self._thresholds.min_peak_snr_warning,
                        err=self._thresholds.min_peak_snr_error,
                        level=peak_level.upper(),
                    )
                )

            if frequency is not None:
                demod_metrics["frequency"] = frequency
                messages.append(f"Demod tuned frequency {frequency:.3f} MHz")

            if demod_metrics:
                metrics["demod"] = demod_metrics

        decoder = (
            data.get("ccsds_conv_concat_decoder")
            or data.get("ccsdsConvConcatDecoder")
            or data.get("decoder")
            or {}
        )
        if isinstance(decoder, dict) and decoder:
            decoder_metrics: Dict[str, Any] = {}
            deframer_lock = self._get_bool(decoder, "deframer_lock", "deframerLock")
            viterbi_lock = self._get_bool(decoder, "viterbi_lock", "viterbiLock")
            viterbi_ber = self._get_float(decoder, "viterbi_ber", "viterbiBer")
            rs_avg = self._get_float(decoder, "rs_avg", "rsAvg")

            if deframer_lock is not None:
                decoder_metrics["deframer_lock"] = deframer_lock
                if self._thresholds.require_deframer_lock and deframer_lock is False:
                    flag("error", "Decoder deframer not locked", component="decoder")
                messages.append(
                    "Decoder deframer " + ("locked" if deframer_lock else "unlocked")
                )

            if viterbi_lock is not None:
                decoder_metrics["viterbi_lock"] = viterbi_lock
                if self._thresholds.require_viterbi_lock and viterbi_lock is False:
                    flag("error", "Decoder viterbi not locked", component="decoder")
                messages.append(
                    "Decoder viterbi " + ("locked" if viterbi_lock else "unlocked")
                )

            if viterbi_ber is not None:
                decoder_metrics["viterbi_ber"] = viterbi_ber
                ber_level = "ok"
                if viterbi_ber > self._thresholds.max_viterbi_ber_error:
                    flag(
                        "error",
                        (
                            "Viterbi BER "
                            f"{viterbi_ber:.3f} above error threshold {self._thresholds.max_viterbi_ber_error:.3f}"
                        ),
                        component="decoder",
                    )
                    ber_level = "error"
                elif viterbi_ber > self._thresholds.max_viterbi_ber_warning:
                    flag(
                        "warning",
                        (
                            "Viterbi BER "
                            f"{viterbi_ber:.3f} above warning threshold {self._thresholds.max_viterbi_ber_warning:.3f}"
                        ),
                        component="decoder",
                    )
                    ber_level = "warning"
                messages.append(
                    (
                        "Viterbi BER {value:.4f} (warning > {warn:.3f}, error > {err:.3f}) -> {level}"
                    ).format(
                        value=viterbi_ber,
                        warn=self._thresholds.max_viterbi_ber_warning,
                        err=self._thresholds.max_viterbi_ber_error,
                        level=ber_level.upper(),
                    )
                )

            if rs_avg is not None:
                decoder_metrics["rs_avg"] = rs_avg
                messages.append(f"Reed-Solomon average {rs_avg}")

            if decoder_metrics:
                metrics["decoder"] = decoder_metrics

        for component, level in component_levels.items():
            if component in metrics:
                metrics[component]["severity"] = level

        for component_metrics in metrics.values():
            component_metrics.setdefault("severity", "ok")

        if not issues and not messages:
            messages.append("SatDump API returned no telemetry")

        return SatdumpApiEvaluation(
            severity=severity,
            issues=issues,
            metrics=metrics,
            evaluated_at=evaluated_at,
            messages=messages,
        )

    @staticmethod
    def _get_float(container: Dict[str, Any], *keys: str) -> Optional[float]:
        for key in keys:
            if key in container:
                try:
                    return float(container[key])
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    def _get_bool(container: Dict[str, Any], *keys: str) -> Optional[bool]:
        for key in keys:
            if key not in container:
                continue
            value = container[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"1", "true", "yes", "on"}:
                    return True
                if lowered in {"0", "false", "no", "off"}:
                    return False
        return None


@dataclass
class MountProbe:
    exists: bool
    is_mount: bool
    device: Optional[int]
    readable: bool
    writable: bool


class MountWatcher:
    """Track availability of critical storage mount points."""

    def __init__(self, paths: Sequence[Path], probe: Optional[Callable[[Path], MountProbe]] = None) -> None:
        unique_paths = []
        seen = set()
        for path in paths:
            resolved = path if isinstance(path, Path) else Path(path)
            resolved = resolved.resolve(strict=False)
            if resolved in seen:
                continue
            seen.add(resolved)
            unique_paths.append(resolved)

        self._probe_func = probe or self._default_probe
        self._targets: List[Dict[str, Any]] = []
        for path in unique_paths:
            baseline = self._probe(path)
            self._targets.append({"path": path, "baseline": baseline})

    def evaluate(self, now: datetime) -> tuple[str, List[str], List[Dict[str, Any]]]:
        severity = "ok"
        issues: List[str] = []
        report: List[Dict[str, Any]] = []

        for target in self._targets:
            path: Path = target["path"]
            baseline: MountProbe = target["baseline"]
            current = self._probe(path)

            entry: Dict[str, Any] = {
                "path": path.as_posix(),
                "checked_at": now.isoformat(),
                "exists": current.exists,
                "is_mount": current.is_mount,
                "readable": current.readable,
                "writable": current.writable,
            }
            if current.device is not None:
                entry["device"] = current.device

            entry_severity = "ok"
            detail: Optional[str] = None

            if not current.exists:
                entry_severity = "error"
                detail = "missing"
            elif baseline.exists and baseline.is_mount and not current.is_mount:
                entry_severity = "error"
                detail = "not mounted"
            elif not current.writable:
                entry_severity = "error"
                detail = "read-only"
            elif (
                baseline.device is not None
                and current.device is not None
                and current.device != baseline.device
            ):
                entry_severity = "warning"
                detail = "device changed"

            if entry_severity != "ok" and detail:
                entry["detail"] = detail
                description = f"Storage {path} {detail}"
                if description not in issues:
                    issues.append(description)

            entry["severity"] = entry_severity
            report.append(entry)

            if SEVERITY_ORDER[entry_severity] > SEVERITY_ORDER[severity]:
                severity = entry_severity

            if current.exists and current.is_mount and current.device is not None:
                target["baseline"] = current

        return severity, issues, report

    def _probe(self, path: Path) -> MountProbe:
        try:
            return self._probe_func(path)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed to probe mount path %s", path)
            return MountProbe(False, False, None, False, False)

    @staticmethod
    def _default_probe(path: Path) -> MountProbe:
        exists = path.exists()
        is_mount = path.is_mount() if exists else False
        readable = os.access(path, os.R_OK) if exists else False
        writable = os.access(path, os.W_OK | os.X_OK) if exists else False
        device: Optional[int] = None
        if exists:
            try:
                device = path.stat().st_dev
            except OSError:
                device = None
        return MountProbe(exists, is_mount, device, readable, writable)


class SystemdUnitWatcher:
    """Check the active state of a systemd unit."""

    def __init__(self, unit: str, timeout_seconds: float = 2.0) -> None:
        self._unit = unit
        self._timeout = timeout_seconds

    def evaluate(self, now: datetime) -> tuple[str, List[str], Dict[str, Any]]:
        info: Dict[str, Any] = {"unit": self._unit, "checked_at": now.isoformat()}
        issues: List[str] = []
        severity = "ok"

        try:
            completed = subprocess.run(
                ["systemctl", "show", self._unit, "--property", "ActiveState,SubState,Result", "--no-page"],
                capture_output=True,
                text=True,
                check=True,
                timeout=self._timeout,
            )
        except FileNotFoundError:
            issues.append("systemctl not available; cannot verify SatDump service state")
            severity = "warning"
            return severity, issues, info
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            issues.append(f"systemctl query failed: {detail}")
            severity = "warning"
            return severity, issues, info
        except Exception as exc:  # noqa: BLE001
            issues.append(f"systemctl invocation error: {exc}")
            severity = "warning"
            return severity, issues, info

        for line in completed.stdout.splitlines():
            key, _, value = line.partition("=")
            if not key:
                continue
            info[key.strip().lower()] = value.strip()

        active_state = info.get("activestate", "unknown")
        sub_state = info.get("substate", "unknown")
        result = info.get("result", "unknown")

        if active_state != "active" or sub_state not in {"running", "listening"}:
            severity = "error"
            issues.append(
                f"SatDump systemd unit inactive (active={active_state}, sub={sub_state}, result={result})"
            )

        info["severity"] = severity
        if issues:
            info["issues"] = issues
        return severity, issues, info
    @staticmethod
    def _get_bool(container: Dict[str, Any], *keys: str) -> Optional[bool]:
        for key in keys:
            if key not in container:
                continue
            value = container[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"1", "true", "yes", "on"}:
                    return True
                if lowered in {"0", "false", "no", "off"}:
                    return False
        return None
    @staticmethod
    def _build_event(entry: Dict[str, Any]) -> JournalEvent:
        timestamp_raw = entry.get("__REALTIME_TIMESTAMP")
        if isinstance(timestamp_raw, datetime):
            timestamp = timestamp_raw.astimezone(timezone.utc)
        elif timestamp_raw is None:
            timestamp = utc_now()
        else:
            # Journald returns microseconds as an int
            timestamp = datetime.fromtimestamp(float(timestamp_raw) / 1_000_000, tz=timezone.utc)

        priority = int(entry.get("PRIORITY", 6))
        message = str(entry.get("MESSAGE", "")).strip()
        cursor = entry.get("__CURSOR")
        identifier = entry.get("SYSLOG_IDENTIFIER") or entry.get("SYSLOG_IDENTITY") or entry.get("UNIT")

        return JournalEvent(
            timestamp=timestamp,
            priority=priority,
            message=message,
            cursor=cursor,
            identifier=str(identifier) if identifier else None,
        )


@dataclass
class SatdumpJournalState:
    max_gap_seconds: int
    recent_limit: int
    error_window_seconds: int
    warning_window_seconds: int
    error_keywords: Sequence[str]
    warning_keywords: Sequence[str]
    signal_thresholds: SatdumpSignalThresholds = field(default_factory=SatdumpSignalThresholds)
    total_messages: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    last_message_time: Optional[datetime] = None
    last_error_time: Optional[datetime] = None
    last_warning_time: Optional[datetime] = None
    recent_messages: Deque[Dict[str, Any]] = field(init=False)
    recent_errors: Deque[Dict[str, Any]] = field(init=False)
    issues: List[str] = field(default_factory=list)
    _analyzer: SatdumpLogAnalyzer = field(init=False)

    def __post_init__(self) -> None:
        limit = max(1, self.recent_limit)
        self.error_window_seconds = max(60, self.error_window_seconds)
        self.warning_window_seconds = max(60, self.warning_window_seconds)
        self.recent_messages = deque(maxlen=limit)
        self.recent_errors = deque(maxlen=min(limit, 20))
        self._analyzer = SatdumpLogAnalyzer(self.signal_thresholds, insight_limit=limit)

    def ingest(self, events: Iterable[JournalEvent]) -> None:
        for event in events:
            self.total_messages += 1
            self.last_message_time = event.timestamp
            display = event.to_display()
            self.recent_messages.append(display)

            lowered = event.message.lower()
            priority = event.priority

            is_error = priority <= 3 or any(keyword in lowered for keyword in self.error_keywords)
            is_warning = priority == 4 or any(keyword in lowered for keyword in self.warning_keywords)

            if is_error:
                self.total_errors += 1
                self.last_error_time = event.timestamp
                self.recent_errors.append(display)
            elif is_warning:
                self.total_warnings += 1
                self.last_warning_time = event.timestamp

            self._analyzer.observe(event)

    def evaluate(self, now: datetime) -> str:
        severity = "ok"
        self.issues.clear()

        if self.last_error_time and (now - self.last_error_time).total_seconds() <= self.error_window_seconds:
            severity = "error"
            recent = self.recent_errors[-1] if self.recent_errors else None
            if recent:
                self.issues.append(f"Recent error: {recent['message']}")
        elif self.last_warning_time and (now - self.last_warning_time).total_seconds() <= self.warning_window_seconds:
            severity = "warning"
            if self.recent_messages:
                last = self.recent_messages[-1]
                self.issues.append(f"Recent warning: {last['message']}")

        if self.last_message_time is None:
            self.issues.append("No SatDump logs observed in current boot")
            severity = max(severity, "warning", key=lambda level: SEVERITY_ORDER[level])
        else:
            gap = (now - self.last_message_time).total_seconds()
            if gap > self.max_gap_seconds:
                detail = f"SatDump log gap {int(gap)}s exceeds threshold {self.max_gap_seconds}s"
                self.issues.append(detail)
                new_level = "error" if gap > self.max_gap_seconds * 2 else "warning"
                severity = max(severity, new_level, key=lambda level: SEVERITY_ORDER[level])

        analyzer_severity, analyzer_issues = self._analyzer.evaluate(now, self.error_window_seconds, self.warning_window_seconds)
        if analyzer_issues:
            for issue in analyzer_issues:
                if issue not in self.issues:
                    self.issues.append(issue)
        severity = max(severity, analyzer_severity, key=lambda level: SEVERITY_ORDER[level])

        return severity

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "total_messages": self.total_messages,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "last_message_time": self.last_message_time.isoformat() if self.last_message_time else None,
            "last_error_time": self.last_error_time.isoformat() if self.last_error_time else None,
            "last_warning_time": self.last_warning_time.isoformat() if self.last_warning_time else None,
            "recent_messages": list(self.recent_messages),
            "recent_errors": list(self.recent_errors),
        }
        decoded = self._analyzer.snapshot()
        if decoded:
            payload["decoded"] = decoded
        return payload


@dataclass
class HealthSnapshot:
    generated_at: datetime
    status: str
    issues: List[str]
    satdump: Dict[str, Any]
    satdump_api: Optional[Dict[str, Any]] = None
    storage: Optional[Dict[str, Any]] = None
    components: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "generated_at": self.generated_at.isoformat(),
            "status": self.status,
            "issues": self.issues,
            "satdump": self.satdump,
        }
        if self.satdump_api is not None:
            payload["satdump_api"] = self.satdump_api
        if self.storage is not None:
            payload["storage"] = self.storage
        if self.components:
            payload["components"] = self.components
        return payload


class SatdumpApiClient:
    """Fetch status details from the local SatDump API."""

    def __init__(self, config: SatdumpApiConfig) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._endpoint = config.status_endpoint if config.status_endpoint.startswith("/") else f"/{config.status_endpoint}"
        self._timeout = config.timeout_seconds

    def fetch_status(self) -> Dict[str, Any]:
        url = f"{self._base_url}{self._endpoint}"
        try:
            req = request.Request(url, headers={"Accept": "application/json"})
            with request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read()
                if not body:
                    return {"status": "empty-response"}
                try:
                    data = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError as exc:  # noqa: TRY003
                    return {"status": "invalid-json", "detail": str(exc)}
                return {"status": "ok", "data": data}
        except error.HTTPError as exc:
            return {"status": "http-error", "code": exc.code, "detail": exc.reason}
        except Exception as exc:  # noqa: BLE001
            return {"status": "unreachable", "detail": str(exc)}


class AlertDispatcher:
    """Dispatch alerts for degraded health states using Discord webhooks."""

    def __init__(self, config: Optional[HealthAlertConfig]) -> None:
        self._config = config
        self._last_status = "ok"
        self._last_alert_at: Optional[datetime] = None

    def notify(self, snapshot: HealthSnapshot) -> None:
        if not self._config:
            return

        min_required = self._config.min_severity.lower()
        if min_required not in SEVERITY_ORDER:
            LOGGER.warning("Unknown alert severity threshold '%s', defaulting to warning", min_required)
            min_required = "warning"

        current_level = snapshot.status
        if SEVERITY_ORDER[current_level] < SEVERITY_ORDER[min_required]:
            self._last_status = current_level
            return

        should_alert = False
        if SEVERITY_ORDER[current_level] > SEVERITY_ORDER.get(self._last_status, 0):
            should_alert = True
        elif SEVERITY_ORDER[current_level] >= SEVERITY_ORDER[min_required]:
            if self._last_alert_at is None:
                should_alert = True
            else:
                elapsed = (utc_now() - self._last_alert_at).total_seconds()
                if elapsed >= self._config.cooldown_seconds:
                    should_alert = True

        if not should_alert:
            self._last_status = current_level
            return

        content_lines = [
            f"GOES health status: **{current_level.upper()}**",
        ]
        if snapshot.issues:
            for issue in snapshot.issues[:5]:
                content_lines.append(f"• {issue}")
        payload = {
            "content": "\n".join(content_lines),
        }
        if self._config.username:
            payload["username"] = self._config.username

        try:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                self._config.webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "GoesHealthMonitor/1.0"},
            )
            with request.urlopen(req, timeout=5.0):
                pass
            self._last_alert_at = utc_now()
            LOGGER.info("Sent health alert (status=%s)", current_level)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed to dispatch health alert")

        self._last_status = current_level


class HealthMonitor:
    """Coordinate journal ingestion, optional API polling, and state publication."""

    def __init__(self, app_config: AppConfig, health_config: HealthConfig) -> None:
        self._app_config = app_config
        self._config = health_config

        if not self._config.enabled:
            LOGGER.warning("Health monitor created with enabled=False; run_once will be a no-op")

        self._journal_reader: Optional[SatdumpJournalReader] = None
        if journal is None:
            LOGGER.error("python-systemd not available; health monitoring requires journald access")
        else:
            try:
                self._journal_reader = SatdumpJournalReader(
                    self._config.satdump_unit, self._config.journal_lookback_seconds
                )
            except Exception:  # noqa: BLE001
                LOGGER.exception("Failed to initialise journald reader")
                self._journal_reader = None

        error_window = max(self._config.journal_lookback_seconds, self._config.journal_max_gap_seconds)
        warning_window = max(int(self._config.journal_lookback_seconds / 2), 120)

        self._journal_state = SatdumpJournalState(
            max_gap_seconds=self._config.journal_max_gap_seconds,
            recent_limit=self._config.journal_recent_limit,
            error_window_seconds=error_window,
            warning_window_seconds=warning_window,
            error_keywords=self._config.error_keywords,
            warning_keywords=self._config.warning_keywords,
            signal_thresholds=self._config.signal_thresholds,
        )

        self._api_client = SatdumpApiClient(self._config.satdump_api) if self._config.satdump_api else None
        self._api_evaluator = (
            SatdumpApiEvaluator(self._config.signal_thresholds) if self._config.satdump_api else None
        )
        self._unit_watcher = SystemdUnitWatcher(self._config.satdump_unit) if self._config.satdump_unit else None

        monitored_set = {path.resolve(strict=False) for path in self._config.storage_mounts}
        data_root_parent = self._app_config.data_root.parent
        state_dir_parent = self._app_config.state_dir.parent
        for candidate in (
            self._app_config.data_root,
            data_root_parent,
            state_dir_parent,
        ):
            if candidate != Path("/"):
                monitored_set.add(candidate.resolve(strict=False))

        monitored_mounts = sorted(monitored_set, key=lambda p: p.as_posix())
        self._mount_watcher = MountWatcher(monitored_mounts) if monitored_mounts else None
        self._alerts = AlertDispatcher(self._config.alert)

        self._fallback_state_file = Path("/var/tmp/goes_health_monitor/health.json")
        self._latest_state_path: Path = self._config.state_file

        ensure_directory(self._config.state_file.parent)

    @staticmethod
    def _combine_status(current: str, new: str) -> str:
        if new not in SEVERITY_ORDER:
            return current
        if current not in SEVERITY_ORDER:
            return new
        return max(current, new, key=lambda level: SEVERITY_ORDER[level])

    def _persist_state(self, snapshot: HealthSnapshot) -> tuple[str, List[str]]:
        payload = snapshot.to_dict()
        storage_section = payload.setdefault("storage", {})
        state_mapping = {
            "primary": self._config.state_file.as_posix(),
            "active": self._config.state_file.as_posix(),
        }
        storage_section["state_file"] = state_mapping
        if snapshot.storage is None:
            snapshot.storage = {"state_file": dict(state_mapping)}
        else:
            snapshot.storage["state_file"] = dict(state_mapping)

        messages: List[str] = []
        try:
            save_state(self._config.state_file, payload)
            self._latest_state_path = self._config.state_file
            messages.append(f"State saved to {self._config.state_file.as_posix()}")
            return "ok", messages
        except OSError as exc:
            message = f"Primary health state path unavailable ({self._config.state_file}): {exc}"
            if message not in snapshot.issues:
                snapshot.issues.append(message)
                messages.append(message)
            LOGGER.warning(message)

        try:
            ensure_directory(self._fallback_state_file.parent)
            state_mapping["active"] = self._fallback_state_file.as_posix()
            storage_section["state_file"] = state_mapping
            if snapshot.storage is not None:
                snapshot.storage["state_file"] = dict(state_mapping)
            save_state(self._fallback_state_file, payload)
            self._latest_state_path = self._fallback_state_file
            fallback_msg = f"Health state persisted to fallback path {self._fallback_state_file}"
            if fallback_msg not in snapshot.issues:
                snapshot.issues.append(fallback_msg)
                messages.append(fallback_msg)
            return "warning", messages
        except OSError as exc:  # noqa: BLE001
            failure_msg = f"Failed to persist fallback health state: {exc}"
            LOGGER.error(failure_msg)
            if failure_msg not in snapshot.issues:
                snapshot.issues.append(failure_msg)
                messages.append(failure_msg)
            return "error", messages

    def run_once(self) -> HealthSnapshot:
        now = utc_now()

        if not self._config.enabled:
            snapshot = HealthSnapshot(
                generated_at=now,
                status="disabled",
                issues=["Health monitor disabled via configuration"],
                satdump={"active": False},
                components={
                    "health_monitor": {
                        "status": "disabled",
                        "issues": ["Health monitor disabled via configuration"],
                    }
                },
            )
            self._persist_state(snapshot)
            return snapshot

        components: Dict[str, Dict[str, Any]] = {}
        issues: List[str] = []

        # SatDump journal evaluation
        journal_issues: List[str] = []
        if self._journal_reader is None:
            journal_status = "error"
            journal_issues.append("Journald reader unavailable")
        else:
            events = self._journal_reader.poll()
            if events:
                LOGGER.debug("Processed %s new journal events", len(events))
            self._journal_state.ingest(events)
            journal_status = self._journal_state.evaluate(now)
            journal_issues.extend(self._journal_state.issues)

        satdump_payload = self._journal_state.to_dict()
        if self._journal_reader is None and "Journald reader unavailable" not in journal_issues:
            journal_issues.append("Journald reader unavailable")

        journal_messages: List[str] = []
        decoded_data = satdump_payload.get("decoded") or {}
        total_messages = satdump_payload.get("total_messages")
        total_errors = satdump_payload.get("total_errors")
        if total_messages is not None:
            journal_messages.append(f"SatDump journal messages observed: {total_messages}")
        if total_errors:
            journal_messages.append(f"Errors observed: {total_errors}")
        last_signal = decoded_data.get("signal_quality") if isinstance(decoded_data, dict) else None
        if isinstance(last_signal, dict):
            signal_parts: List[str] = []
            snr = last_signal.get("snr")
            if snr is not None:
                signal_parts.append(f"SNR {snr:.2f} dB")
            peak = last_signal.get("peak_snr")
            if peak is not None:
                signal_parts.append(f"peak {peak:.2f} dB")
            severity_label = last_signal.get("severity", "unknown")
            if signal_parts:
                journal_messages.append(
                    f"Last signal quality ({severity_label}): {', '.join(signal_parts)}"
                )
        if not journal_messages:
            journal_messages.append("No SatDump signal metrics available")

        components["satdump_journal"] = {
            "status": journal_status,
            "issues": journal_issues,
            "messages": journal_messages,
        }

        status = journal_status if journal_status in SEVERITY_ORDER else "ok"
        for issue in journal_issues:
            if issue not in issues:
                issues.append(issue)

        # Systemd unit watcher
        if self._unit_watcher:
            unit_severity, unit_issues, unit_report = self._unit_watcher.evaluate(now)
            if unit_issues:
                for issue in unit_issues:
                    if issue not in issues:
                        issues.append(issue)
            status = self._combine_status(status, unit_severity)
            satdump_payload["service"] = unit_report
            unit_messages: List[str] = []
            if isinstance(unit_report, dict):
                active_state = unit_report.get("activestate")
                sub_state = unit_report.get("substate")
                if active_state or sub_state:
                    unit_messages.append(
                        f"systemd active={active_state or 'unknown'} sub={sub_state or 'unknown'}"
                    )
            components["systemd_unit"] = {
                "status": unit_severity,
                "issues": unit_issues,
                "messages": unit_messages,
            }
        else:
            components["systemd_unit"] = {
                "status": "disabled",
                "issues": ["Systemd unit watcher disabled"],
                "messages": ["No systemd status checks executed"],
            }

        # Storage watcher
        storage_payload: Optional[Dict[str, Any]] = None
        if self._mount_watcher:
            storage_severity, storage_issues, storage_report = self._mount_watcher.evaluate(now)
            if storage_issues:
                for issue in storage_issues:
                    if issue not in issues:
                        issues.append(issue)
            status = self._combine_status(status, storage_severity)
            storage_payload = {"paths": storage_report}
            storage_messages = []
            for entry in storage_report:
                path = entry.get("path")
                sev = entry.get("severity")
                detail = entry.get("detail")
                storage_messages.append(
                    f"{path}: {sev}" + (f" ({detail})" if detail else "")
                )
            components["storage"] = {
                "status": storage_severity,
                "issues": storage_issues,
                "messages": storage_messages,
            }
        else:
            components["storage"] = {
                "status": "disabled",
                "issues": ["Storage mount watcher disabled"],
                "messages": ["No storage mounts configured for monitoring"],
            }

        # SatDump API
        api_payload: Optional[Dict[str, Any]] = None
        if self._api_client:
            api_payload = self._api_client.fetch_status()
            api_status = str(api_payload.get("status", "unknown")).lower()
            if api_status == "ok":
                data = api_payload.get("data")
                if self._api_evaluator and isinstance(data, dict):
                    evaluation = self._api_evaluator.evaluate(data, now)
                    api_payload["analysis"] = evaluation.to_dict()
                    status = self._combine_status(status, evaluation.severity)
                    for issue in evaluation.issues:
                        if issue not in issues:
                            issues.append(issue)
                    components["satdump_api"] = {
                        "status": evaluation.severity,
                        "issues": evaluation.issues,
                        "messages": evaluation.messages,
                    }
                else:
                    components["satdump_api"] = {
                        "status": "warning",
                        "issues": ["SatDump API returned unexpected payload"],
                        "messages": ["SatDump API response missing expected structure"],
                    }
            else:
                issue_message = f"SatDump API {api_status}"
                detail = api_payload.get("detail") or api_payload.get("code") or api_payload.get("error")
                if detail:
                    issue_message = f"{issue_message}: {detail}"
                if issue_message not in issues:
                    issues.append(issue_message)
                degraded_level = "error" if api_status in {"unreachable", "timeout"} else "warning"
                if api_status == "http-error":
                    code = api_payload.get("code")
                    if isinstance(code, int) and code >= 500:
                        degraded_level = "error"
                status = self._combine_status(status, degraded_level)
                components["satdump_api"] = {
                    "status": degraded_level,
                    "issues": [issue_message],
                    "messages": [issue_message],
                }
        else:
            components["satdump_api"] = {
                "status": "disabled",
                "issues": ["SatDump API polling disabled in configuration"],
                "messages": ["Not polling SatDump API"],
            }

        snapshot = HealthSnapshot(
            generated_at=now,
            status=status,
            issues=issues,
            satdump=satdump_payload,
            satdump_api=api_payload,
            storage=storage_payload,
            components=components,
        )

        persist_level, persist_messages = self._persist_state(snapshot)
        status = self._combine_status(status, persist_level)
        snapshot.status = status
        components["state_persistence"] = {
            "status": persist_level,
            "issues": [] if persist_level == "ok" else list(persist_messages),
            "messages": persist_messages,
        }

        self._alerts.notify(snapshot)

        return snapshot
