# ============================================================
# PPS_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   RTK
#
# Role:
#   Manager
#
# Purpose:
#   Read Linux kernel PPS state from /sys/class/pps/pps0/assert and create
#   canonical PPS snapshots for RTKDispatcher.
#
# Expected config source:
#   RTK_config.json
#
# Expected config section:
#   config["pps"]
#
# Does:
#   - Read Linux kernel PPS assert timestamps
#   - Detect whether the PPS device is present
#   - Detect whether PPS is online and recently valid
#   - Track PPS sequence changes
#   - Report latest PPS kernel timestamp
#   - Build PPS snapshots for RTKDispatcher
#
# Does NOT:
#   - Own the serial GPS port
#   - Publish events
#   - Subscribe to events
#   - Access the event bus
#   - Configure the ZED-F9P
#   - Pair PPS edges with RMC UTC labels yet
#
# Owner:
#   RTK_dispatcher.py
#
# ============================================================

from __future__ import annotations

import re
import time

from pathlib import Path
from typing import Any
from typing import Dict
from typing import Optional


PPS_ASSERT_PATTERN = re.compile(
    r"(?P<sec>\d+)\.(?P<nsec>\d+)#(?P<seq>\d+)"
)


class PPSManager:

    def __init__(
        self,
        gpio_bcm: int | None = None,
        pps_device: str = "pps0",
        max_age_sec: float = 2.5,
        debug: bool = True,
        **kwargs
    ):

        self.debug = debug
        self.pps_device = pps_device
        self.max_age_sec = max_age_sec

        self.pps_dir = Path("/sys/class/pps") / self.pps_device
        self.assert_path = self.pps_dir / "assert"
        self.name_path = self.pps_dir / "name"

        self.last_seq: Optional[int] = None
        self.last_kernel_time: Optional[float] = None
        self.last_seen_monotonic: Optional[float] = None
        self.last_error: Optional[str] = None

        self.log(
            f"Using kernel PPS path: {self.assert_path}"
        )

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(
        self,
        message
    ):

        if self.debug:

            print(
                f"[PPSManager] {message}"
            )

    # --------------------------------------------------
    # Kernel PPS Read
    # --------------------------------------------------

    def read_kernel_pps(
        self
    ) -> Dict[str, Any]:

        if not self.assert_path.exists():

            self.last_error = (
                f"Missing PPS assert path: {self.assert_path}"
            )

            return {
                "pps_present": False,
                "pps_valid": False,
                "pps_locked": False,
                "pps_online": False,
                "state": "LOST",
                "last_error": self.last_error,
            }

        try:

            raw_assert = (
                self.assert_path
                .read_text()
                .strip()
            )

            match = PPS_ASSERT_PATTERN.search(
                raw_assert
            )

            if not match:

                self.last_error = (
                    f"Could not parse PPS assert: {raw_assert}"
                )

                return {
                    "pps_present": True,
                    "pps_valid": False,
                    "pps_locked": False,
                    "pps_online": False,
                    "state": "LOST",
                    "raw_assert": raw_assert,
                    "last_error": self.last_error,
                }

            sec = int(
                match.group("sec")
            )

            nsec = int(
                match.group("nsec")
            )

            seq = int(
                match.group("seq")
            )

            kernel_time = (
                sec
                + (
                    nsec
                    / 1_000_000_000.0
                )
            )

            now_wall = time.time()
            now_monotonic = time.monotonic()

            pps_age_sec = (
                now_wall
                - kernel_time
            )

            seq_changed = (
                self.last_seq is None
                or seq != self.last_seq
            )

            if seq_changed:

                self.last_seq = seq
                self.last_kernel_time = kernel_time
                self.last_seen_monotonic = now_monotonic

            # The assert timestamp should be recent if PPS is alive.
            # A 2.5 s threshold gives the 1 Hz PPS signal room for scheduler delay
            # without reporting stale edges as valid forever.
            pps_valid = (
                pps_age_sec >= -0.5
                and pps_age_sec <= self.max_age_sec
            )

            self.last_error = None

            return {
                "pps_present": True,
                "pps_valid": pps_valid,
                "pps_locked": pps_valid,
                "pps_online": pps_valid,
                "state": "LOCKED" if pps_valid else "LOST",
                "pps_source": "kernel_pps",
                "pps_device": self.pps_device,
                "pps_name": self.get_pps_name(),
                "pps_seq": seq,
                "pps_seq_changed": seq_changed,
                "last_pps_kernel_time": kernel_time,
                "last_pps_kernel_time_sec": sec,
                "last_pps_kernel_time_nsec": nsec,
                "pps_age_sec": pps_age_sec,
                "raw_assert": raw_assert,
                "last_error": None,
            }

        except Exception as error:

            self.last_error = repr(
                error
            )

            return {
                "pps_present": True,
                "pps_valid": False,
                "pps_locked": False,
                "pps_online": False,
                "state": "LOST",
                "pps_source": "kernel_pps",
                "pps_device": self.pps_device,
                "last_error": self.last_error,
            }

    def get_pps_name(
        self
    ) -> Optional[str]:

        try:

            if self.name_path.exists():

                return (
                    self.name_path
                    .read_text()
                    .strip()
                )

        except Exception:

            return None

        return None

    # --------------------------------------------------
    # Snapshot
    # --------------------------------------------------

    def get_snapshot(
        self
    ) -> Dict[str, Any]:

        pps_data = self.read_kernel_pps()

        event_utc = int(
            time.time()
        )

        snapshot = {
            "event_id": f"PPS_{event_utc}",
            "event_utc": event_utc,
            **pps_data,
        }

        return snapshot


if __name__ == "__main__":

    manager = PPSManager(
        debug=True
    )

    for _ in range(5):

        print(
            manager.get_snapshot()
        )

        time.sleep(
            1
        )