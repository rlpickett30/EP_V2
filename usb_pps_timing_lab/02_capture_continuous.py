#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from usb_pps_lab.capture import ContinuousCapture
from usb_pps_lab.common import load_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuously capture USB audio while logging PPS and GNSS RMC timing evidence.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=None, help="Optional capture duration in seconds. Otherwise, Ctrl+C stops capture.")
    args = parser.parse_args()
    config_path = args.config.resolve()
    capture = ContinuousCapture(load_json(config_path), config_path)
    capture.run(duration_seconds=args.duration)


if __name__ == "__main__":
    main()
