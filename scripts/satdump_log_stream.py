#!/usr/bin/env python3
"""Stream and summarize SatDump journal logs."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
GRAY = "\033[90m"


LOG_RE = re.compile(
    r"^(?P<journal_ts>\w{3}\s+\d+\s+\d\d:\d\d:\d\d)\s+"
    r"(?P<host>\S+)\s+(?P<proc>[^:]+):\s+"
    r"(?:\[(?P<satdump_ts>[^\]]+)\]\s+)?"
    r"(?:\((?P<level>[A-Z])\)\s+)?"
    r"(?P<message>.*)$"
)
NEW_LRIT_RE = re.compile(r"New LRIT file\s*:\s*(?P<name>\S+)")
WRITING_RE = re.compile(r"Writing file\s+(?P<path>.+?)(?:\.\.\.)?$")
IMAGE_RE = re.compile(r"This is image data\. Size\s+(?P<width>\d+)x(?P<height>\d+)")
SNR_RE = re.compile(r"SNR\s*:\s*(?P<snr>[-+]?\d+(?:\.\d+)?)dB,\s*Peak SNR:\s*(?P<peak>[-+]?\d+(?:\.\d+)?)dB")
SYNC_RE = re.compile(
    r"Viterbi\s*:\s*(?P<viterbi>\S+)\s+BER\s*:\s*(?P<ber>[-+]?\d+(?:\.\d+)?),\s*"
    r"Deframer\s*:\s*(?P<deframer>\S+)"
)
GOES_ABI_RE = re.compile(
    r"OR_ABI-(?P<level>L\d)-(?P<product>[A-Z0-9]+)-(?P<mode>M\d)C(?P<channel>\d{2})_"
    r"(?P<satellite>G\d{2})_s(?P<start>\d+)_e(?P<end>\d+)_c(?P<created>\d+)",
    re.IGNORECASE,
)
EMWIN_RE = re.compile(
    r"^(?P<prefix>[A-Z])_(?P<ttaaii>[A-Z]{4}\d{2})(?P<cccc>[A-Z]{4})(?P<ddhhmm>\d{6})_"
    r"C_(?P<source>[A-Z]{4})_(?P<created>\d{14})_(?P<seq>\d+)-(?P<priority>\d)-(?P<awips>[A-Z0-9]+)",
    re.IGNORECASE,
)
NWS_GRAPHIC_RE = re.compile(r"^(?P<stamp>\d{14})-(?P<name>.+?)\.lrit\.(?P<ext>gif|jpg|png)$", re.IGNORECASE)


PRODUCT_HINTS = {
    "CMIPF": "Cloud and Moisture Imagery, Full Disk",
    "CMIPC": "Cloud and Moisture Imagery, CONUS",
    "CMIPM1": "Cloud and Moisture Imagery, Mesoscale 1",
    "CMIPM2": "Cloud and Moisture Imagery, Mesoscale 2",
}

AWIPS_HINTS = {
    "TAF": "Terminal Aerodrome Forecast",
    "RWR": "Regional Weather Roundup",
    "RRM": "River/Rainfall Message",
    "LSR": "Local Storm Report",
    "SFT": "Tabular State Forecast",
    "ZFP": "Zone Forecast Product",
    "FWF": "Fire Weather Forecast",
    "PFM": "Point Forecast Matrices",
    "MIS": "Miscellaneous Message",
    "OMR": "Other Marine Report",
    "OBS": "Observation",
    "SAH": "Hourly Surface Aviation Observation",
}


@dataclass
class State:
    seen_lrit: int = 0
    written_files: int = 0
    image_files: int = 0
    warnings: int = 0
    errors: int = 0
    last_lrit: str | None = None
    last_snr: str | None = None
    last_peak_snr: str | None = None
    last_ber: str | None = None
    last_sync: str | None = None
    last_image_size: str | None = None


def color(text: str, ansi: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{ansi}{text}{RESET}"


def terminal_supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def parse_line(line: str) -> dict[str, str | None]:
    match = LOG_RE.match(line.rstrip("\n"))
    if not match:
        return {
            "journal_ts": None,
            "host": None,
            "proc": None,
            "satdump_ts": None,
            "level": None,
            "message": line.rstrip("\n"),
        }
    return match.groupdict()


def lrit_description(name: str) -> tuple[str, str]:
    basename = Path(name).name

    if basename.startswith("pH-"):
        return "DCS/platform housekeeping", "Small LRIT housekeeping or platform header frame."

    abi = GOES_ABI_RE.search(basename)
    if abi:
        groups = abi.groupdict()
        product = groups["product"].upper()
        hint = PRODUCT_HINTS.get(product, product)
        channel = int(groups["channel"])
        return (
            f"{groups['satellite']} ABI channel {channel:02d}",
            f"{hint}; {groups['level'].upper()} {groups['mode'].upper()} channel {channel:02d}.",
        )

    emwin = EMWIN_RE.search(basename)
    if emwin:
        groups = emwin.groupdict()
        awips = groups["awips"].upper()
        prefix = awips[:3]
        hint = next((description for key, description in AWIPS_HINTS.items() if prefix.startswith(key)), None)
        if hint is None:
            hint = "EMWIN/NWS text weather product"
        return (
            f"EMWIN {awips}",
            f"{hint}; WMO {groups['ttaaii'].upper()} from {groups['cccc'].upper()}.",
        )

    graphic = NWS_GRAPHIC_RE.search(basename)
    if graphic:
        return "NWS graphic", f"Broadcast chart or graphic: {graphic.group('name')}."

    if basename.lower().endswith(".lrit"):
        return "LRIT product", "Unclassified LRIT payload."

    suffix = Path(basename).suffix.lower().lstrip(".") or "file"
    return suffix.upper(), "Decoded output file."


def format_event(kind: str, fields: list[str], details: str | None, ansi: str, use_color: bool) -> str:
    label = color(f"{kind:<8}", ansi, use_color)
    line = f"{label} " + "  ".join(part for part in fields if part)
    if details:
        line += f"  {color(details, DIM, use_color)}"
    return line


def handle_line(line: str, state: State, use_color: bool, raw: bool) -> str | None:
    parsed = parse_line(line)
    message = parsed["message"] or ""
    when = parsed["satdump_ts"] or parsed["journal_ts"] or ""
    level = parsed["level"] or ""

    if raw:
        return line.rstrip("\n")

    if level == "W":
        state.warnings += 1
        return format_event("WARN", [when, message], None, YELLOW, use_color)
    if level in {"E", "F"} or "error" in message.lower() or "traceback" in message.lower():
        state.errors += 1
        return format_event("ERROR", [when, message], None, RED, use_color)

    new_lrit = NEW_LRIT_RE.search(message)
    if new_lrit:
        name = new_lrit.group("name")
        state.seen_lrit += 1
        state.last_lrit = name
        title, details = lrit_description(name)
        ansi = MAGENTA if name.startswith("OR_ABI") else CYAN
        return format_event("LRIT", [when, title, color(name, BOLD, use_color)], details, ansi, use_color)

    writing = WRITING_RE.search(message)
    if writing:
        path = writing.group("path")
        state.written_files += 1
        title, details = lrit_description(path)
        return format_event("WRITE", [when, title, color(path, BOLD, use_color)], details, GREEN, use_color)

    image = IMAGE_RE.search(message)
    if image:
        state.image_files += 1
        state.last_image_size = f"{image.group('width')}x{image.group('height')}"
        return format_event(
            "IMAGE",
            [when, f"{state.last_image_size}", state.last_lrit or ""],
            "SatDump identified image raster data in the current LRIT product.",
            BLUE,
            use_color,
        )

    if "RICE-compressed" in message or "Rice header" in message:
        return format_event("DECODE", [when, message], None, BLUE, use_color)

    snr = SNR_RE.search(message)
    if snr:
        state.last_snr = snr.group("snr")
        state.last_peak_snr = snr.group("peak")
        return format_event(
            "SIGNAL",
            [when, f"SNR {state.last_snr} dB", f"peak {state.last_peak_snr} dB"],
            None,
            GREEN,
            use_color,
        )

    sync = SYNC_RE.search(message)
    if sync:
        state.last_ber = sync.group("ber")
        state.last_sync = f"Viterbi {sync.group('viterbi')} / Deframer {sync.group('deframer')}"
        ansi = GREEN if "SYNCED" in state.last_sync.upper() else YELLOW
        return format_event("SYNC", [when, state.last_sync, f"BER {state.last_ber}"], None, ansi, use_color)

    interesting = ("CRC", "invalid", "recover", "sync", "fail", "lost", "drop")
    if any(word.lower() in message.lower() for word in interesting):
        return format_event("NOTE", [when, message], None, YELLOW, use_color)

    return None


def print_status(state: State, use_color: bool) -> None:
    fields = [
        f"LRIT {state.seen_lrit}",
        f"written {state.written_files}",
        f"images {state.image_files}",
        f"warnings {state.warnings}",
        f"errors {state.errors}",
    ]
    if state.last_snr:
        fields.append(f"SNR {state.last_snr} dB")
    if state.last_ber:
        fields.append(f"BER {state.last_ber}")
    print(format_event("STATUS", fields, None, GRAY, use_color), flush=True)


def stream_file(path: Path, follow: bool, from_start: bool) -> Iterable[str]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        if not from_start:
            handle.seek(0, os.SEEK_END)
        while True:
            line = handle.readline()
            if line:
                yield line
                continue
            if not follow:
                break
            time.sleep(0.25)


def stream_journal(unit: str, since: str | None, lines: int, follow: bool) -> Iterable[str]:
    cmd = ["journalctl", "-u", unit, "-o", "short"]
    if since:
        cmd.extend(["--since", since])
    else:
        cmd.extend(["-n", str(lines)])
    if follow:
        cmd.append("-f")

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")

    def stop_process(signum: int, _frame: object) -> None:
        process.terminate()
        raise KeyboardInterrupt

    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, stop_process)
    signal.signal(signal.SIGTERM, stop_process)
    try:
        assert process.stdout is not None
        yield from process.stdout
        process.wait()
        if process.returncode not in (0, None):
            stderr = process.stderr.read().strip() if process.stderr else ""
            raise SystemExit(f"journalctl exited with {process.returncode}: {stderr}")
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
        if process.poll() is None:
            process.terminate()


def read_lines(args: argparse.Namespace) -> Iterable[str]:
    if args.file:
        return stream_file(Path(args.file), follow=args.follow, from_start=args.from_start)
    if args.stdin or (not args.journal and not sys.stdin.isatty()):
        return sys.stdin
    if shutil.which("journalctl") is None:
        raise SystemExit("journalctl was not found. Use --file satdump.service.log instead.")
    return stream_journal(args.unit, args.since, args.lines, args.follow)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream SatDump logs and highlight received LRIT files, decoded outputs, and signal state."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", help="Read from a saved journalctl log file.")
    source.add_argument("--stdin", action="store_true", help="Read log lines from standard input.")
    source.add_argument("--journal", action="store_true", help="Read from journalctl. This is the default.")
    parser.add_argument("--unit", default="satdump.service", help="systemd unit for --journal mode.")
    parser.add_argument("--since", help='journalctl --since value, for example "4 weeks ago".')
    parser.add_argument("-n", "--lines", type=int, default=50, help="Initial journal lines before following.")
    parser.add_argument("-f", "--follow", action="store_true", help="Keep streaming new lines.")
    parser.add_argument("--from-start", action="store_true", help="With --file, read existing file content before following.")
    parser.add_argument("--raw", action="store_true", help="Print matching raw log lines without summarizing.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output.")
    parser.add_argument("--status-every", type=int, default=60, help="Print a count/status line every N seconds. 0 disables.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    use_color = terminal_supports_color() and not args.no_color
    state = State()
    next_status = time.monotonic() + args.status_every if args.status_every > 0 else None

    try:
        for line in read_lines(args):
            rendered = handle_line(line, state, use_color, args.raw)
            if rendered:
                print(rendered, flush=True)
            if next_status is not None and time.monotonic() >= next_status:
                print_status(state, use_color)
                next_status = time.monotonic() + args.status_every
    except KeyboardInterrupt:
        print()
        print_status(state, use_color)
        return 130

    print_status(state, use_color)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
