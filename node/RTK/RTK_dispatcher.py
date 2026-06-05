"""
RTK_dispatcher.py

Responsibilities:

- Load RTK configuration
- Track GPS state
- Track PPS state
- Publish state changes
- Publish coordinate updates
- Coordinate managers and services

This module intentionally knows nothing about:

- UART
- UBX parsing
- Hardware details
"""

from __future__ import annotations

import json
import time

from RTK.GPS_manager import GPSManager
from RTK.PPS_manager import PPSManager
from RTK.RTK_event_services import RTKEventServices


class RTKDispatcher:

    def __init__(
        self,
        event_bus,
        config_path="RTK/RTK_config.json",
        debug=True
    ):

        self.debug = debug

        self.config_path = config_path

        self.config = self.load_config()

        self.gps_manager = GPSManager(
            debug=debug
        )

        self.pps_manager = PPSManager(
            debug=debug
        )

        self.event_services = RTKEventServices(
            event_bus=event_bus,
            debug=debug
        )

        # ------------------------------------------
        # State Tracking
        # ------------------------------------------

        self.gps_locked = False

        self.pps_locked = False

        self.last_coord_publish = 0

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:

            print(
                f"[RTKDispatcher] {message}"
            )

    # --------------------------------------------------
    # Config
    # --------------------------------------------------

    def load_config(self):

        with open(
            self.config_path,
            "r"
        ) as file:

            return json.load(file)

    # --------------------------------------------------
    # Startup
    # --------------------------------------------------

    def start(self):

        self.log(
            "RTK subsystem started"
        )

        while True:

            self.check_gps()

            self.check_pps()

            self.publish_coordinates()

            time.sleep(1)

    # --------------------------------------------------
    # GPS State Machine
    # --------------------------------------------------

    def check_gps(self):

        gps = self.gps_manager.get_snapshot()

        fix_valid = gps["fix_valid"]

        if fix_valid and not self.gps_locked:

            self.gps_locked = True

            gps["event_type"] = "GPS_LOCK"

            self.event_services.publish_gps_lock(
                gps
            )

            self.log(
                "GPS lock acquired"
            )

        elif not fix_valid and self.gps_locked:

            self.gps_locked = False

            gps["event_type"] = "GPS_LOST"

            self.event_services.publish_gps_lost(
                gps
            )

            self.log(
                "GPS lock lost"
            )

    # --------------------------------------------------
    # PPS State Machine
    # --------------------------------------------------

    def check_pps(self):

        pps = self.pps_manager.get_snapshot()

        pps_valid = pps["pps_valid"]

        if pps_valid and not self.pps_locked:

            self.pps_locked = True

            pps["event_type"] = "PPS_LOCK"

            self.event_services.publish_pps_lock(
                pps
            )

            self.log(
                "PPS lock acquired"
            )

        elif not pps_valid and self.pps_locked:

            self.pps_locked = False

            pps["event_type"] = "PPS_LOST"

            self.event_services.publish_pps_lost(
                pps
            )

            self.log(
                "PPS lock lost"
            )

    # --------------------------------------------------
    # Coordinate Publishing
    # --------------------------------------------------

    def publish_coordinates(self):

        interval = self.config[
            "gps"
        ][
            "coord_publish_interval_sec"
        ]

        now = time.time()

        if (
            now - self.last_coord_publish
            < interval
        ):

            return

        gps = self.gps_manager.get_snapshot()

        if not gps["fix_valid"]:

            return

        gps["event_type"] = "GPS_COORD"

        self.event_services.publish_gps_coord(
            gps
        )

        self.last_coord_publish = now

        self.log(
            "Published GPS coordinates"
        )