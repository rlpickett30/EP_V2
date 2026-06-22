#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import statistics
import time
from pathlib import Path


ASSERT_PATTERN = re.compile(
    r"(?P<sec>\d+)\.(?P<nsec>\d+)#(?P<seq>\d+)"
)


def read_assert(path: Path):
    text = path.read_text().strip()
    match = ASSERT_PATTERN.search(text)

    if not match:
        return None, text

    sec = int(match.group("sec"))
    nsec = int(match.group("nsec"))
    seq = int(match.group("seq"))

    timestamp = sec + (nsec / 1_000_000_000.0)

    return {
        "timestamp": timestamp,
        "sec": sec,
        "nsec": nsec,
        "seq": seq,
        "raw": text,
    }, text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe Linux kernel PPS events from /sys/class/pps."
    )

    parser.add_argument("--pps", default="pps0")
    parser.add_argument("--events", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=30.0)

    args = parser.parse_args()

    pps_dir = Path("/sys/class/pps") / args.pps
    assert_path = pps_dir / "assert"
    name_path = pps_dir / "name"

    print(f"[PPS KERNEL PROBE] PPS device: {args.pps}")
    print(f"[PPS KERNEL PROBE] Path: {assert_path}")
    print()

    if name_path.exists():
        print(f"Name: {name_path.read_text().strip()}")

    if not assert_path.exists():
        print("[FAIL] PPS assert path does not exist.")
        print("Expected something like /sys/class/pps/pps0/assert")
        return

    events = []
    last_seq = None
    start = time.time()

    while len(events) < args.events and time.time() - start < args.timeout:
        event, raw = read_assert(assert_path)

        if event is None:
            print(f"[WARN] Could not parse assert file: {raw!r}")
            time.sleep(0.05)
            continue

        if last_seq is None:
            last_seq = event["seq"]
            print(f"[START] seq={event['seq']} raw={event['raw']}")

        elif event["seq"] != last_seq:
            last_seq = event["seq"]
            events.append(event)
            print(
                f"[EDGE] seq={event['seq']} "
                f"time={event['timestamp']:.9f} "
                f"raw={event['raw']}",
                flush=True,
            )

        time.sleep(0.01)

    print()
    print("========== PPS KERNEL RESULT ==========")
    print(f"Events captured: {len(events)}")

    if len(events) < 3:
        print("[FAIL] Not enough PPS events captured.")
        print("This means the kernel PPS device exists, but assert events are not updating.")
        return

    timestamps = [
        event["timestamp"]
        for event in events
    ]

    intervals = [
        timestamps[i] - timestamps[i - 1]
        for i in range(1, len(timestamps))
    ]

    mean_interval = statistics.mean(intervals)
    min_interval = min(intervals)
    max_interval = max(intervals)
    spread_ms = (max_interval - min_interval) * 1000.0
    stdev_ms = statistics.stdev(intervals) * 1000.0 if len(intervals) > 1 else 0.0

    print(f"Mean interval: {mean_interval:.9f} s")
    print(f"Min interval:  {min_interval:.9f} s")
    print(f"Max interval:  {max_interval:.9f} s")
    print(f"Spread:        {spread_ms:.6f} ms")
    print(f"Std dev:       {stdev_ms:.6f} ms")
    print()

    if all(0.990 <= interval <= 1.010 for interval in intervals):
        print("[GOOD] Kernel PPS is alive and updating at 1 Hz.")
    else:
        print("[WARN] Some PPS intervals are outside 0.990–1.010 s.")
        for interval in intervals:
            print(f"  {interval:.9f}")


if __name__ == "__main__":
    main()


