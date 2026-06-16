"""
FP9_driver.py

u-blox ZED-F9P Driver

Responsibilities:

- Connect to ZED-F9P
- Read GPS data
- Read PPS status
- Return raw hardware facts

This module intentionally knows nothing about:

- EventBus
- Dispatchers
- Managers
- GPS_LOCK
- GPS_COORD
- PPS_LOCK
- Event IDs
"""

from __future__ import annotations

import time
import serial


class FP9Driver:

    def __init__(
        self,
        port="/dev/ttyACM0",
        baudrate=9600,
        timeout=1.0,
        debug=True
    ):

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.debug = debug

        self.serial_port = None

        self.connected = False

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:

            print(
                f"[FP9Driver] {message}"
            )

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def connect(self):

        try:

            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )

            self.connected = True

            self.log(
                f"Connected to {self.port}"
            )

        except Exception as e:

            self.connected = False

            self.log(
                f"Connection failed: {e}"
            )

    def disconnect(self):

        try:

            if self.serial_port:

                self.serial_port.close()

        except Exception as e:

            self.log(
                f"Disconnect error: {e}"
            )

        self.connected = False

    # --------------------------------------------------
    # GPS
    # --------------------------------------------------

    def get_gps_data(self):

        #
        # Placeholder until
        # UBX/NMEA parsing is added
        #

        return {

            "fix_valid": False,

            "latitude": None,

            "longitude": None,

            "altitude_m": None,

            "satellites": 0,

            "hdop": None,

            "timestamp": time.time()
        }

    # --------------------------------------------------
    # PPS
    # --------------------------------------------------

    def get_pps_data(self):

        #
        # Placeholder until PPS
        # monitoring is implemented
        #

        return {

            "pps_valid": False,

            "timestamp": time.time()
        }

    # --------------------------------------------------
    # Status
    # --------------------------------------------------

    def get_status(self):

        return {

            "connected": self.connected,

            "port": self.port,

            "baudrate": self.baudrate
        }


# ------------------------------------------------------
# Standalone Test
# ------------------------------------------------------

if __name__ == "__main__":

    driver = FP9Driver(
        debug=True
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

            time.sleep(5)

    except KeyboardInterrupt:

        print()
        print("Shutdown requested")

    finally:

        driver.disconnect()