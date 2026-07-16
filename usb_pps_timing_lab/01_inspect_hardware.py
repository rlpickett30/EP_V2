#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from usb_pps_lab.inspect import inspect_system


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect audio devices, LinuxPPS, and GNSS serial presence.")
    parser.add_argument("--pps", default="/sys/class/pps/pps0/assert")
    parser.add_argument("--serial", default="/dev/ttyACM0")
    args = parser.parse_args()
    report = inspect_system(Path(args.pps), Path(args.serial))
    print(json.dumps(report, indent=4))


if __name__ == "__main__":
    main()
