#!/usr/bin/env python3

import argparse
import struct
import time
from collections import defaultdict

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
    length = len(payload)
    body = bytes([msg_class, msg_id]) + struct.pack("<H", length) + payload
    ck_a, ck_b = ubx_checksum(body)
    return b"\xB5\x62" + body + bytes([ck_a, ck_b])


def parse_stream(ser, seconds):
    end_time = time.time() + seconds
    buf = bytearray()

    ubx_frames = []
    rtcm_count = 0

    while time.time() < end_time:
        chunk = ser.read(4096)
        if chunk:
            buf.extend(chunk)

        while buf:
            if len(buf) >= 2 and buf[0] == 0xB5 and buf[1] == 0x62:
                if len(buf) < 6:
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

                if ck_a == frame[-2] and ck_b == frame[-1]:
                    payload = frame[6:-2]
                    ubx_frames.append((msg_class, msg_id, payload))

                continue

            if buf[0] == 0x24:  # NMEA "$"
                nl = buf.find(b"\n")
                if nl == -1:
                    break
                del buf[:nl + 1]
                continue

            if buf[0] == 0xD3:  # RTCM3
                if len(buf) < 3:
                    break
                length = ((buf[1] & 0x03) << 8) | buf[2]
                frame_len = 3 + length + 3
                if len(buf) < frame_len:
                    break
                del buf[:frame_len]
                rtcm_count += 1
                continue

            next_candidates = []
            for marker in (b"\xB5\x62", b"$", b"\xD3"):
                idx = buf.find(marker, 1)
                if idx != -1:
                    next_candidates.append(idx)

            if next_candidates:
                del buf[:min(next_candidates)]
            else:
                if len(buf) > 4:
                    del buf[:-4]
                break

    return ubx_frames, rtcm_count


def parse_nav_svin(payload):
    if len(payload) < 40:
        return None

    dur = struct.unpack_from("<I", payload, 8)[0]
    mean_acc_raw = struct.unpack_from("<I", payload, 28)[0]
    obs = struct.unpack_from("<I", payload, 32)[0]
    valid = bool(payload[36])
    active = bool(payload[37])

    return {
        "duration_s": dur,
        "mean_acc_m": mean_acc_raw * 0.0001,
        "mean_acc_cm": mean_acc_raw * 0.01,
        "observations": obs,
        "valid": valid,
        "active": active,
    }


def parse_cfg_tmode3(payload):
    if len(payload) < 40:
        return None

    flags = struct.unpack_from("<H", payload, 2)[0]
    mode_value = flags & 0x00FF
    lla_mode = bool(flags & 0x0100)

    mode_name = {
        0: "DISABLED",
        1: "SURVEY_IN",
        2: "FIXED",
    }.get(mode_value, f"UNKNOWN_{mode_value}")

    fixed_pos_acc_raw = struct.unpack_from("<I", payload, 20)[0]
    svin_min_dur = struct.unpack_from("<I", payload, 24)[0]
    svin_acc_limit_raw = struct.unpack_from("<I", payload, 28)[0]

    return {
        "mode": mode_name,
        "mode_value": mode_value,
        "lla_mode": lla_mode,
        "fixed_pos_acc_m": fixed_pos_acc_raw * 0.0001,
        "svin_min_dur_s": svin_min_dur,
        "svin_acc_limit_m": svin_acc_limit_raw * 0.0001,
    }


def parse_cfg_msg(payload):
    if len(payload) < 8:
        return None

    msg_class = payload[0]
    msg_id = payload[1]

    rates = {
        "I2C": payload[2],
        "UART1": payload[3],
        "UART2": payload[4],
        "USB": payload[5],
        "SPI": payload[6],
    }

    return msg_class, msg_id, rates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=38400)
    parser.add_argument("--seconds", type=float, default=5.0)
    args = parser.parse_args()

    print(f"[F9P BASE CHECK] Opening {args.port} at {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.2)

    ser.reset_input_buffer()

    # Poll NAV-SVIN.
    ser.write(make_ubx(0x01, 0x3B))

    # Poll CFG-TMODE3.
    ser.write(make_ubx(0x06, 0x71))

    # Poll CFG-MSG for common RTCM correction messages.
    for msg_class, msg_id in RTCM_MESSAGES:
        ser.write(make_ubx(0x06, 0x01, bytes([msg_class, msg_id])))

    ubx_frames, rtcm_count = parse_stream(ser, args.seconds)
    ser.close()

    nav_svin = None
    tmode3 = None
    cfg_msg_rates = {}

    for msg_class, msg_id, payload in ubx_frames:
        if (msg_class, msg_id) == (0x01, 0x3B):
            nav_svin = parse_nav_svin(payload)

        elif (msg_class, msg_id) == (0x06, 0x71):
            tmode3 = parse_cfg_tmode3(payload)

        elif (msg_class, msg_id) == (0x06, 0x01):
            parsed = parse_cfg_msg(payload)
            if parsed:
                cfg_class, cfg_id, rates = parsed
                cfg_msg_rates[(cfg_class, cfg_id)] = rates

    print()
    print("========== F9P BASE STATE ==========")

    if tmode3:
        print("TMODE3:")
        print(f"  mode:             {tmode3['mode']}")
        print(f"  lla_mode:         {tmode3['lla_mode']}")
        print(f"  svin_min_dur_s:   {tmode3['svin_min_dur_s']}")
        print(f"  svin_acc_limit_m: {tmode3['svin_acc_limit_m']:.4f}")
        print(f"  fixed_pos_acc_m:  {tmode3['fixed_pos_acc_m']:.4f}")
    else:
        print("TMODE3: No response")

    print()

    if nav_svin:
        print("NAV-SVIN:")
        print(f"  active:           {nav_svin['active']}")
        print(f"  valid:            {nav_svin['valid']}")
        print(f"  duration_s:       {nav_svin['duration_s']}")
        print(f"  observations:     {nav_svin['observations']}")
        print(f"  mean_acc_m:       {nav_svin['mean_acc_m']:.4f}")
        print(f"  mean_acc_cm:      {nav_svin['mean_acc_cm']:.2f}")
    else:
        print("NAV-SVIN: No response")

    print()
    print("RTCM CFG-MSG RATES:")
    for key, label in RTCM_MESSAGES.items():
        rates = cfg_msg_rates.get(key)
        if not rates:
            print(f"  {label}: No response")
            continue

        print(
            f"  {label}: "
            f"I2C={rates['I2C']} "
            f"UART1={rates['UART1']} "
            f"UART2={rates['UART2']} "
            f"USB={rates['USB']} "
            f"SPI={rates['SPI']}"
        )

    print()
    print(f"RTCM frames observed during check: {rtcm_count}")
    print()

    print("========== DIAGNOSIS HINTS ==========")

    if tmode3 and tmode3["mode"] == "DISABLED":
        print("[LIKELY ISSUE] Base mode is disabled. The F9P is acting like a normal GPS receiver, not an RTK base.")

    elif tmode3 and tmode3["mode"] == "SURVEY_IN":
        if nav_svin and nav_svin["active"] and not nav_svin["valid"]:
            print("[LIKELY ISSUE] Survey-in is still running. RTCM may not start until survey-in becomes valid.")
        elif nav_svin and nav_svin["valid"]:
            print("[BASE POSITION] Survey-in is valid.")
        else:
            print("[CHECK] Survey-in mode is configured, but NAV-SVIN did not clearly report active/valid state.")

    elif tmode3 and tmode3["mode"] == "FIXED":
        print("[BASE POSITION] Fixed base mode is configured.")

    usb_enabled = any((rates and rates.get("USB", 0) > 0) for rates in cfg_msg_rates.values())

    if not usb_enabled:
        print("[LIKELY ISSUE] RTCM messages are not enabled on USB.")
    elif rtcm_count == 0:
        print("[LIKELY ISSUE] RTCM is configured on USB, but no correction frames were observed yet.")
    else:
        print("[GOOD] RTCM correction frames are present on USB.")


if __name__ == "__main__":
    main()