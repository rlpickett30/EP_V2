"""
PPS_manager.py

Responsibilities:

- Own FP9 driver
- Create PPS snapshots
- Create PPS event IDs

This module intentionally knows nothing about:

- EventBus
- Dispatchers
- Publishers
- Subscribers
"""

from __future__ import annotations

import time

from RTK.FP9_driver import FP9Driver


class PPSManager:

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
                f"[PPSManager] {message}"
            )

    # --------------------------------------------------
    # Snapshot
    # --------------------------------------------------

    def get_snapshot(self):

        pps_data = self.driver.get_pps_data()

        event_utc = int(
            time.time()
        )

        snapshot = {

            "event_id":
                f"PPS_{event_utc}",

            "event_utc":
                event_utc,

            "pps_valid":
                pps_data["pps_valid"]
        }

        return snapshot