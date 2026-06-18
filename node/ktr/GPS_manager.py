"""
GPS_manager.py

Responsibilities:

- Own FP9 driver
- Create GPS snapshots
- Create GPS event IDs
- Preserve GPS / DGPS / RTK fix metadata from the FP9 driver

This module intentionally knows nothing about:

- EventBus
- Dispatchers
- Publishers
- Subscribers
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from RTK.FP9_driver import FP9Driver


class GPSManager:

    FIX_QUALITY_LABELS = {
        0: "NO_FIX",
        1: "GPS",
        2: "DGPS_SBAS",
        4: "RTK_FIXED",
        5: "RTK_FLOAT",
        6: "DEAD_RECKONING"
    }

    RTK_FIX_QUALITIES = {
        4,
        5
    }

    RTK_FIXED_QUALITY = 4
    RTK_FLOAT_QUALITY = 5

    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        debug: bool = True
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

    def log(
        self,
        message: str
    ) -> None:

        if self.debug:

            print(
                f"[GPSManager] {message}"
            )

    # --------------------------------------------------
    # Snapshot
    # --------------------------------------------------

    def get_snapshot(
        self
    ) -> Dict[str, Any]:

        gps_data = self.driver.get_gps_data()

        event_utc = int(
            time.time()
        )

        fix_quality = self.get_fix_quality(
            gps_data
        )

        fix_label = self.get_fix_label(
            gps_data=gps_data,
            fix_quality=fix_quality
        )

        fix_valid = bool(
            gps_data.get(
                "fix_valid",
                False
            )
        )

        rtk_online = self.is_rtk_online(
            fix_quality
        )

        rtk_fixed = self.is_rtk_fixed(
            fix_quality
        )

        rtk_float = self.is_rtk_float(
            fix_quality
        )

        snapshot = {

            "event_id":
                self.build_event_id(
                    event_utc
                ),

            "event_utc":
                event_utc,

            "fix_valid":
                fix_valid,

            "gps_online":
                fix_valid,

            "gps_locked":
                fix_valid,

            "latitude":
                gps_data.get(
                    "latitude"
                ),

            "longitude":
                gps_data.get(
                    "longitude"
                ),

            "altitude_m":
                gps_data.get(
                    "altitude_m"
                ),

            "satellites":
                gps_data.get(
                    "satellites",
                    0
                ),

            "hdop":
                gps_data.get(
                    "hdop"
                ),

            "fix_quality":
                fix_quality,

            "fix_label":
                fix_label,

            "rtk_status":
                fix_label,

            "rtk_state":
                fix_label,

            "rtk_online":
                rtk_online,

            "rtk_fixed":
                rtk_fixed,

            "rtk_float":
                rtk_float,

            "last_sentence":
                gps_data.get(
                    "last_sentence"
                ),

            "driver_timestamp":
                gps_data.get(
                    "timestamp"
                )
        }

        return snapshot

    # --------------------------------------------------
    # Event IDs
    # --------------------------------------------------

    def build_event_id(
        self,
        event_utc: int
    ) -> str:

        return f"GPS_{event_utc}"

    # --------------------------------------------------
    # Fix Quality Helpers
    # --------------------------------------------------

    def get_fix_quality(
        self,
        gps_data: Dict[str, Any]
    ) -> int:

        raw_value = gps_data.get(
            "fix_quality",
            0
        )

        try:

            return int(
                raw_value
            )

        except (
            TypeError,
            ValueError
        ):

            return 0

    def get_fix_label(
        self,
        gps_data: Dict[str, Any],
        fix_quality: int
    ) -> str:

        driver_status = gps_data.get(
            "rtk_status"
        )

        if driver_status:

            return str(
                driver_status
            )

        return self.FIX_QUALITY_LABELS.get(
            fix_quality,
            "UNKNOWN"
        )

    def is_rtk_online(
        self,
        fix_quality: int
    ) -> bool:

        return fix_quality in self.RTK_FIX_QUALITIES

    def is_rtk_fixed(
        self,
        fix_quality: int
    ) -> bool:

        return fix_quality == self.RTK_FIXED_QUALITY

    def is_rtk_float(
        self,
        fix_quality: int
    ) -> bool:

        return fix_quality == self.RTK_FLOAT_QUALITY