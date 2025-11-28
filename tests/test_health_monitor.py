from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from goes_health_monitor.service import (
    JournalEvent,
    SatdumpApiEvaluator,
    SatdumpJournalState,
)
from goes_manager.config import SatdumpSignalThresholds


def _make_event(message: str, *, priority: int = 6, ts: Optional[datetime] = None) -> JournalEvent:
    timestamp = ts or datetime.now(tz=timezone.utc)
    return JournalEvent(timestamp=timestamp, priority=priority, message=message, cursor=None, identifier="satdump")


def test_journal_state_detects_plugin_failure() -> None:
    thresholds = SatdumpSignalThresholds()
    state = SatdumpJournalState(
        max_gap_seconds=300,
        recent_limit=10,
        error_window_seconds=600,
        warning_window_seconds=300,
        error_keywords=[],
        warning_keywords=[],
        signal_thresholds=thresholds,
    )

    base_time = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    event = _make_event(
        "Error loading /usr/lib/satdump/plugins/libusrp_sdr_support.so! Error : missing dependency",
        priority=3,
        ts=base_time,
    )

    state.ingest([event])
    severity = state.evaluate(base_time + timedelta(seconds=10))

    assert severity == "error"
    assert any("Plugin libusrp_sdr_support failed to load" in issue for issue in state.issues)

    decoded = state.to_dict().get("decoded", {})
    assert decoded.get("active_alerts")


def test_journal_state_signals_low_snr_warning() -> None:
    thresholds = SatdumpSignalThresholds(min_snr_warning=2.5, min_snr_error=1.0, min_peak_snr_warning=4.0, min_peak_snr_error=2.0)
    state = SatdumpJournalState(
        max_gap_seconds=300,
        recent_limit=10,
        error_window_seconds=600,
        warning_window_seconds=300,
        error_keywords=[],
        warning_keywords=[],
        signal_thresholds=thresholds,
    )

    base_time = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    event = _make_event(
        "Progress inf%, SNR : 1.90dB, Peak SNR: 3.20dB",
        priority=6,
        ts=base_time,
    )

    state.ingest([event])
    severity = state.evaluate(base_time + timedelta(seconds=5))

    assert severity == "warning"
    assert any("Signal SNR" in issue for issue in state.issues)

    decoded = state.to_dict().get("decoded", {})
    signal = decoded.get("signal_quality", {})
    assert signal.get("severity") == "warning"


def test_journal_state_detects_rtlsdr_failure() -> None:
    thresholds = SatdumpSignalThresholds()
    state = SatdumpJournalState(
        max_gap_seconds=300,
        recent_limit=10,
        error_window_seconds=600,
        warning_window_seconds=300,
        error_keywords=[],
        warning_keywords=[],
        signal_thresholds=thresholds,
    )

    base_time = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    event = _make_event("rtlsdr_read_reg failed with -4", priority=3, ts=base_time)

    state.ingest([event])
    severity = state.evaluate(base_time + timedelta(seconds=5))

    assert severity == "error"
    assert any("RTL-SDR" in issue for issue in state.issues)

def test_api_evaluator_flags_decoder_and_signal_issues() -> None:
    thresholds = SatdumpSignalThresholds(
        min_snr_warning=2.5,
        min_snr_error=1.5,
        min_peak_snr_warning=3.5,
        min_peak_snr_error=2.5,
        max_viterbi_ber_warning=0.1,
        max_viterbi_ber_error=0.2,
        require_deframer_lock=True,
        require_viterbi_lock=True,
    )
    evaluator = SatdumpApiEvaluator(thresholds)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    payload = {
        "psk_demod": {
            "snr": 1.2,
            "peak_snr": 2.3,
            "freq": 562.25,
        },
        "ccsds_conv_concat_decoder": {
            "deframer_lock": False,
            "viterbi_lock": 0,
            "viterbi_ber": 0.15,
            "rs_avg": 0,
        },
    }

    evaluation = evaluator.evaluate(payload, now)

    assert evaluation.severity == "error"
    assert any("Demod SNR" in issue for issue in evaluation.issues)
    assert any("Decoder deframer" in issue for issue in evaluation.issues)

    demod_metrics = evaluation.metrics.get("demod", {})
    decoder_metrics = evaluation.metrics.get("decoder", {})
    assert demod_metrics.get("severity") == "error"
    assert decoder_metrics.get("severity") == "error"
    assert any("Demod SNR" in message for message in evaluation.messages)


def test_api_evaluator_ok_messages() -> None:
    thresholds = SatdumpSignalThresholds()
    evaluator = SatdumpApiEvaluator(thresholds)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    payload = {
        "psk_demod": {
            "snr": 4.2,
            "peak_snr": 6.0,
            "freq": 562.25,
        },
        "ccsds_conv_concat_decoder": {
            "deframer_lock": True,
            "viterbi_lock": 1,
            "viterbi_ber": 0.05,
            "rs_avg": 0,
        },
    }

    evaluation = evaluator.evaluate(payload, now)

    assert evaluation.severity == "ok"
    assert any("Demod SNR" in message for message in evaluation.messages)
    assert any("Viterbi BER" in message for message in evaluation.messages)
