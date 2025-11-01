"""Health monitoring service components."""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence
from urllib import error, request

from goes_manager.config import AppConfig, HealthAlertConfig, HealthConfig, SatdumpApiConfig
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
    total_messages: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    last_message_time: Optional[datetime] = None
    last_error_time: Optional[datetime] = None
    last_warning_time: Optional[datetime] = None
    recent_messages: Deque[Dict[str, Any]] = field(init=False)
    recent_errors: Deque[Dict[str, Any]] = field(init=False)
    issues: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        limit = max(1, self.recent_limit)
        self.error_window_seconds = max(60, self.error_window_seconds)
        self.warning_window_seconds = max(60, self.warning_window_seconds)
        self.recent_messages = deque(maxlen=limit)
        self.recent_errors = deque(maxlen=min(limit, 20))

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

        return severity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_messages": self.total_messages,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "last_message_time": self.last_message_time.isoformat() if self.last_message_time else None,
            "last_error_time": self.last_error_time.isoformat() if self.last_error_time else None,
            "last_warning_time": self.last_warning_time.isoformat() if self.last_warning_time else None,
            "recent_messages": list(self.recent_messages),
            "recent_errors": list(self.recent_errors),
        }


@dataclass
class HealthSnapshot:
    generated_at: datetime
    status: str
    issues: List[str]
    satdump: Dict[str, Any]
    satdump_api: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "generated_at": self.generated_at.isoformat(),
            "status": self.status,
            "issues": self.issues,
            "satdump": self.satdump,
        }
        if self.satdump_api is not None:
            payload["satdump_api"] = self.satdump_api
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
        )

        self._api_client = SatdumpApiClient(self._config.satdump_api) if self._config.satdump_api else None
        self._alerts = AlertDispatcher(self._config.alert)

        ensure_directory(self._config.state_file.parent)

    def run_once(self) -> HealthSnapshot:
        now = utc_now()

        if not self._config.enabled:
            snapshot = HealthSnapshot(
                generated_at=now,
                status="disabled",
                issues=["Health monitor disabled via configuration"],
                satdump={"active": False},
            )
            save_state(self._config.state_file, snapshot.to_dict())
            return snapshot

        if self._journal_reader is None:
            issues = ["Journald reader unavailable"]
            snapshot = HealthSnapshot(
                generated_at=now,
                status="error",
                issues=issues,
                satdump=self._journal_state.to_dict(),
            )
            save_state(self._config.state_file, snapshot.to_dict())
            return snapshot

        events = self._journal_reader.poll()
        if events:
            LOGGER.debug("Processed %s new journal events", len(events))
        self._journal_state.ingest(events)

        status = self._journal_state.evaluate(now)
        issues = list(self._journal_state.issues)

        satdump_payload = self._journal_state.to_dict()

        """
        The data structure was not considered during creation of this code. The actual data from 127.0.0.1:8000/api is:
        
        {
            "ccsds_conv_concat_decoder": {
                "deframer_lock": true,
                "rs_avg": 0,
                "viterbi_ber": 0.0732421875,
                "viterbi_lock": 1
            },
            "psk_demod": {
                "freq": 562.2508544921875,
                "peak_snr": 4.7560505867004395,
                "snr": 2.1177315711975098
            }
        
        TODO: Implement an actual check here instead of whatever this is below (which will always fail)
        """

        api_payload = None
        if self._api_client:
            api_payload = self._api_client.fetch_status()
            if api_payload.get("status") != "ok":
                issues.append(f"SatDump API {api_payload.get('status')}")
                status = max(status, "warning", key=lambda level: SEVERITY_ORDER[level])

        snapshot = HealthSnapshot(
            generated_at=now,
            status=status,
            issues=issues,
            satdump=satdump_payload,
            satdump_api=api_payload,
        )

        save_state(self._config.state_file, snapshot.to_dict())
        self._alerts.notify(snapshot)

        return snapshot
