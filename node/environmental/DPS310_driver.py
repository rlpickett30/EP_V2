#!/usr/bin/env python3
# ============================================================
# DPS310_driver.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Environmental
#
# Role:
#   Helper Script
#
# Purpose:
#   Provide a persistent, long-lived I2C driver for the Infineon DPS310
#   pressure sensor and expose latest raw pressure, temperature, and altitude
#   facts.
#
# Expected config source:
#   environmental_config.json
#
# Expected config section:
#   config["sample_hz"], config["sea_level_pressure_hpa"],
#   config["sensors"]["dps310"]
#
# Does:
#   - Own the DPS310 sensor for the lifetime of the process
#   - Start and stop the DPS310 sampling thread
#   - Read pressure from the DPS310
#   - Read temperature from the DPS310
#   - Calculate altitude using configured sea-level pressure
#   - Maintain a latest sensor snapshot
#   - Report sample counts and driver errors
#
# Does NOT:
#   - Publish events
#   - Subscribe to the event bus
#   - Make environmental workflow decisions
#   - Decide whether the environmental subsystem is online
#   - Own node identity
#   - Own configuration loading
#
# Owner:
#   driver_manager.py
#
# ============================================================

from __future__ import annotations

import math
import threading
import time
from typing import Any, Dict, Optional

import board
import busio
import adafruit_dps310


class DPS310Driver:
    def __init__(
        self,
        *,
        sample_hz: float = 1.0,
        sea_level_pressure_hpa: float = 1013.25
    ) -> None:
        if sample_hz <= 0:
            raise ValueError("sample_hz must be > 0")

        self.sample_hz = float(sample_hz)
        self.sea_level_pressure_hpa = float(sea_level_pressure_hpa)

        self._i2c: Optional[busio.I2C] = None
        self._sensor: Optional[adafruit_dps310.DPS310] = None

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False

        now_mono = time.monotonic()
        self._state: Dict[str, Any] = {
            "driver": "DPS310Driver",
            "sample_hz": self.sample_hz,
            "sea_level_pressure_hpa": self.sea_level_pressure_hpa,
            "driver_start_monotonic": None,
            "last_sample_monotonic": None,
            "sample_count": 0,
            "last_error": None,
            "last_error_monotonic": None,
            "pressure_hpa": None,
            "temperature_c": None,
            "altitude_m": None,
            "snapshot_monotonic": now_mono,
        }

    def start(self) -> None:
        if self._started:
            return

        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._sensor = adafruit_dps310.DPS310(self._i2c)

        with self._lock:
            self._state["driver_start_monotonic"] = time.monotonic()
            self._state["last_error"] = None
            self._state["last_error_monotonic"] = None
            self._state["snapshot_monotonic"] = time.monotonic()

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="DPS310DriverThread",
            daemon=True
        )
        self._thread.start()
        self._started = True

    def stop(self) -> None:
        self._stop_event.set()

        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

        self._thread = None
        self._started = False
        self._sensor = None
        self._i2c = None

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            snapshot = dict(self._state)
            snapshot["snapshot_monotonic"] = time.monotonic()
            return snapshot

    def is_started(self) -> bool:
        return self._started

    def _calculate_altitude_m(self, pressure_hpa: float) -> Optional[float]:
        try:
            return 44330.0 * (
                1.0 - math.pow(
                    pressure_hpa / self.sea_level_pressure_hpa,
                    1.0 / 5.255
                )
            )
        except Exception:
            return None

    def _run(self) -> None:
        assert self._sensor is not None

        period = 1.0 / self.sample_hz

        while not self._stop_event.is_set():
            try:
                pressure_hpa = float(self._sensor.pressure)
                temperature_c = float(self._sensor.temperature)
                altitude_m = self._calculate_altitude_m(pressure_hpa)

                with self._lock:
                    self._state["pressure_hpa"] = pressure_hpa
                    self._state["temperature_c"] = temperature_c
                    self._state["altitude_m"] = altitude_m
                    self._state["last_sample_monotonic"] = time.monotonic()
                    self._state["sample_count"] += 1
                    self._state["last_error"] = None
                    self._state["last_error_monotonic"] = None
                    self._state["snapshot_monotonic"] = time.monotonic()

            except Exception as error:
                with self._lock:
                    self._state["last_error"] = f"{type(error).__name__}: {error}"
                    self._state["last_error_monotonic"] = time.monotonic()
                    self._state["snapshot_monotonic"] = time.monotonic()

            time.sleep(period)


if __name__ == "__main__":
    driver = DPS310Driver(sample_hz=1.0)

    try:
        driver.start()
        print("DPS310 driver started. Printing 10 samples.")

        for _ in range(10):
            print(driver.get_snapshot())
            time.sleep(1.0)

    finally:
        driver.stop()
        print("DPS310 driver stopped.")
