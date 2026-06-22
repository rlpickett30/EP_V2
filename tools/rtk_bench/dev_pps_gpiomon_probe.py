#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys


TIMESTAMP_PATTERN = re.compile(r"(\d+\.\d+)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chip", default="gpiochip0")
    parser.add_argument("--line", default="GPIO18")
    parser.add_argument("--events", type=int, default=20)
    args = parser.parse_args()

    command = [
        "gpiomon",
        "--chip",
        args.chip,
        "-n",
        str(args.events),
        args.line,
    ]

    print("[PPS PROBE] Running:")
    print(" ".join(command))
    print()

    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=args.events + 8,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        error = exc.stderr or ""
    else:
        output = result.stdout or ""
        error = result.stderr or ""

    if error.strip():
        print("[GPIOMON STDERR]")
        print(error.strip())
        print()

    print("========== PPS RAW EDGES ==========")
    print(output.strip())
    print()

    timestamps = []

    for line in output.splitlines():
        match = TIMESTAMP_PATTERN.search(line)
        if match:
            timestamps.append(float(match.group(1)))

    if len(timestamps) < 3:
        print("[FAIL] Not enough PPS edges captured.")
        print("Try this manually:")
        print(f"  gpiomon --chip {args.chip} -n {args.events} {args.line}")
        sys.exit(1)

    intervals = [
        timestamps[i] - timestamps[i - 1]
        for i in range(1, len(timestamps))
    ]

    mean_interval = statistics.mean(intervals)
    min_interval = min(intervals)
    max_interval = max(intervals)
    spread_ms = (max_interval - min_interval) * 1000.0

    if len(intervals) > 1:
        stdev_ms = statistics.stdev(intervals) * 1000.0
    else:
        stdev_ms = 0.0

    print("========== PPS TIMING RESULT ==========")
    print(f"Edges captured: {len(timestamps)}")
    print(f"Mean interval: {mean_interval:.9f} s")
    print(f"Min interval:  {min_interval:.9f} s")
    print(f"Max interval:  {max_interval:.9f} s")
    print(f"Spread:        {spread_ms:.3f} ms")
    print(f"Std dev:       {stdev_ms:.3f} ms")
    print()

    if all(0.990 <= interval <= 1.010 for interval in intervals):
        print("[GOOD] PPS is arriving as a stable 1 Hz edge.")
    else:
        print("[WARN] Some PPS intervals are outside 0.990–1.010 s.")
        for interval in intervals:
            print(f"  {interval:.9f}")


if __name__ == "__main__":
    main()