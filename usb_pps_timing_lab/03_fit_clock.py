#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from usb_pps_lab.clock import fit_session_clock


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit the USB microphone sample clock to GPS/PPS time.")
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    model = fit_session_clock(args.session)
    summary = {
        "node_id": model["node_id"],
        "quality": model["quality"],
        "nominal_sample_rate_hz": model["nominal_sample_rate_hz"],
        "effective_sample_rate_hz": model["effective_sample_rate_hz"],
        "sample_rate_error_ppm": model["sample_rate_error_ppm"],
        "coverage": model["coverage"],
    }
    print(json.dumps(summary, indent=4))
    print(f"\nSaved: {args.session.resolve() / 'clock_model.json'}")


if __name__ == "__main__":
    main()
