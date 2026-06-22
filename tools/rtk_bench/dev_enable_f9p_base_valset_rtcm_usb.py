#!/usr/bin/env python3

import argparse
import struct
import time

try:
    import serial
except ImportError:
    raise SystemExit("Missing pyserial. Install with: pip install pyserial")


# Generation-9 configuration database keys.
# USB protocol output/input flags.
CFG_USBINPROT_UBX = 0x10770001
CFG_USBINPROT_NMEA = 0x10770002
CFG_USBINPROT_RTCM3X = 0x10770004

CFG_USBOUTPROT_UBX = 0x10780001
CFG_USBOUTPROT_NMEA = 0x10780002
CFG_USBOUTPROT_RTCM3X = 0x10780004

# Time mode / survey-in.
CFG_TMODE_MODE = 0x20030001
CFG_TMODE_SVIN_MIN_DUR = 0x40030010
CFG_TMODE_SVIN_ACC_LIMIT = 0x40030011

# RTCM output rates on USB.
CFG_MSGOUT_RTCM_3X_TYPE1005_USB = 0x209102C0
CFG_MSGOUT_RTCM_3X_TYPE1074_USB = 0x20910361
CFG_MSGOUT_RTCM_3X_TYPE1084_USB = 0x20910366
CFG_MSGOUT_RTCM_3X_TYPE1094_USB = 0x2091036B
CFG_MSGOUT_RTCM_3X_TYPE1124_USB = 0x20910370
CFG_MSGOUT_RTCM_3X_TYPE1230_USB = 0x20910306


def ubx_checksum(data: bytes):
    ck_a = 0
    ck_b = 0

    for byte in data:
        ck_a = (ck_a + byte) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF

    return ck_a, ck_b


def make_ubx(msg_class: int, msg_id: int, payload: bytes = b"") -> bytes:
    body = bytes([msg_class, msg_id]) + struct.pack("<H", len(payload)) + payload
    ck_a, ck_b = ubx_checksum(body)
    return b"\xB5\x62" + body + bytes([ck_a, ck_b])


def wait_for_ack(ser, target_class, target_id, timeout=2.0):
    end = time.time() + timeout
    buffer = bytearray()

    while time.time() < end:
        chunk = ser.read(4096)

        if chunk:
            buffer.extend(chunk)

        while len(buffer) >= 2:
            start = buffer.find(b"\xB5\x62")

            if start < 0:
                buffer.clear()
                break

            if start > 0:
                del buffer[:start]

            if len(buffer) < 10:
                break

            msg_class = buffer[2]
            msg_id = buffer[3]
            length = buffer[4] | (buffer[5] << 8)
            frame_len = 6 + length + 2

            if len(buffer) < frame_len:
                break

            frame = bytes(buffer[:frame_len])
            del buffer[:frame_len]

            body = frame[2:-2]
            ck_a, ck_b = ubx_checksum(body)

            if ck_a != frame[-2] or ck_b != frame[-1]:
                continue

            payload = frame[6:-2]

            if msg_class == 0x05 and msg_id in (0x00, 0x01) and len(payload) >= 2:
                acked_class = payload[0]
                acked_id = payload[1]

                if acked_class == target_class and acked_id == target_id:
                    return msg_id == 0x01

    return None


def val_item(key: int, value_type: str, value: int | bool) -> bytes:
    output = struct.pack("<I", key)

    if value_type in ("U1", "E1", "L"):
        output += struct.pack("<B", int(value))

    elif value_type == "U4":
        output += struct.pack("<I", int(value))

    else:
        raise ValueError(f"Unsupported VALSET value type: {value_type}")

    return output


def make_valset(items, layers: int) -> bytes:
    # version=0, layers bitmask, transaction=0, reserved=0
    payload = bytes([0x00, layers, 0x00, 0x00])

    for key, value_type, value in items:
        payload += val_item(key, value_type, value)

    return payload


def sniff_rtcm(ser, seconds: float):
    end = time.time() + seconds
    buffer = bytearray()
    rtcm_count = 0
    nmea_count = 0
    total_bytes = 0

    while time.time() < end:
        chunk = ser.read(4096)

        if not chunk:
            continue

        total_bytes += len(chunk)
        buffer.extend(chunk)

        while buffer:
            if buffer[0] == 0x24:
                newline = buffer.find(b"\n")

                if newline < 0:
                    break

                nmea_count += 1
                del buffer[:newline + 1]
                continue

            if buffer[0] == 0xD3:
                if len(buffer) < 3:
                    break

                length = ((buffer[1] & 0x03) << 8) | buffer[2]
                frame_len = 3 + length + 3

                if len(buffer) < frame_len:
                    break

                rtcm_count += 1
                del buffer[:frame_len]
                continue

            next_nmea = buffer.find(b"$", 1)
            next_rtcm = buffer.find(b"\xD3", 1)

            candidates = [x for x in (next_nmea, next_rtcm) if x >= 0]

            if candidates:
                del buffer[:min(candidates)]
            else:
                if len(buffer) > 4:
                    del buffer[:-4]
                break

    return total_bytes, nmea_count, rtcm_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=38400)
    parser.add_argument("--min-duration", type=int, default=60)
    parser.add_argument("--acc-limit-m", type=float, default=5.0)
    parser.add_argument("--keep-nmea", action="store_true")
    parser.add_argument("--save-bbr", action="store_true")
    args = parser.parse_args()

    print(f"[VALSET BASE CONFIG] Opening {args.port} at {args.baud}")

    # RAM only by default. Add BBR only after this is proven.
    layers = 0x01
    if args.save_bbr:
        layers |= 0x02

    svin_acc_limit_raw = int(args.acc_limit_m / 0.0001)

    items = [
        (CFG_USBINPROT_UBX, "L", 1),
        (CFG_USBINPROT_NMEA, "L", 1),
        (CFG_USBINPROT_RTCM3X, "L", 1),

        (CFG_USBOUTPROT_UBX, "L", 1),
        (CFG_USBOUTPROT_NMEA, "L", 1 if args.keep_nmea else 0),
        (CFG_USBOUTPROT_RTCM3X, "L", 1),

        (CFG_TMODE_SVIN_MIN_DUR, "U4", args.min_duration),
        (CFG_TMODE_SVIN_ACC_LIMIT, "U4", svin_acc_limit_raw),
        (CFG_TMODE_MODE, "E1", 1),

        (CFG_MSGOUT_RTCM_3X_TYPE1005_USB, "U1", 1),
        (CFG_MSGOUT_RTCM_3X_TYPE1074_USB, "U1", 1),
        (CFG_MSGOUT_RTCM_3X_TYPE1084_USB, "U1", 1),
        (CFG_MSGOUT_RTCM_3X_TYPE1094_USB, "U1", 1),
        (CFG_MSGOUT_RTCM_3X_TYPE1124_USB, "U1", 1),
        (CFG_MSGOUT_RTCM_3X_TYPE1230_USB, "U1", 1),
    ]

    payload = make_valset(items, layers=layers)

    with serial.Serial(args.port, args.baud, timeout=0.2) as ser:
        ser.reset_input_buffer()

        ser.write(make_ubx(0x06, 0x8A, payload))
        ser.flush()

        ack = wait_for_ack(ser, 0x06, 0x8A)

        if ack is True:
            print("[ACK] VALSET base + USB RTCM configuration accepted.")
        elif ack is False:
            print("[NAK] VALSET configuration rejected.")
            return
        else:
            print("[WAIT] No ACK seen. Continuing to sniff anyway.")

        print("[SNIFF] Watching for RTCM for 20 seconds...")
        total_bytes, nmea_count, rtcm_count = sniff_rtcm(ser, 20.0)

    print()
    print("========== VALSET RTCM CHECK ==========")
    print(f"Total bytes: {total_bytes}")
    print(f"NMEA count:  {nmea_count}")
    print(f"RTCM count:  {rtcm_count}")

    if rtcm_count > 0:
        print("[GOOD] RTCM is now coming out of USB.")
    else:
        print("[STILL BLOCKED] No RTCM frames seen yet.")


if __name__ == "__main__":
    main()