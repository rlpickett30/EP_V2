"""
rover_rtcm_receiver.py

Temporary EnviroPulse RTK rover bench script.

Responsibilities:
- Listen for RTCM packets over UDP.
- Write received RTCM bytes into the local ZED-F9P over USB.
- Read local GGA lines from the same ZED-F9P.
- Print GPS / DGPS / RTK_FLOAT / RTK_FIXED status.

Run on rover nodes:
- node_01
- node_02

Stop node_main.py before running this script.
"""

from __future__ import annotations

import select
import socket
import time
from serial import Serial


SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 38400

UDP_BIND_HOST = "0.0.0.0"
UDP_PORT = 5010


FIX_LABELS = {
    "0": "NO_FIX",
    "1": "GPS",
    "2": "DGPS_SBAS",
    "4": "RTK_FIXED",
    "5": "RTK_FLOAT",
}


def parse_gga(line: str) -> None:
    parts = line.split(",")

    if len(parts) < 10:
        return

    fix_quality = parts[6]
    satellites = parts[7]
    hdop = parts[8]
    latitude = parts[2]
    latitude_hemi = parts[3]
    longitude = parts[4]
    longitude_hemi = parts[5]
    altitude_m = parts[9]

    print(
        "GGA "
        f"fix={FIX_LABELS.get(fix_quality, fix_quality)} "
        f"quality={fix_quality} "
        f"sats={satellites} "
        f"hdop={hdop} "
        f"lat={latitude}{latitude_hemi} "
        f"lon={longitude}{longitude_hemi} "
        f"alt_m={altitude_m}",
        flush=True
    )


def main() -> None:
    print("Starting temporary RTK rover.")
    print(f"Serial: {SERIAL_PORT} @ {SERIAL_BAUD}")
    print(f"UDP listen: {UDP_BIND_HOST}:{UDP_PORT}")
    print("Stop with Ctrl+C.")
    print()

    udp_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    udp_socket.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    udp_socket.bind(
        (
            UDP_BIND_HOST,
            UDP_PORT
        )
    )

    udp_socket.setblocking(
        False
    )

    with Serial(
        SERIAL_PORT,
        SERIAL_BAUD,
        timeout=0,
        write_timeout=1
    ) as gps_serial:

        serial_buffer = b""

        last_report_time = time.time()
        rtcm_packets = 0
        rtcm_bytes = 0

        while True:
            readable, _, _ = select.select(
                [
                    udp_socket
                ],
                [],
                [],
                0.05
            )

            if udp_socket in readable:
                data, address = udp_socket.recvfrom(
                    4096
                )

                if data:
                    gps_serial.write(
                        data
                    )

                    gps_serial.flush()

                    rtcm_packets += 1
                    rtcm_bytes += len(
                        data
                    )

            serial_data = gps_serial.read(
                4096
            )

            if serial_data:
                serial_buffer += serial_data

                while b"\n" in serial_buffer:
                    raw_line, serial_buffer = serial_buffer.split(
                        b"\n",
                        1
                    )

                    line = raw_line.decode(
                        errors="replace"
                    ).strip()

                    if "GGA" in line:
                        parse_gga(
                            line
                        )

            now = time.time()

            if now - last_report_time >= 5:
                print(
                    f"RTCM received: packets={rtcm_packets} bytes={rtcm_bytes}",
                    flush=True
                )

                rtcm_packets = 0
                rtcm_bytes = 0
                last_report_time = now


if __name__ == "__main__":
    main()