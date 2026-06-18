"""
base_rtcm_broadcaster.py

Temporary EnviroPulse RTK base bench script.

Responsibilities:
- Read the local ZED-F9P USB stream.
- Extract complete RTCM3 packets.
- Send RTCM packets over UDP to rover IP addresses.

Run on base node:
- node_03

Stop node_main.py before running this script.
"""

from __future__ import annotations

import argparse
import socket
import time
from serial import Serial


SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 38400

UDP_PORT = 5010


def extract_rtcm_packets(
    buffer: bytes
) -> tuple[list[bytes], bytes]:

    packets = []

    while True:
        start = buffer.find(
            b"\xd3"
        )

        if start < 0:
            return packets, b""

        if start > 0:
            buffer = buffer[start:]

        if len(buffer) < 3:
            return packets, buffer

        length = (
            (
                buffer[1] & 0x03
            ) << 8
        ) | buffer[2]

        packet_length = 3 + length + 3

        if len(buffer) < packet_length:
            return packets, buffer

        packet = buffer[:packet_length]

        packets.append(
            packet
        )

        buffer = buffer[packet_length:]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Broadcast RTCM packets from base F9P to rover IPs."
    )

    parser.add_argument(
        "rovers",
        nargs="+",
        help="Rover IP addresses."
    )

    args = parser.parse_args()

    rover_addresses = [
        (
            rover_ip,
            UDP_PORT
        )
        for rover_ip in args.rovers
    ]

    print("Starting temporary RTK base broadcaster.")
    print(f"Serial: {SERIAL_PORT} @ {SERIAL_BAUD}")
    print(f"Rovers: {rover_addresses}")
    print("Stop with Ctrl+C.")
    print()

    udp_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    with Serial(
        SERIAL_PORT,
        SERIAL_BAUD,
        timeout=0.25
    ) as gps_serial:

        buffer = b""

        last_report_time = time.time()
        packets_sent = 0
        bytes_sent = 0
        nmea_hits = 0
        rtcm_packets_found = 0

        while True:
            data = gps_serial.read(
                4096
            )

            if not data:
                continue

            nmea_hits += data.count(
                b"$GN"
            ) + data.count(
                b"$GP"
            )

            buffer += data

            packets, buffer = extract_rtcm_packets(
                buffer
            )

            rtcm_packets_found += len(
                packets
            )

            for packet in packets:
                for address in rover_addresses:
                    udp_socket.sendto(
                        packet,
                        address
                    )

                packets_sent += 1
                bytes_sent += len(
                    packet
                )

            now = time.time()

            if now - last_report_time >= 5:
                print(
                    "RTCM sent: "
                    f"packets={packets_sent} "
                    f"bytes={bytes_sent} "
                    f"rtcm_found={rtcm_packets_found} "
                    f"nmea_hits={nmea_hits}",
                    flush=True
                )

                packets_sent = 0
                bytes_sent = 0
                nmea_hits = 0
                rtcm_packets_found = 0
                last_report_time = now


if __name__ == "__main__":
    main()