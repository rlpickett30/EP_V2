#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from usb_pps_lab.analysis import compare_recordings


def parse_recording(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Use node_id=/path/to/file.wav")
    name, path = value.split("=", 1)
    return name, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a center pipe strike across GPS-corrected node recordings.")
    parser.add_argument("--recording", action="append", type=parse_recording, required=True, help="Repeat as node_id=file.wav")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--event-time", type=float, default=None, help="Optional seconds from corrected-window start. Automatic transient detection is the default.")
    parser.add_argument("--fmin", type=float, default=300.0)
    parser.add_argument("--fmax", type=float, default=10000.0)
    parser.add_argument("--half-window-ms", type=float, default=40.0)
    parser.add_argument("--max-delay-ms", type=float, default=20.0)
    parser.add_argument("--speed-of-sound", type=float, default=343.2)
    args = parser.parse_args()

    recordings = dict(args.recording)
    report = compare_recordings(
        recordings=recordings,
        output_directory=args.output,
        fmin_hz=args.fmin,
        fmax_hz=args.fmax,
        event_time_seconds=args.event_time,
        analysis_half_window_seconds=args.half_window_ms / 1000.0,
        max_delay_seconds=args.max_delay_ms / 1000.0,
        speed_of_sound_mps=args.speed_of_sound,
    )
    print(json.dumps(report, indent=4))


if __name__ == "__main__":
    main()
