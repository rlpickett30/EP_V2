"""
GPS_manager.py

Responsibilities:

- Own FP9 driver
- Create GPS snapshots
- Create GPS event IDs

This module intentionally knows nothing about:

- EventBus
- Dispatchers
- Publishers
- Subscribers
"""

from __future__ import annotations

import time

from RTK.FP9_driver import FP9Driver


class GPSManager:

    def __init__(
        self,
        port="/dev/ttyACM0",
        debug=True
    ):

        self.debug = debug

        self.driver = FP9Driver(
            port=port,
            debug=debug
        )

        self.driver.connect()

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:

            print(
                f"[GPSManager] {message}"
            )

    # --------------------------------------------------
    # Snapshot
    # --------------------------------------------------

    def get_snapshot(self):

        gps_data = self.driver.get_gps_data()

        event_utc = int(
            time.time()
        )

        snapshot = {

            "event_id":
                f"GPS_{event_utc}",

            "event_utc":
                event_utc,

            "fix_valid":
                gps_data["fix_valid"],

            "latitude":
                gps_data["latitude"],

            "longitude":
                gps_data["longitude"],

            "altitude_m":
                gps_data["altitude_m"],

            "satellites":
                gps_data["satellites"],

            "hdop":
                gps_data["hdop"]
        }

        return snapshot