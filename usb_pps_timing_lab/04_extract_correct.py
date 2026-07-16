#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from usb_pps_lab.clock import ClockModel
from usb_pps_lab.common import parse_utc
from usb_pps_lab.correction import extract_and_correct


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a UTC window and warp it onto an exact GPS-time sample grid.")
    parser.add_argument("session", type=Path)
    start_group = parser.add_mutually_exclusive_group(required=True)
    start_group.add_argument("--start-utc", help="ISO-8601 timestamp, for example 2026-07-16T14:15:30Z")
    start_group.add_argument("--offset-seconds", type=float, help="Seconds after the first fitted PPS anchor.")
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-rate", type=int, default=48000)
    parser.add_argument("--interpolation", choices=["linear", "cubic"], default="cubic")
    parser.add_argument("--time-map", choices=["global_linear", "local_linear", "piecewise"], default="local_linear")
    args = parser.parse_args()

    if args.start_utc:
        start_ns = parse_utc(args.start_utc)
    else:
        model = ClockModel.load(args.session / "clock_model.json")
        first_ns = int(model.payload["coverage"]["first_utc_ns"])
        start_ns = first_ns + int(round(args.offset_seconds * 1e9))

    metadata = extract_and_correct(
        session_directory=args.session,
        start_utc_ns=start_ns,
        duration_seconds=args.duration,
        output_directory=args.output,
        target_rate_hz=args.target_rate,
        interpolation=args.interpolation,
        time_map_mode=args.time_map,
    )
    print(json.dumps(metadata, indent=4))


if __name__ == "__main__":
    main()
