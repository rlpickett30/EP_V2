#!/usr/bin/env python3

import argparse
import time
from collections import Counter

try:
    import serial
except ImportError:
    raise SystemExit("Missing pyserial. Install with: pip install pyserial")


def rtcm_message_id(payload: bytes):
    if len(payload) < 2:
        return None
    return (payload[0] << 4) | (payload[1] >> 4)


def main():
    parser = argparse.ArgumentParser(description="Sniff F9P serial stream for NMEA and RTCM frames.")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=38400)
    parser.add_argument("--seconds", type=float, default=20.0)
    args = parser.parse_args()

    print(f"[RTCM SNIFF] Opening {args.port} at {args.baud} for {args.seconds:.1f}s")
    print("[RTCM SNIFF] Looking for RTCM frames starting with byte 0xD3")
    print()

    ser = serial.Serial(args.port, args.baud, timeout=0.2)

    start = time.time()
    buf = bytearray()

    total_bytes = 0
    other_bytes = 0
    nmea_count = 0
    rtcm_count = 0
    nmea_types = Counter()
    rtcm_types = Counter()

    while time.time() - start < args.seconds:
        chunk = ser.read(4096)
        if not chunk:
            continue

        total_bytes += len(chunk)
        buf.extend(chunk)

        while buf:
            # NMEA sentence: ASCII, starts with '$', ends with newline.
            if buf[0] == 0x24:  # '$'
                nl = buf.find(b"\n")
                if nl == -1:
                    break

                line = bytes(buf[:nl + 1])
                del buf[:nl + 1]

                try:
                    text = line.decode("ascii", errors="ignore").strip()
                except Exception:
                    text = ""

                if text.startswith("$"):
                    nmea_count += 1
                    sentence_type = text[1:].split(",", 1)[0]
                    nmea_types[sentence_type] += 1

                continue

            # RTCM3 frame: 0xD3, 10-bit length, payload, 3-byte CRC.
            if buf[0] == 0xD3:
                if len(buf) < 3:
                    break

                length = ((buf[1] & 0x03) << 8) | buf[2]
                frame_len = 3 + length + 3

                if len(buf) < frame_len:
                    break

                frame = bytes(buf[:frame_len])
                del buf[:frame_len]

                payload = frame[3:3 + length]
                msg_id = rtcm_message_id(payload)

                rtcm_count += 1
                if msg_id is not None:
                    rtcm_types[msg_id] += 1

                continue

            # Unknown / binary / UBX / partial junk. Resync to next likely frame start.
            next_nmea = buf.find(b"$", 1)
            next_rtcm = buf.find(b"\xD3", 1)

            candidates = [x for x in (next_nmea, next_rtcm) if x != -1]

            if candidates:
                n = min(candidates)
                other_bytes += n
                del buf[:n]
            else:
                # Keep a tiny tail in case a frame start lands across reads.
                if len(buf) > 4:
                    other_bytes += len(buf) - 4
                    del buf[:-4]
                break

    ser.close()

    print("========== RTCM SNIFF RESULT ==========")
    print(f"Port:        {args.port}")
    print(f"Baud:        {args.baud}")
    print(f"Seconds:     {args.seconds:.1f}")
    print(f"Total bytes: {total_bytes}")
    print()
    print(f"NMEA count:  {nmea_count}")
    if nmea_types:
        print("NMEA types:")
        for k, v in nmea_types.most_common():
            print(f"  {k}: {v}")
    print()
    print(f"RTCM count:  {rtcm_count}")
    if rtcm_types:
        print("RTCM message IDs:")
        for k, v in rtcm_types.most_common():
            print(f"  {k}: {v}")
    print()
    print(f"Other/unparsed bytes: {other_bytes}")
    print()

    if rtcm_count == 0:
        print("[DIAGNOSIS] No RTCM frames were seen on this port.")
        print("[NEXT] The F9P base is not outputting RTCM on this serial path, or the base is not configured/surveyed-in yet.")
    else:
        print("[DIAGNOSIS] RTCM frames ARE present on this port.")
        print("[NEXT] The problem is likely in RTKBaseManager packet capture, forwarding, or rover injection.")


if __name__ == "__main__":
    main()