#!/usr/bin/env python3
# ============================================================
# driver_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Environmental
#
# Role:
#   Manager
#
# Purpose:
#   Own environmental sensor driver lifecycle and return unified
#   environmental sensor snapshots to EnvironmentalDispatcher.
#
# Expected config source:
#   environmental_config.json
#
# Expected config section:
#   config["enabled"], config["sample_hz"],
#   config["sea_level_pressure_hpa"], config["sensors"]
#
# Does:
#   - Start only configured environmental sensor drivers
#   - Stop environmental sensor drivers
#   - Create supported environmental sensor drivers
#   - Collect sensor snapshots
#   - Mark sensor online status from driver snapshots
#   - Return failure snapshots for disabled or failed sensors
#   - Preserve driver startup errors for dispatcher visibility
#
# Does NOT:
#   - Publish events
#   - Subscribe to the event bus
#   - Decide whether a state or reading should be published
#   - Own node identity
#   - Own environmental workflow
#   - Build ENVIRO_STATE or ENVIRO_EVENT payloads
#
# Owner:
#   environmental_dispatcher.py
#
# ============================================================
from __future__ import annotations

import time
from typing import Any
from typing import Dict
from typing import Optional


class DriverManager:

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        debug: bool = True,
    ):

        self.config = config or {}
        self.debug = debug

        self.enabled = bool(
            self.config.get(
                "enabled",
                True,
            )
        )

        self.sample_hz = float(
            self.config.get(
                "sample_hz",
                1.0,
            )
        )

        self.sea_level_pressure_hpa = float(
            self.config.get(
                "sea_level_pressure_hpa",
                1013.25,
            )
        )

        self.sensor_config = self.config.get(
            "sensors",
            {},
        )

        self.drivers: Dict[str, Any] = {}
        self.start_errors: Dict[str, Optional[str]] = {}

    # ============================================================
    # DEBUG
    # ============================================================

    def log(
        self,
        message: str,
    ) -> None:

        if self.debug:
            print(
                f"[DriverManager] {message}"
            )

    # ============================================================
    # LIFECYCLE
    # ============================================================

    def start(
        self,
    ) -> None:

        if not self.enabled:
            self.log(
                "Environmental drivers disabled by config"
            )
            return

        self.log(
            "Starting environmental drivers..."
        )

        for sensor_name in self.get_configured_sensor_names():
            if self.is_sensor_enabled(
                sensor_name
            ):
                self.start_sensor(
                    sensor_name
                )
            else:
                self.start_errors[sensor_name] = "sensor_disabled"
                self.log(
                    f"{sensor_name} disabled by config"
                )

    def stop(
        self,
    ) -> None:

        self.log(
            "Stopping environmental drivers..."
        )

        for sensor_name, driver in list(
            self.drivers.items()
        ):
            try:
                driver.stop()
                self.log(
                    f"{sensor_name} stopped"
                )

            except Exception as error:
                self.log(
                    f"{sensor_name} stop error: {error}"
                )

        self.drivers.clear()

    # ============================================================
    # SENSOR CONFIG
    # ============================================================

    def get_configured_sensor_names(
        self,
    ):

        if self.sensor_config:
            return list(
                self.sensor_config.keys()
            )

        return [
            "sht45",
            "dps310",
        ]

    def is_sensor_enabled(
        self,
        sensor_name: str,
    ) -> bool:

        sensor_settings = self.sensor_config.get(
            sensor_name,
            {},
        )

        return bool(
            sensor_settings.get(
                "enabled",
                False,
            )
        )

    # ============================================================
    # DRIVER START
    # ============================================================

    def start_sensor(
        self,
        sensor_name: str,
    ) -> None:

        self.drivers[sensor_name] = None
        self.start_errors[sensor_name] = None

        try:
            driver = self.create_driver(
                sensor_name
            )

            driver.start()

            self.drivers[sensor_name] = driver
            self.log(
                f"{sensor_name} started"
            )

        except Exception as error:
            self.drivers[sensor_name] = None
            self.start_errors[sensor_name] = (
                f"{type(error).__name__}: {error}"
            )
            self.log(
                f"{sensor_name} startup failed: {error}"
            )

    def create_driver(
        self,
        sensor_name: str,
    ):

        sensor_key = sensor_name.strip().lower()

        if sensor_key == "sht45":
            from environmental.SHT45_driver import SHT45Driver

            return SHT45Driver(
                sample_hz=self.sample_hz,
            )

        if sensor_key == "dps310":
            from environmental.DPS310_driver import DPS310Driver

            return DPS310Driver(
                sample_hz=self.sample_hz,
                sea_level_pressure_hpa=self.sea_level_pressure_hpa,
            )

        if sensor_key == "bmp390":
            from environmental.BMP390_driver import BMP390Driver

            return BMP390Driver(
                sample_hz=self.sample_hz,
                sea_level_pressure_hpa=self.sea_level_pressure_hpa,
            )

        raise ValueError(
            f"Unsupported environmental sensor: {sensor_name}"
        )

    # ============================================================
    # SNAPSHOTS
    # ============================================================

    def get_snapshot(
        self,
    ) -> Dict[str, Any]:

        snapshot: Dict[str, Any] = {
            "timestamp": time.time(),
            "enabled": self.enabled,
        }

        for sensor_name in self.get_configured_sensor_names():
            snapshot[sensor_name] = self.get_sensor_snapshot(
                sensor_name
            )

        return snapshot

    def get_sensor_snapshot(
        self,
        sensor_name: str,
    ) -> Dict[str, Any]:

        if not self.enabled:
            return self.failure_snapshot(
                sensor_name=sensor_name,
                last_error="environmental_disabled",
            )

        if not self.is_sensor_enabled(
            sensor_name
        ):
            return self.failure_snapshot(
                sensor_name=sensor_name,
                last_error="sensor_disabled",
            )

        driver = self.drivers.get(
            sensor_name
        )

        start_error = self.start_errors.get(
            sensor_name
        )

        if driver is None:
            return self.failure_snapshot(
                sensor_name=sensor_name,
                last_error=start_error or "driver_not_started",
            )

        try:
            sensor_snapshot = driver.get_snapshot()
            started = bool(
                driver.is_started()
            )

            sensor_snapshot["started"] = started
            sensor_snapshot["online"] = bool(
                started
                and sensor_snapshot.get(
                    "driver_start_monotonic"
                )
                is not None
                and sensor_snapshot.get(
                    "sample_count",
                    0,
                )
                > 0
                and not sensor_snapshot.get(
                    "last_error"
                )
            )

            return sensor_snapshot

        except Exception as error:
            return self.failure_snapshot(
                sensor_name=sensor_name,
                last_error=f"{type(error).__name__}: {error}",
            )

    def failure_snapshot(
        self,
        sensor_name: str,
        last_error: Optional[str],
    ) -> Dict[str, Any]:

        snapshot = {
            "driver": self.get_driver_label(
                sensor_name
            ),
            "started": False,
            "online": False,
            "driver_start_monotonic": None,
            "last_sample_monotonic": None,
            "sample_count": 0,
            "last_error": last_error or "driver_not_started",
            "last_error_monotonic": time.monotonic(),
            "snapshot_monotonic": time.monotonic(),
        }

        snapshot.update(
            self.get_empty_reading_fields(
                sensor_name
            )
        )

        return snapshot

    def get_driver_label(
        self,
        sensor_name: str,
    ) -> str:

        labels = {
            "sht45": "SHT45Driver",
            "dps310": "DPS310Driver",
            "bmp390": "BMP390Driver",
        }

        return labels.get(
            sensor_name,
            f"{sensor_name}Driver",
        )

    def get_empty_reading_fields(
        self,
        sensor_name: str,
    ) -> Dict[str, Any]:

        if sensor_name == "sht45":
            return {
                "temperature_c": None,
                "humidity_rh": None,
            }

        if sensor_name in {
            "dps310",
            "bmp390",
        }:
            return {
                "sea_level_pressure_hpa": self.sea_level_pressure_hpa,
                "pressure_hpa": None,
                "temperature_c": None,
                "altitude_m": None,
            }

        return {}


# ============================================================
# STANDALONE TEST
# ============================================================

if __name__ == "__main__":

    manager = DriverManager(
        config={
            "enabled": True,
            "sample_hz": 1.0,
            "sea_level_pressure_hpa": 1013.25,
            "sensors": {
                "sht45": {
                    "enabled": True,
                },
                "dps310": {
                    "enabled": True,
                },
                "bmp390": {
                    "enabled": False,
                },
            },
        },
        debug=True,
    )

    try:
        manager.start()

        while True:
            print()
            print("=" * 60)
            print(
                manager.get_snapshot()
            )

            time.sleep(
                5
            )

    except KeyboardInterrupt:
        print(
            "\nShutdown requested"
        )

    finally:
        manager.stop()