#!/usr/bin/env python3

import argparse
import struct
import time

try:
    import serial
except ImportError:
    raise SystemExit("Missing pyserial. Install with: pip install pyserial")


RTCM_MESSAGES = {
    (0xF5, 0x05): "RTCM 1005 Stationary RTK reference station ARP",
    (0xF5, 0x4A): "RTCM 1074 GPS MSM4",
    (0xF5, 0x54): "RTCM 1084 GLONASS MSM4",
    (0xF5, 0x5E): "RTCM 1094 Galileo MSM4",
    (0xF5, 0x7C): "RTCM 1124 BeiDou MSM4",
    (0xF5, 0xE6): "RTCM 1230 GLONASS code-phase biases",
}


def ubx_checksum(data: bytes):
    ck_a = 0
    ck_b = 0
    for b in data:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a, ck_b


def make_ubx(msg_class: int, msg_id: int, payload: bytes = b"") -> bytes:
    body = bytes([msg_class, msg_id]) + struct.pack("<H", len(payload)) + payload
    ck_a, ck_b = ubx_checksum(body)
    return b"\xB5\x62" + body + bytes([ck_a, ck_b])


def wait_for_ack(ser, target_class, target_id, timeout=1.5):
    end = time.time() + timeout
    buf = bytearray()

    while time.time() < end:
        chunk = ser.read(4096)
        if chunk:
            buf.extend(chunk)

        while len(buf) >= 2:
            start = buf.find(b"\xB5\x62")
            if start == -1:
                buf.clear()
                break

            if start > 0:
                del buf[:start]

            if len(buf) < 10:
                break

            msg_class = buf[2]
            msg_id = buf[3]
            length = buf[4] | (buf[5] << 8)
            frame_len = 6 + length + 2

            if len(buf) < frame_len:
                break

            frame = bytes(buf[:frame_len])
            del buf[:frame_len]

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


def send_cfg(ser, msg_class, msg_id, payload, label):
    ser.write(make_ubx(msg_class, msg_id, payload))
    ser.flush()

    ack = wait_for_ack(ser, msg_class, msg_id)

    if ack is True:
        print(f"[ACK]  {label}")
    elif ack is False:
        print(f"[NAK]  {label}")
    else:
        print(f"[WAIT] {label} — no ACK seen, continuing")


def build_tmode3_survey_in_payload(min_duration_s, acc_limit_m):
    version = 0
    reserved1 = 0

    # TMODE3 flags:
    # mode 0 = disabled
    # mode 1 = survey-in
    # mode 2 = fixed
    flags = 1

    ecef_x_or_lat = 0
    ecef_y_or_lon = 0
    ecef_z_or_alt = 0
    ecef_x_or_lat_hp = 0
    ecef_y_or_lon_hp = 0
    ecef_z_or_alt_hp = 0
    reserved2 = 0

    fixed_pos_acc = 0

    # u-blox TMODE3 accuracy values are in 0.1 mm units.
    svin_acc_limit = int(acc_limit_m / 0.0001)

    reserved3 = b"\x00" * 8

    return struct.pack(
        "<BBHiiiBBBBIII8s",
        version,
        reserved1,
        flags,
        ecef_x_or_lat,
        ecef_y_or_lon,
        ecef_z_or_alt,
        ecef_x_or_lat_hp,
        ecef_y_or_lon_hp,
        ecef_z_or_alt_hp,
        reserved2,
        fixed_pos_acc,
        int(min_duration_s),
        svin_acc_limit,
        reserved3,
    )


def build_usb_prt_payload():
    # CFG-PRT for USB, portID 3.
    # Enable UBX, NMEA, and RTCM3 input/output masks.
    port_id = 3
    reserved1 = 0
    tx_ready = 0
    mode = 0
    baud_rate = 0

    proto_ubx = 0x0001
    proto_nmea = 0x0002
    proto_rtcm3 = 0x0004

    in_proto_mask = proto_ubx | proto_nmea | proto_rtcm3
    out_proto_mask = proto_ubx | proto_nmea | proto_rtcm3

    flags = 0
    reserved2 = 0

    return struct.pack(
        "<BBHIIHHHH",
        port_id,
        reserved1,
        tx_ready,
        mode,
        baud_rate,
        in_proto_mask,
        out_proto_mask,
        flags,
        reserved2,
    )


def build_cfg_msg_payload(msg_class, msg_id, usb_rate=1):
    # msgClass, msgID, rateI2C, rateUART1, rateUART2, rateUSB, rateSPI, reserved
    return bytes([msg_class, msg_id, 0, 0, 0, usb_rate, 0, 0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=38400)
    parser.add_argument("--min-duration", type=int, default=60)
    parser.add_argument("--acc-limit-m", type=float, default=5.0)
    args = parser.parse_args()

    print(f"[BASE CONFIG] Opening {args.port} at {args.baud}")
    print(f"[BASE CONFIG] Survey-in duration: {args.min_duration}s")
    print(f"[BASE CONFIG] Survey-in accuracy limit: {args.acc_limit_m:.2f} m")
    print()

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    ser.reset_input_buffer()

    send_cfg(
        ser,
        0x06,
        0x00,
        build_usb_prt_payload(),
        "Enable UBX/NMEA/RTCM3 protocol masks on USB",
    )

    send_cfg(
        ser,
        0x06,
        0x71,
        build_tmode3_survey_in_payload(args.min_duration, args.acc_limit_m),
        "Enable TMODE3 survey-in base mode",
    )

    for (msg_class, msg_id), label in RTCM_MESSAGES.items():
        send_cfg(
            ser,
            0x06,
            0x01,
            build_cfg_msg_payload(msg_class, msg_id, usb_rate=1),
            f"Enable {label} on USB",
        )

    ser.close()

    print()
    print("[DONE] Base survey-in and USB RTCM output were requested.")
    print("[NEXT] Re-run the base state check. NAV-SVIN should become active immediately.")
    print("[NEXT] RTCM frames usually appear after survey-in becomes valid.")


if __name__ == "__main__":
    main()