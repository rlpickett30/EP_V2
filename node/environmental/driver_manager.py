#!/usr/bin/env python3
"""
driver_manager.py

Environmental Driver Manager

Responsibilities:
- Create environmental sensor drivers
- Start environmental sensor drivers
- Stop environmental sensor drivers
- Collect sensor snapshots
- Return unified environmental data

This class DOES NOT:
- Publish events
- Subscribe to events
- Perform environmental analysis
- Handle GUI updates
- Handle database writes
"""

from __future__ import annotations

import time
from typing import Dict, Any

from environmental.SHT45_driver import SHT45Driver
from environmental.BMP390_driver import BMP390Driver


class DriverManager:

    def __init__(
        self,
        sample_hz: float = 1.0,
        sea_level_pressure_hpa: float = 1013.25,
        debug: bool = True
    ):

        self.debug = debug

        self.sample_hz = sample_hz
        self.sea_level_pressure_hpa = sea_level_pressure_hpa

        self.sht45 = None
        self.bmp390 = None

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message: str):

        if self.debug:
            print(f"[DriverManager] {message}")

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def start(self):

        self.log("Starting environmental drivers...")

        try:

            self.sht45 = SHT45Driver(
                sample_hz=self.sample_hz
            )

            self.sht45.start()

            self.log("SHT45 started")

        except Exception as e:

            self.log(f"SHT45 startup failed: {e}")

        try:

            self.bmp390 = BMP390Driver(
                sample_hz=self.sample_hz,
                sea_level_pressure_hpa=self.sea_level_pressure_hpa
            )

            self.bmp390.start()

            self.log("BMP390 started")

        except Exception as e:

            self.log(f"BMP390 startup failed: {e}")

    def stop(self):

        self.log("Stopping environmental drivers...")

        try:

            if self.sht45:
                self.sht45.stop()

        except Exception as e:

            self.log(f"SHT45 stop error: {e}")

        try:

            if self.bmp390:
                self.bmp390.stop()

        except Exception as e:

            self.log(f"BMP390 stop error: {e}")

    # --------------------------------------------------
    # Snapshots
    # --------------------------------------------------

    def get_snapshot(self) -> Dict[str, Any]:

        snapshot = {
            "timestamp": time.time(),
            "sht45": None,
            "bmp390": None
        }

        try:

            if self.sht45:
                snapshot["sht45"] = self.sht45.get_snapshot()

        except Exception as e:

            self.log(f"SHT45 snapshot error: {e}")

        try:

            if self.bmp390:
                snapshot["bmp390"] = self.bmp390.get_snapshot()

        except Exception as e:

            self.log(f"BMP390 snapshot error: {e}")

        return snapshot


# ------------------------------------------------------
# Standalone Test
# ------------------------------------------------------

if __name__ == "__main__":

    manager = DriverManager(debug=True)

    try:

        manager.start()

        while True:

            snapshot = manager.get_snapshot()

            print()
            print("=" * 60)
            print(snapshot)

            time.sleep(5)

    except KeyboardInterrupt:

        print("\nShutdown requested")

    finally:

        manager.stop()