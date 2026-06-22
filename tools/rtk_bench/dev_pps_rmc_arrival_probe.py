#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import re
import statistics
import time
from pathlib import Path

from serial import Serial


PPS_PATTERN = re.compile(r"(?P<sec>\d+)\.(?P<nsec>\d+)#(?P<seq>\d+)")


def read_pps_assert(assert_path: Path):
    text = assert_path.read_text().strip()
    match = PPS_PATTERN.search(text)

    if not match:
        return None

    sec = int(match.group("sec"))
    nsec = int(match.group("nsec"))
    seq = int(match.group("seq"))

    kernel_time = sec + nsec / 1_000_000_000.0

    return {
        "seq": seq,
        "kernel_time": kernel_time,
        "kernel_utc": dt.datetime.fromtimestamp(
            kernel_time,
            tz=dt.timezone.utc,
        ),
        "rounded_utc": dt.datetime.fromtimestamp(
            round(kernel_time),
            tz=dt.timezone.utc,
        ),
        "raw": text,
    }


def parse_rmc(line: str):
    if "RMC" not in line:
        return None

    parts = line.split(",")

    if len(parts) < 10:
        return None

    time_field = parts[1]
    status = parts[2]
    date_field = parts[9]

    if status != "A":
        return None

    if len(time_field) < 6 or len(date_field) != 6:
        return None

    try:
        hour = int(time_field[0:2])
        minute = int(time_field[2:4])
        second = int(time_field[4:6])

        day = int(date_field[0:2])
        month = int(date_field[2:4])
        year = 2000 + int(date_field[4:6])

        utc_dt = dt.datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            tzinfo=dt.timezone.utc,
        )

        return {
            "utc": utc_dt,
            "line": line,
        }

    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pps", default="pps0")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=38400)
    parser.add_argument("--rmc-events", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    assert_path = Path("/sys/class/pps") / args.pps / "assert"

    if not assert_path.exists():
        raise SystemExit(f"Missing PPS assert path: {assert_path}")

    print("[PPS/RMC ARRIVAL PROBE]")
    print(f"PPS:    {assert_path}")
    print(f"Serial: {args.port} @ {args.baud}")
    print()

    latest_pps = read_pps_assert(assert_path)
    last_pps_seq = latest_pps["seq"] if latest_pps else None

    serial_buffer = b""
    rmc_delays_ms = []
    rmc_second_offsets = []

    start = time.time()

    with Serial(args.port, args.baud, timeout=0) as gps_serial:
        while len(rmc_delays_ms) < args.rmc_events and time.time() - start < args.timeout:
            pps_event = read_pps_assert(assert_path)

            if pps_event and pps_event["seq"] != last_pps_seq:
                latest_pps = pps_event
                last_pps_seq = pps_event["seq"]

                print(
                    f"[PPS] seq={pps_event['seq']} "
                    f"kernel_utc={pps_event['kernel_utc'].isoformat()} "
                    f"rounded_utc={pps_event['rounded_utc'].isoformat()}",
                    flush=True,
                )

            serial_data = gps_serial.read(4096)

            if serial_data:
                serial_buffer += serial_data

                while b"\n" in serial_buffer:
                    raw_line, serial_buffer = serial_buffer.split(b"\n", 1)
                    line = raw_line.decode(errors="replace").strip()

                    rmc = parse_rmc(line)

                    if not rmc or not latest_pps:
                        continue

                    observed_time = time.time()
                    delay_ms = (observed_time - latest_pps["kernel_time"]) * 1000.0

                    rmc_epoch = int(rmc["utc"].timestamp())
                    pps_rounded_epoch = int(round(latest_pps["kernel_time"]))
                    second_offset = rmc_epoch - pps_rounded_epoch

                    rmc_delays_ms.append(delay_ms)
                    rmc_second_offsets.append(second_offset)

                    print(
                        f"[RMC] utc={rmc['utc'].isoformat()} "
                        f"paired_pps_seq={latest_pps['seq']} "
                        f"after_pps_ms={delay_ms:.3f} "
                        f"rmc_minus_pps_seconds={second_offset}",
                        flush=True,
                    )
                    print(f"      {rmc['line']}", flush=True)

            time.sleep(0.002)

    print()
    print("========== PPS/RMC ARRIVAL RESULT ==========")
    print(f"RMC events captured: {len(rmc_delays_ms)}")

    if not rmc_delays_ms:
        print("[FAIL] No valid RMC events captured.")
        return

    print(f"Mean RMC arrival after PPS: {statistics.mean(rmc_delays_ms):.3f} ms")
    print(f"Min RMC arrival after PPS:  {min(rmc_delays_ms):.3f} ms")
    print(f"Max RMC arrival after PPS:  {max(rmc_delays_ms):.3f} ms")

    if len(rmc_delays_ms) > 1:
        print(f"Std dev:                    {statistics.stdev(rmc_delays_ms):.3f} ms")

    print()
    print("RMC UTC second offset relative to paired PPS rounded second:")
    for offset in sorted(set(rmc_second_offsets)):
        print(f"  offset {offset}: {rmc_second_offsets.count(offset)} events")

    if all(offset == 0 for offset in rmc_second_offsets):
        print()
        print("[GOOD] RMC UTC labels match the most recent PPS edge.")
        print("[INTEGRATION RULE] Store the PPS edge first, then label it when the matching RMC arrives.")
    else:
        print()
        print("[CHECK] RMC/PPS second pairing needs review before integration.")


if __name__ == "__main__":
    main()