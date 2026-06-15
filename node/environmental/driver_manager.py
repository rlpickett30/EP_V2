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
from typing import Any, Dict, Optional

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

        self.sht45: Optional[SHT45Driver] = None
        self.bmp390: Optional[BMP390Driver] = None

        self.sht45_start_error: Optional[str] = None
        self.bmp390_start_error: Optional[str] = None

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

        self._start_sht45()
        self._start_bmp390()

    def _start_sht45(self):

        self.sht45 = None
        self.sht45_start_error = None

        try:
            driver = SHT45Driver(
                sample_hz=self.sample_hz
            )

            driver.start()

            self.sht45 = driver
            self.log("SHT45 started")

        except Exception as error:
            self.sht45 = None
            self.sht45_start_error = f"{type(error).__name__}: {error}"
            self.log(f"SHT45 startup failed: {error}")

    def _start_bmp390(self):

        self.bmp390 = None
        self.bmp390_start_error = None

        try:
            driver = BMP390Driver(
                sample_hz=self.sample_hz,
                sea_level_pressure_hpa=self.sea_level_pressure_hpa
            )

            driver.start()

            self.bmp390 = driver
            self.log("BMP390 started")

        except Exception as error:
            self.bmp390 = None
            self.bmp390_start_error = f"{type(error).__name__}: {error}"
            self.log(f"BMP390 startup failed: {error}")

    def stop(self):

        self.log("Stopping environmental drivers...")

        try:
            if self.sht45:
                self.sht45.stop()

        except Exception as error:
            self.log(f"SHT45 stop error: {error}")

        try:
            if self.bmp390:
                self.bmp390.stop()

        except Exception as error:
            self.log(f"BMP390 stop error: {error}")

        self.sht45 = None
        self.bmp390 = None

    # --------------------------------------------------
    # Snapshots
    # --------------------------------------------------

    def _failure_snapshot(
        self,
        *,
        driver_name: str,
        last_error: Optional[str],
        extra_fields: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:

        snapshot = {
            "driver": driver_name,
            "started": False,
            "online": False,
            "driver_start_monotonic": None,
            "last_sample_monotonic": None,
            "sample_count": 0,
            "last_error": last_error or "driver_not_started",
            "last_error_monotonic": time.monotonic(),
            "snapshot_monotonic": time.monotonic()
        }

        if extra_fields:
            snapshot.update(extra_fields)

        return snapshot

    def _driver_snapshot(
        self,
        driver,
        *,
        driver_name: str,
        start_error: Optional[str],
        extra_fields: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:

        if driver is None:
            return self._failure_snapshot(
                driver_name=driver_name,
                last_error=start_error,
                extra_fields=extra_fields
            )

        try:
            snapshot = driver.get_snapshot()
            started = bool(driver.is_started())

            snapshot["started"] = started
            snapshot["online"] = bool(
                started
                and snapshot.get("driver_start_monotonic") is not None
                and not snapshot.get("last_error")
            )

            return snapshot

        except Exception as error:
            return self._failure_snapshot(
                driver_name=driver_name,
                last_error=f"{type(error).__name__}: {error}",
                extra_fields=extra_fields
            )

    def get_snapshot(self) -> Dict[str, Any]:

        return {
            "timestamp": time.time(),
            "sht45": self._driver_snapshot(
                self.sht45,
                driver_name="SHT45Driver",
                start_error=self.sht45_start_error,
                extra_fields={
                    "temperature_c": None,
                    "humidity_rh": None
                }
            ),
            "bmp390": self._driver_snapshot(
                self.bmp390,
                driver_name="BMP390Driver",
                start_error=self.bmp390_start_error,
                extra_fields={
                    "sea_level_pressure_hpa": self.sea_level_pressure_hpa,
                    "pressure_hpa": None,
                    "temperature_c": None,
                    "altitude_m": None
                }
            )
        }


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