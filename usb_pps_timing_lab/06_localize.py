#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from usb_pps_lab.analysis import localize_from_relative_delays
from usb_pps_lab.common import atomic_json_write, load_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve a source position from a timing report and measured microphone geometry.")
    parser.add_argument("--timing-report", type=Path, required=True)
    parser.add_argument("--positions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixed-z", type=float, default=None)
    args = parser.parse_args()

    timing = load_json(args.timing_report)
    geometry = load_json(args.positions)
    speed = float(geometry.get("speed_of_sound_mps", 343.2))
    result = localize_from_relative_delays(
        microphone_positions=geometry["microphones"],
        relative_delays_seconds=timing["relative_delays_seconds"],
        speed_of_sound_mps=speed,
        fixed_z=args.fixed_z,
    )
    if "expected_source" in geometry:
        import numpy as np
        expected = np.asarray(geometry["expected_source"], dtype=float)
        solved = np.asarray(result["source_position_m"], dtype=float)
        result["expected_source_m"] = expected.tolist()
        result["position_error_m"] = float(np.linalg.norm(solved - expected))
    args.output.mkdir(parents=True, exist_ok=True)
    atomic_json_write(args.output / "localization_report.json", result)
    print(json.dumps(result, indent=4))


if __name__ == "__main__":
    main()
