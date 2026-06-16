"""
RTK_dispatcher.py

EnviroPulse V2.0

Subsystem:
    RTK

Role:
    Dispatcher

Purpose:
    Own the RTK subsystem workflow.

Publishes:
    - RTK_STATE
    - GPS_STATE
    - PPS_STATE
    - GPS_COORD

Subscribes:
    - None

Does:
    - Load RTK configuration
    - Coordinate GPS and PPS managers
    - Track GPS lock state
    - Track PPS lock state
    - Track RTK fix state when available from the GPS snapshot
    - Publish canonical node RTK events through RTKEventServices
    - Publish GPS coordinates at a configured interval

Does NOT:
    - Publish legacy GPS_LOCK, GPS_LOST, PPS_LOCK, or PPS_LOST events
    - Subscribe directly to the event bus
    - Publish directly to the event bus
    - Own UART, UBX parsing, or hardware details
    - Own node registration
"""

from __future__ import annotations

import json
import time

from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import Optional

from RTK.GPS_manager import GPSManager
from RTK.PPS_manager import PPSManager
from RTK.RTK_event_services import RTKEventServices


class RTKDispatcher:

    def __init__(
        self,
        event_bus,
        config_path: str = "RTK/RTK_config.json",
        debug: bool = True
    ):

        self.debug = debug
        self.config_path = config_path
        self.config = self.load_config()
        self.node_id = self.config.get("node_id", "node_01")
        self.node_name = self.config.get("node_name", self.node_id)
        self.loop_delay_sec = self.config.get(
            "loop_delay_sec",
            1.0
        )

        self.state_publish_interval_sec = self.config.get(
            "state_publish_interval_sec",
            30
        )

        self.coord_publish_interval_sec = (
            self.config
            .get("gps", {})
            .get("coord_publish_interval_sec", 5)
        )

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

        # ----------------------------------------------------
        # State tracking.
        #
        # None means no state has been published yet. The first
        # snapshot will therefore publish startup state.
        # ----------------------------------------------------

        self.gps_locked: Optional[bool] = None
        self.pps_locked: Optional[bool] = None
        self.rtk_online: Optional[bool] = None

        self.last_coord_publish = 0.0
        self.last_state_publish = 0.0

        self.running = False

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(
        self,
        message
    ):

        if self.debug:

            print(
                f"[RTKDispatcher] {message}"
            )

    # --------------------------------------------------
    # Config
    # --------------------------------------------------

    def load_config(
        self
    ):

        with open(
            self.config_path,
            "r"
        ) as file:

            return json.load(file)

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def start(
        self
    ):

        self.log(
            "Starting RTK subsystem"
        )

        self.running = True

        self.run()

    def stop(
        self
    ):

        self.log(
            "Stopping RTK subsystem"
        )

        self.running = False

    def run(
        self
    ):

        while self.running:

            try:

                gps_snapshot = self.get_gps_snapshot()
                pps_snapshot = self.get_pps_snapshot()

                force_state_publish = self.should_publish_state_heartbeat()

                self.check_gps_state(
                    gps_snapshot=gps_snapshot,
                    force_publish=force_state_publish
                )

                self.check_pps_state(
                    pps_snapshot=pps_snapshot,
                    force_publish=force_state_publish
                )

                self.check_rtk_state(
                    gps_snapshot=gps_snapshot,
                    force_publish=force_state_publish
                )

                if force_state_publish:

                    self.last_state_publish = time.time()

                self.publish_coordinates(
                    gps_snapshot=gps_snapshot
                )

            except Exception as error:

                self.log(
                    f"Loop error: {error}"
                )

            time.sleep(
                self.loop_delay_sec
            )

    # --------------------------------------------------
    # Snapshot Access
    # --------------------------------------------------

    def get_gps_snapshot(
        self
    ) -> Dict[str, Any]:

        try:

            snapshot = self.gps_manager.get_snapshot()

            if isinstance(
                snapshot,
                dict
            ):

                return snapshot

        except Exception as error:

            self.log(
                f"GPS snapshot error: {error}"
            )

        return {}

    def get_pps_snapshot(
        self
    ) -> Dict[str, Any]:

        try:

            snapshot = self.pps_manager.get_snapshot()

            if isinstance(
                snapshot,
                dict
            ):

                return snapshot

        except Exception as error:

            self.log(
                f"PPS snapshot error: {error}"
            )

        return {}

    # --------------------------------------------------
    # GPS State
    # --------------------------------------------------

    def check_gps_state(
        self,
        gps_snapshot: Dict[str, Any],
        force_publish: bool = False
    ):

        current_state = self.extract_gps_locked(
            gps_snapshot
        )

        state_changed = (
            self.gps_locked is None
            or current_state != self.gps_locked
        )

        if not state_changed and not force_publish:

            return

        self.gps_locked = current_state

        event = self.build_gps_state_event(
            gps_snapshot=gps_snapshot,
            gps_locked=current_state
        )

        self.event_services.publish_gps_state(
            event
        )

        self.log(
            f"Published GPS_STATE: {event['payload']['state']}"
        )

    def extract_gps_locked(
        self,
        gps_snapshot: Dict[str, Any]
    ) -> bool:

        return bool(
            gps_snapshot.get(
                "fix_valid",
                gps_snapshot.get(
                    "gps_locked",
                    gps_snapshot.get(
                        "gps_online",
                        False
                    )
                )
            )
        )

    def build_gps_state_event(
        self,
        gps_snapshot: Dict[str, Any],
        gps_locked: bool
    ) -> Dict[str, Any]:

        payload = {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "subsystem": "rtk",
            "gps_online": gps_locked,
            "gps_locked": gps_locked,
            "fix_valid": gps_locked,
            "state": "LOCKED" if gps_locked else "LOST",
            "snapshot": gps_snapshot
        }
        
        return self.build_event(
            event_type="GPS_STATE",
            payload=payload
        )

    # --------------------------------------------------
    # PPS State
    # --------------------------------------------------

    def check_pps_state(
        self,
        pps_snapshot: Dict[str, Any],
        force_publish: bool = False
    ):

        current_state = self.extract_pps_locked(
            pps_snapshot
        )

        state_changed = (
            self.pps_locked is None
            or current_state != self.pps_locked
        )

        if not state_changed and not force_publish:

            return

        self.pps_locked = current_state

        event = self.build_pps_state_event(
            pps_snapshot=pps_snapshot,
            pps_locked=current_state
        )

        self.event_services.publish_pps_state(
            event
        )

        self.log(
            f"Published PPS_STATE: {event['payload']['state']}"
        )

    def extract_pps_locked(
        self,
        pps_snapshot: Dict[str, Any]
    ) -> bool:

        return bool(
            pps_snapshot.get(
                "pps_valid",
                pps_snapshot.get(
                    "pps_locked",
                    pps_snapshot.get(
                        "pps_online",
                        False
                    )
                )
            )
        )

    def build_pps_state_event(
        self,
        pps_snapshot: Dict[str, Any],
        pps_locked: bool
    ) -> Dict[str, Any]:

        payload = {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "subsystem": "rtk",
            "pps_online": pps_locked,
            "pps_locked": pps_locked,
            "pps_valid": pps_locked,
            "state": "LOCKED" if pps_locked else "LOST",
            "snapshot": pps_snapshot
        }

        return self.build_event(
            event_type="PPS_STATE",
            payload=payload
        )

    # --------------------------------------------------
    # RTK State
    # --------------------------------------------------

    def check_rtk_state(
        self,
        gps_snapshot: Dict[str, Any],
        force_publish: bool = False
    ):

        current_state = self.extract_rtk_online(
            gps_snapshot
        )

        state_changed = (
            self.rtk_online is None
            or current_state != self.rtk_online
        )

        if not state_changed and not force_publish:

            return

        self.rtk_online = current_state

        event = self.build_rtk_state_event(
            gps_snapshot=gps_snapshot,
            rtk_online=current_state
        )

        self.event_services.publish_rtk_state(
            event
        )

        self.log(
            f"Published RTK_STATE: {event['payload']['state']}"
        )

    def extract_rtk_online(
        self,
        gps_snapshot: Dict[str, Any]
    ) -> bool:

        direct_fields = [
            "rtk_online",
            "rtk_fixed",
            "rtk_fix_valid",
            "rtk_valid"
        ]

        for field in direct_fields:

            if field in gps_snapshot:

                return bool(
                    gps_snapshot.get(field)
                )

        status = self.get_first_available(
            gps_snapshot,
            [
                "rtk_status",
                "rtk_state",
                "carrier_solution",
                "carrier_solution_status",
                "fix_quality"
            ]
        )

        if status is None:

            return False

        if isinstance(
            status,
            str
        ):

            normalized = (
                status
                .strip()
                .upper()
                .replace(" ", "_")
            )

            return normalized in {
                "FIX",
                "FIXED",
                "RTK",
                "RTK_FIX",
                "RTK_FIXED",
                "FLOAT",
                "RTK_FLOAT",
                "DGPS"
            }

        return bool(status)

    def build_rtk_state_event(
        self,
        gps_snapshot: Dict[str, Any],
        rtk_online: bool
    ) -> Dict[str, Any]:

        status = self.get_first_available(
            gps_snapshot,
            [
                "rtk_status",
                "rtk_state",
                "carrier_solution",
                "carrier_solution_status",
                "fix_quality"
            ],
            default="UNKNOWN"
        )

        payload = {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "subsystem": "rtk",
            "rtk_online": rtk_online,
            "rtk_fixed": rtk_online,
            "rtk_status": status,
            "state": "ONLINE" if rtk_online else "OFFLINE",
            "snapshot": gps_snapshot
        }

        return self.build_event(
            event_type="RTK_STATE",
            payload=payload
        )

    # --------------------------------------------------
    # Coordinate Publishing
    # --------------------------------------------------

    def publish_coordinates(
        self,
        gps_snapshot: Dict[str, Any]
    ):

        now = time.time()

        if (
            now - self.last_coord_publish
            < self.coord_publish_interval_sec
        ):

            return

        if not self.extract_gps_locked(
            gps_snapshot
        ):

            return

        latitude = self.get_first_available(
            gps_snapshot,
            [
                "lat",
                "latitude"
            ]
        )

        longitude = self.get_first_available(
            gps_snapshot,
            [
                "lon",
                "lng",
                "longitude"
            ]
        )

        if latitude is None or longitude is None:

            self.log(
                "GPS_COORD skipped because latitude or longitude is missing"
            )

            return

        event = self.build_gps_coord_event(
            gps_snapshot=gps_snapshot,
            latitude=latitude,
            longitude=longitude
        )

        self.event_services.publish_gps_coord(
            event
        )

        self.last_coord_publish = now

        self.log(
            "Published GPS_COORD"
        )

    def build_gps_coord_event(
        self,
        gps_snapshot: Dict[str, Any],
        latitude,
        longitude
    ) -> Dict[str, Any]:

        altitude_m = self.get_first_available(
            gps_snapshot,
            [
                "altitude_m",
                "alt_m",
                "altitude"
            ]
        )

        gps_coord = {
            "lat": latitude,
            "lon": longitude,
            "alt": altitude_m,
            "altitude_m": altitude_m
            }

        payload = {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "subsystem": "rtk",
            "gps_coord": gps_coord,
            "lat": latitude,
            "lon": longitude,
            "latitude": latitude,
            "longitude": longitude,
            "alt": altitude_m,
            "altitude_m": altitude_m,
            "fix_valid": self.extract_gps_locked(gps_snapshot),
            "snapshot": gps_snapshot
        }

        return self.build_event(
            event_type="GPS_COORD",
            payload=payload
        )

    # --------------------------------------------------
    # Event Helpers
    # --------------------------------------------------

    def build_event(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:

        return {
            "event_type": event_type,
            "source": self.node_id,
            "target": "server",
            "timestamp": self.get_utc_timestamp(),
            "payload": payload
        }

    def should_publish_state_heartbeat(
        self
    ) -> bool:

        now = time.time()

        if self.last_state_publish == 0:

            return True

        return (
            now - self.last_state_publish
            >= self.state_publish_interval_sec
        )

    def get_first_available(
        self,
        source: Dict[str, Any],
        keys,
        default=None
    ):

        for key in keys:

            value = source.get(
                key
            )

            if value is not None:

                return value

        return default

    def get_utc_timestamp(
        self
    ) -> str:

        return (
            datetime.now(
                timezone.utc
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z"
            )
        )


if __name__ == "__main__":

    class MockBus:

        def publish(
            self,
            event
        ):

            print(
                f"[BUS] {event}"
            )

    dispatcher = RTKDispatcher(
        event_bus=MockBus(),
        debug=True
    )

    try:

        dispatcher.start()

    except KeyboardInterrupt:

        dispatcher.stop()
