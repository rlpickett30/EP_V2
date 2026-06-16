"""
FP9_driver.py

u-blox ZED-F9P Driver

Responsibilities:
    - Connect to ZED-F9P over USB serial.
    - Read NMEA sentences.
    - Parse basic GPS fix data from GGA and RMC sentences.
    - Return raw hardware facts.

Does NOT:
    - Own EventBus logic.
    - Publish events.
    - Own node identity.
    - Claim true PPS lock from USB serial.

Notes:
    The SparkFun PPS LED can indicate that the ZED-F9P has a valid
    timepulse, but USB serial does not prove that the Raspberry Pi
    has measured the PPS edge.

    True PPS readiness for TDOA should come from the ZED-F9P PPS pin
    wired to a Raspberry Pi GPIO input.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import serial


class FP9Driver:
    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        baudrate: int = 9600,
        timeout: float = 1.0,
        debug: bool = True,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.debug = debug

        self.serial_port: Optional[serial.Serial] = None
        self.connected = False

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

    def log(self, message: str) -> None:
        if self.debug:
            print(f"[FP9Driver] {message}")

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def connect(self) -> None:
        try:
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )

            self.connected = True
            self.log(f"Connected to {self.port}")

        except Exception as error:
            self.connected = False
            self.serial_port = None
            self.log(f"Connection failed: {error}")

    def disconnect(self) -> None:
        try:
            if self.serial_port:
                self.serial_port.close()

        except Exception as error:
            self.log(f"Disconnect error: {error}")

        self.connected = False
        self.serial_port = None

    # --------------------------------------------------
    # NMEA Helpers
    # --------------------------------------------------

    def read_sentence(self) -> Optional[str]:
        if not self.connected or not self.serial_port:
            return None

        try:
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
            self.log(f"Read error: {error}")
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
            raw = float(value)

            degrees = int(raw // 100)
            minutes = raw - (degrees * 100)

            decimal = degrees + (minutes / 60.0)

            if hemisphere in ("S", "W"):
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
        parts = sentence.split(",")

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

            fix_quality = int(parts[6]) if parts[6] else 0
            satellites = int(parts[7]) if parts[7] else 0
            hdop = float(parts[8]) if parts[8] else None
            altitude_m = float(parts[9]) if parts[9] else None

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
                    "rtk_status": self.fix_quality_to_status(fix_quality),
                    "timestamp": time.time(),
                    "last_sentence": sentence,
                }
            )

        except Exception as error:
            self.log(f"GGA parse error: {error}")

    def parse_rmc(
        self,
        sentence: str,
    ) -> None:
        parts = sentence.split(",")

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
            self.log(f"RMC parse error: {error}")

    def parse_sentence(
        self,
        sentence: str,
    ) -> None:
        sentence_type = sentence.split(",", 1)[0]

        if sentence_type.endswith("GGA"):
            self.parse_gga(sentence)

        elif sentence_type.endswith("RMC"):
            self.parse_rmc(sentence)

    # --------------------------------------------------
    # GPS
    # --------------------------------------------------

    def get_gps_data(self) -> Dict[str, Any]:
        if not self.connected:
            return dict(self.last_gps_data)

        for _ in range(25):
            sentence = self.read_sentence()

            if sentence is None:
                continue

            self.parse_sentence(sentence)

            if self.last_gps_data["fix_valid"]:
                break

        return dict(self.last_gps_data)

    # --------------------------------------------------
    # PPS
    # --------------------------------------------------

    def get_pps_data(self) -> Dict[str, Any]:
        return {
            "pps_valid": False,
            "pps_source": "not_measured_by_usb_serial",
            "timestamp": time.time(),
        }

    # --------------------------------------------------
    # Status
    # --------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        return {
            "connected": self.connected,
            "port": self.port,
            "baudrate": self.baudrate,
        }


if __name__ == "__main__":
    driver = FP9Driver(
        debug=True,
    )

    try:
        driver.connect()

        while True:
            gps_data = driver.get_gps_data()
            pps_data = driver.get_pps_data()

            print()
            print("GPS")
            print(gps_data)

            print()
            print("PPS")
            print(pps_data)

            time.sleep(2)

    except KeyboardInterrupt:
        print()
        print("Shutdown requested")

    finally:
        driver.disconnect()