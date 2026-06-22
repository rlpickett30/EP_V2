#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import re
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

    return {
        "seq": seq,
        "kernel_time": sec + nsec / 1_000_000_000.0,
        "raw": text,
    }


def parse_nmea_utc(line: str):
    # Prefer RMC because it contains both time and date.
    # Example:
    # $GNRMC,162257.00,A,3716.48806,N,10752.30678,W,....
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

        return utc_dt

    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pps", default="pps0")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=38400)
    parser.add_argument("--events", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=40.0)
    args = parser.parse_args()

    assert_path = Path("/sys/class/pps") / args.pps / "assert"

    if not assert_path.exists():
        raise SystemExit(f"Missing PPS assert path: {assert_path}")

    print("[PPS UTC PAIR]")
    print(f"PPS:    {assert_path}")
    print(f"Serial: {args.port} @ {args.baud}")
    print()

    latest_utc = None
    latest_nmea_line = None
    last_pps_seq = None
    captured = 0
    serial_buffer = b""

    start = time.time()

    with Serial(args.port, args.baud, timeout=0) as gps_serial:
        while captured < args.events and time.time() - start < args.timeout:
            serial_data = gps_serial.read(4096)

            if serial_data:
                serial_buffer += serial_data

                while b"\n" in serial_buffer:
                    raw_line, serial_buffer = serial_buffer.split(b"\n", 1)
                    line = raw_line.decode(errors="replace").strip()

                    utc_dt = parse_nmea_utc(line)

                    if utc_dt is not None:
                        latest_utc = utc_dt
                        latest_nmea_line = line

            pps_event = read_pps_assert(assert_path)

            if pps_event is None:
                time.sleep(0.002)
                continue

            if last_pps_seq is None:
                last_pps_seq = pps_event["seq"]

            elif pps_event["seq"] != last_pps_seq:
                last_pps_seq = pps_event["seq"]
                captured += 1

                if latest_utc is None:
                    utc_label = "NO_RMC_YET"
                else:
                    utc_label = latest_utc.isoformat()

                print(
                    f"[PAIR] "
                    f"pps_seq={pps_event['seq']} "
                    f"kernel_time={pps_event['kernel_time']:.9f} "
                    f"latest_gnss_utc={utc_label}",
                    flush=True,
                )

                if latest_nmea_line:
                    print(f"       RMC: {latest_nmea_line}", flush=True)

            time.sleep(0.002)

    print()
    print("========== PPS UTC PAIR RESULT ==========")
    print(f"Pairs observed: {captured}")

    if captured > 0:
        print("[GOOD] PPS edges and GNSS UTC labels are both visible to the node.")
        print("[NOTE] The next integration step is to store PPS seq, kernel timestamp, and GNSS UTC in PPSManager state.")
    else:
        print("[FAIL] No PPS/UTC pairs observed.")


if __name__ == "__main__":
    main()