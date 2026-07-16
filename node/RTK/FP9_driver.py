# ============================================================
# FP9_driver.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   RTK
#
# Role:
#   Helper Script
#
# Purpose:
#   Provide low-level ZED-F9P serial access, NMEA parsing, RTCM packet
#   extraction, RTCM writing, and temporary Survey-In configuration support.
#
# Expected config source:
#   RTK_config.json
#
# Expected config section:
#   config["gps"]
#
# Does:
#   - Connect to the ZED-F9P over USB serial
#   - Read mixed USB serial data from the receiver
#   - Parse NMEA GGA and RMC sentences
#   - Preserve latest GPS fix data
#   - Extract RTCM3 packets produced by a base receiver
#   - Write RTCM3 packets into a rover receiver
#   - Send basic UBX configuration messages for Survey-In base mode
#   - Return raw hardware and driver status
#
# Does NOT:
#   - Own EventBus logic
#   - Publish events
#   - Own node identity
#   - Claim true PPS lock from USB serial
#   - Decide RTK base or rover role
#   - Decide TDOA readiness
#
# Owner:
#   GPS_manager.py
#
# ============================================================

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import serial


class FP9Driver:

    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        baudrate: int = 38400,
        timeout: float = 0.05,
        debug: bool = True,
    ):
        self.port = port
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self.debug = debug

        self.serial_port: Optional[serial.Serial] = None
        self.connected = False

        self.serial_lock = threading.RLock()

        self.nmea_buffer = b""
        self.rtcm_buffer = b""
        self.pending_rtcm_packets: List[bytes] = []

        self.last_gps_data: Dict[str, Any] = {
            "fix_valid": False,
            "latitude": None,
            "longitude": None,
            "altitude_m": None,
            "satellites": 0,
            "hdop": None,
            "fix_quality": 0,
            "rtk_status": "NO_FIX",
            "timestamp": time.time(),
            "last_sentence": None,
        }

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(
        self,
        message: str
    ) -> None:

        if self.debug:
            print(
                f"[FP9Driver] {message}"
            )

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def connect(
        self
    ) -> None:

        with self.serial_lock:

            if self.connected and self.serial_port:
                return

            try:
                self.serial_port = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout,
                    write_timeout=1,
                )

                self.connected = True
                self.log(
                    f"Connected to {self.port} at {self.baudrate} baud"
                )

            except Exception as error:
                self.connected = False
                self.serial_port = None
                self.log(
                    f"Connection failed: {error}"
                )

    def disconnect(
        self
    ) -> None:

        with self.serial_lock:

            try:
                if self.serial_port:
                    self.serial_port.close()

            except Exception as error:
                self.log(
                    f"Disconnect error: {error}"
                )

            self.connected = False
            self.serial_port = None

    def reconnect(
        self
    ) -> None:

        self.disconnect()
        time.sleep(0.25)
        self.connect()

    # --------------------------------------------------
    # Serial I/O
    # --------------------------------------------------

    def read_available(
        self,
        max_bytes: int = 4096
    ) -> bytes:

        if not self.connected or not self.serial_port:
            return b""

        try:
            with self.serial_lock:
                return self.serial_port.read(
                    max_bytes
                )

        except Exception as error:
            self.log(
                f"Read error: {error}"
            )
            self.connected = False
            return b""

    def write_bytes(
        self,
        data: bytes
    ) -> int:

        if not data:
            return 0

        if not self.connected or not self.serial_port:
            return 0

        try:
            with self.serial_lock:
                written = self.serial_port.write(
                    data
                )
                self.serial_port.flush()
                return int(
                    written
                )

        except Exception as error:
            self.log(
                f"Write error: {error}"
            )
            self.connected = False
            return 0

    # --------------------------------------------------
    # Mixed Stream Processing
    # --------------------------------------------------

    def poll_serial(
        self,
        duration_sec: float = 0.20,
        read_size: int = 4096
    ) -> Dict[str, int]:

        if not self.connected:
            self.connect()

        start = time.time()

        stats = {
            "bytes_read": 0,
            "nmea_lines": 0,
            "rtcm_packets": 0,
        }

        while time.time() - start < duration_sec:
            data = self.read_available(
                read_size
            )

            if not data:
                continue

            result = self.process_bytes(
                data
            )

            stats["bytes_read"] += result["bytes_read"]
            stats["nmea_lines"] += result["nmea_lines"]
            stats["rtcm_packets"] += result["rtcm_packets"]

        return stats

    def process_bytes(
        self,
        data: bytes
    ) -> Dict[str, int]:

        if not data:
            return {
                "bytes_read": 0,
                "nmea_lines": 0,
                "rtcm_packets": 0,
            }

        nmea_lines = self.process_nmea_bytes(
            data
        )

        rtcm_packets = self.process_rtcm_bytes(
            data
        )

        return {
            "bytes_read": len(data),
            "nmea_lines": nmea_lines,
            "rtcm_packets": rtcm_packets,
        }

    def process_nmea_bytes(
        self,
        data: bytes
    ) -> int:

        self.nmea_buffer += data

        if len(self.nmea_buffer) > 65536:
            self.nmea_buffer = self.nmea_buffer[-32768:]

        parsed_count = 0

        while b"\n" in self.nmea_buffer:
            raw_line, self.nmea_buffer = self.nmea_buffer.split(
                b"\n",
                1,
            )

            sentence = raw_line.decode(
                "ascii",
                errors="ignore",
            ).strip()

            if not sentence.startswith("$"):
                continue

            self.parse_sentence(
                sentence
            )

            parsed_count += 1

        return parsed_count

    def process_rtcm_bytes(
        self,
        data: bytes
    ) -> int:

        self.rtcm_buffer += data

        if len(self.rtcm_buffer) > 131072:
            self.rtcm_buffer = self.rtcm_buffer[-65536:]

        packets, self.rtcm_buffer = self.extract_rtcm_packets(
            self.rtcm_buffer
        )

        if packets:
            self.pending_rtcm_packets.extend(
                packets
            )

        return len(
            packets
        )

    def extract_rtcm_packets(
        self,
        buffer: bytes
    ) -> Tuple[List[bytes], bytes]:

        packets: List[bytes] = []

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

            # RTCM3 reserves the upper 6 bits of byte 1.
            # If they are nonzero, this was probably a random 0xD3 byte.
            if buffer[1] & 0xFC:
                buffer = buffer[1:]
                continue

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

    def consume_rtcm_packets(
        self
    ) -> List[bytes]:

        packets = self.pending_rtcm_packets
        self.pending_rtcm_packets = []
        return packets

    # --------------------------------------------------
    # NMEA Helpers
    # --------------------------------------------------

    def read_sentence(
        self
    ) -> Optional[str]:

        if not self.connected or not self.serial_port:
            return None

        try:
            with self.serial_lock:
                raw = self.serial_port.readline()

            if not raw:
                return None

            sentence = raw.decode(
                "ascii",
                errors="ignore",
            ).strip()

            if not sentence.startswith("$"):
                return None

            return sentence

        except Exception as error:
            self.log(
                f"Read sentence error: {error}"
            )
            self.connected = False
            return None

    def nmea_coord_to_decimal(
        self,
        value: str,
        hemisphere: str,
    ) -> Optional[float]:

        if not value or not hemisphere:
            return None

        try:
            raw = float(
                value
            )

            degrees = int(
                raw // 100
            )
            minutes = raw - (
                degrees * 100
            )

            decimal = degrees + (
                minutes / 60.0
            )

            if hemisphere in (
                "S",
                "W",
            ):
                decimal *= -1

            return decimal

        except Exception:
            return None

    def fix_quality_to_status(
        self,
        fix_quality: int,
    ) -> str:

        mapping = {
            0: "NO_FIX",
            1: "GPS",
            2: "DGPS",
            4: "RTK_FIXED",
            5: "RTK_FLOAT",
            6: "DEAD_RECKONING",
        }

        return mapping.get(
            fix_quality,
            f"FIX_{fix_quality}",
        )

    # --------------------------------------------------
    # NMEA Parsers
    # --------------------------------------------------

    def parse_gga(
        self,
        sentence: str,
    ) -> None:

        parts = sentence.split(
            ","
        )

        if len(parts) < 10:
            return

        try:
            latitude = self.nmea_coord_to_decimal(
                parts[2],
                parts[3],
            )

            longitude = self.nmea_coord_to_decimal(
                parts[4],
                parts[5],
            )

            fix_quality = int(
                parts[6]
            ) if parts[6] else 0

            satellites = int(
                parts[7]
            ) if parts[7] else 0

            hdop = float(
                parts[8]
            ) if parts[8] else None

            altitude_m = float(
                parts[9]
            ) if parts[9] else None

            fix_valid = (
                fix_quality > 0
                and latitude is not None
                and longitude is not None
            )

            self.last_gps_data.update(
                {
                    "fix_valid": fix_valid,
                    "latitude": latitude,
                    "longitude": longitude,
                    "altitude_m": altitude_m,
                    "satellites": satellites,
                    "hdop": hdop,
                    "fix_quality": fix_quality,
                    "rtk_status": self.fix_quality_to_status(
                        fix_quality
                    ),
                    "timestamp": time.time(),
                    "last_sentence": sentence,
                }
            )

        except Exception as error:
            self.log(
                f"GGA parse error: {error}"
            )

    def parse_rmc(
        self,
        sentence: str,
    ) -> None:

        parts = sentence.split(
            ","
        )

        if len(parts) < 7:
            return

        try:
            status = parts[2]

            latitude = self.nmea_coord_to_decimal(
                parts[3],
                parts[4],
            )

            longitude = self.nmea_coord_to_decimal(
                parts[5],
                parts[6],
            )

            if (
                status == "A"
                and latitude is not None
                and longitude is not None
            ):
                self.last_gps_data.update(
                    {
                        "fix_valid": True,
                        "latitude": latitude,
                        "longitude": longitude,
                        "timestamp": time.time(),
                        "last_sentence": sentence,
                    }
                )

        except Exception as error:
            self.log(
                f"RMC parse error: {error}"
            )

    def parse_sentence(
        self,
        sentence: str,
    ) -> None:

        sentence_type = sentence.split(
            ",",
            1,
        )[0]

        if sentence_type.endswith(
            "GGA"
        ):
            self.parse_gga(
                sentence
            )

        elif sentence_type.endswith(
            "RMC"
        ):
            self.parse_rmc(
                sentence
            )

    # --------------------------------------------------
    # GPS
    # --------------------------------------------------

    def get_gps_data(
        self
    ) -> Dict[str, Any]:

        if not self.connected:
            self.connect()

        self.poll_serial(
            duration_sec=0.20
        )

        return dict(
            self.last_gps_data
        )

    # --------------------------------------------------
    # RTK / UBX Config
    # --------------------------------------------------

    def configure_survey_in_base(
        self,
        duration_sec: int = 120,
        accuracy_limit_mm: int = 5000,
        rtcm_messages: Optional[List[str]] = None,
        port_type: str = "USB",
    ) -> bool:

        if rtcm_messages is None:
            rtcm_messages = [
                "1005",
                "1077",
                "1087",
                "1097",
                "1127",
                "1230",
            ]

        try:
            from pyubx2 import UBXMessage

        except Exception as error:
            self.log(
                f"pyubx2 is required for base configuration: {error}"
            )
            return False

        if not self.connected:
            self.connect()

        if not self.connected or not self.serial_port:
            return False

        try:
            layers = 1
            transaction = 0

            rtcm_cfg = []

            for rtcm_type in rtcm_messages:
                rtcm_cfg.append(
                    [
                        f"CFG_MSGOUT_RTCM_3X_TYPE{rtcm_type}_{port_type}",
                        1,
                    ]
                )

            rtcm_msg = UBXMessage.config_set(
                layers,
                transaction,
                rtcm_cfg,
            )

            acc_limit_01mm = int(
                round(
                    float(accuracy_limit_mm) / 0.1,
                    0,
                )
            )

            survey_cfg = [
                (
                    "CFG_TMODE_MODE",
                    1,
                ),
                (
                    "CFG_TMODE_SVIN_ACC_LIMIT",
                    acc_limit_01mm,
                ),
                (
                    "CFG_TMODE_SVIN_MIN_DUR",
                    int(duration_sec),
                ),
                (
                    f"CFG_MSGOUT_UBX_NAV_SVIN_{port_type}",
                    1,
                ),
            ]

            survey_msg = UBXMessage.config_set(
                layers,
                transaction,
                survey_cfg,
            )

            self.log(
                "Configuring RTCM output"
            )
            self.write_bytes(
                rtcm_msg.serialize()
            )
            time.sleep(
                0.25
            )

            self.log(
                "Configuring Survey-In base mode"
            )
            self.write_bytes(
                survey_msg.serialize()
            )

            return True

        except Exception as error:
            self.log(
                f"Survey-In config failed: {error}"
            )
            return False

    # --------------------------------------------------
    # PPS
    # --------------------------------------------------

    def get_pps_data(
        self
    ) -> Dict[str, Any]:

        return {
            "pps_valid": False,
            "pps_source": "not_measured_by_usb_serial",
            "timestamp": time.time(),
        }

    # --------------------------------------------------
    # Status
    # --------------------------------------------------

    def get_status(
        self
    ) -> Dict[str, Any]:

        return {
            "connected": self.connected,
            "port": self.port,
            "baudrate": self.baudrate,
            "pending_rtcm_packets": len(
                self.pending_rtcm_packets
            ),
        }


if __name__ == "__main__":

    driver = FP9Driver(
        debug=True,
    )

    try:
        driver.connect()

        while True:
            gps_data = driver.get_gps_data()

            print()
            print("GPS")
            print(gps_data)
            print("STATUS")
            print(driver.get_status())

            time.sleep(2)

    except KeyboardInterrupt:
        print()
        print("Shutdown requested")

    finally:
        driver.disconnect()
