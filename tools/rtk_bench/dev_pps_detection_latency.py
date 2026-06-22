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


def read_pps_assert(path: Path):
    text = path.read_text().strip()
    match = ASSERT_PATTERN.search(text)

    if not match:
        return None

    sec = int(match.group("sec"))
    nsec = int(match.group("nsec"))
    seq = int(match.group("seq"))

    kernel_time = sec + (nsec / 1_000_000_000.0)

    return {
        "seq": seq,
        "kernel_time": kernel_time,
        "raw": text,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pps", default="pps0")
    parser.add_argument("--events", type=int, default=30)
    parser.add_argument("--poll-sleep", type=float, default=0.001)
    parser.add_argument("--timeout", type=float, default=45.0)

    args = parser.parse_args()

    assert_path = Path("/sys/class/pps") / args.pps / "assert"

    if not assert_path.exists():
        raise SystemExit(f"Missing PPS assert path: {assert_path}")

    print(f"[PPS LATENCY] Reading {assert_path}")
    print(f"[PPS LATENCY] Poll sleep: {args.poll_sleep * 1000.0:.3f} ms")
    print()

    first = read_pps_assert(assert_path)

    if not first:
        raise SystemExit("Could not parse PPS assert file.")

    last_seq = first["seq"]
    latencies_ms = []
    edges = []

    start = time.time()

    while len(edges) < args.events and time.time() - start < args.timeout:
        event = read_pps_assert(assert_path)

        if not event:
            time.sleep(args.poll_sleep)
            continue

        if event["seq"] != last_seq:
            observed_time = time.time()
            latency_ms = (observed_time - event["kernel_time"]) * 1000.0

            last_seq = event["seq"]
            latencies_ms.append(latency_ms)
            edges.append(event)

            print(
                f"[EDGE] seq={event['seq']} "
                f"kernel={event['kernel_time']:.9f} "
                f"python_latency_ms={latency_ms:.3f}",
                flush=True,
            )

        time.sleep(args.poll_sleep)

    print()
    print("========== PPS PYTHON DETECTION LATENCY ==========")
    print(f"Events captured: {len(latencies_ms)}")

    if len(latencies_ms) < 3:
        print("[FAIL] Not enough events captured.")
        return

    print(f"Mean latency: {statistics.mean(latencies_ms):.3f} ms")
    print(f"Min latency:  {min(latencies_ms):.3f} ms")
    print(f"Max latency:  {max(latencies_ms):.3f} ms")
    print(f"Spread:       {max(latencies_ms) - min(latencies_ms):.3f} ms")

    if len(latencies_ms) > 1:
        print(f"Std dev:      {statistics.stdev(latencies_ms):.3f} ms")

    print()
    print("[NOTE] This is user-space detection latency, not PPS signal jitter.")
    print("[NOTE] The kernel PPS timestamp is the timing truth; Python is only noticing it later.")


if __name__ == "__main__":
    main()

