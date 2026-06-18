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
    - Load RTK configuration.
    - Resolve node identity from config or hostname.
    - Coordinate GPS, PPS, RTK base, and RTK rover managers.
    - Track GPS lock state.
    - Track PPS lock state.
    - Track RTK fix state from the GPS snapshot.
    - Publish canonical node RTK events through RTKEventServices.
    - Publish GPS coordinates at a configured interval.
    - In BASE mode: configure Survey-In and broadcast RTCM.
    - In ROVER mode: receive RTCM and write corrections to the F9P.

Does NOT:
    - Publish legacy GPS_LOCK, GPS_LOST, PPS_LOCK, or PPS_LOST events.
    - Subscribe directly to the event bus.
    - Publish directly to the event bus.
    - Own node registration.
"""

from __future__ import annotations

import json
import re
import socket
import time

from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import Optional

from RTK.GPS_manager import GPSManager
from RTK.PPS_manager import PPSManager
from RTK.RTK_base_manager import RTKBaseManager
from RTK.RTK_event_services import RTKEventServices
from RTK.RTK_rover_manager import RTKRoverManager


class RTKDispatcher:

    def __init__(
        self,
        event_bus,
        config_path: str = "RTK/RTK_config.json",
        debug: bool = True,
    ):
        self.debug = debug
        self.config_path = config_path
        self.config = self.load_config()

        self.node_id = self.resolve_node_id(
            self.config.get(
                "node_id",
                "auto",
            )
        )

        self.node_name = self.resolve_node_name(
            self.config.get(
                "node_name",
                "auto",
            )
        )

        self.loop_delay_sec = self.config.get(
            "loop_delay_sec",
            1.0,
        )

        self.state_publish_interval_sec = self.config.get(
            "state_publish_interval_sec",
            30,
        )

        gps_config = self.config.get(
            "gps",
            {},
        )

        pps_config = self.config.get(
            "pps",
            {},
        )

        self.coord_publish_interval_sec = gps_config.get(
            "coord_publish_interval_sec",
            5,
        )

        self.gps_manager = GPSManager(
            port=gps_config.get(
                "port",
                "/dev/ttyACM0",
            ),
            baudrate=gps_config.get(
                "baudrate",
                38400,
            ),
            debug=debug,
        )

        self.fp9_driver = self.gps_manager.driver

        self.pps_manager = PPSManager(
            gpio_bcm=pps_config.get(
                "gpio_bcm",
                18,
            ),
            pps_timeout_sec=pps_config.get(
                "pps_timeout_sec",
                2.0,
            ),
            active_edge=pps_config.get(
                "active_edge",
                "rising",
            ),
            pull=pps_config.get(
                "pull",
                "down",
            ),
            debug=debug,
        )

        self.rtk_config = self.config.get(
            "rtk",
            {},
        )

        self.rtk_mode = self.resolve_rtk_mode(
            self.rtk_config.get(
                "mode",
                "disabled",
            )
        )

        self.base_manager: Optional[RTKBaseManager] = None
        self.rover_manager: Optional[RTKRoverManager] = None

        self.configure_rtk_managers()

        self.event_services = RTKEventServices(
            event_bus=event_bus,
            debug=debug,
        )

        # None means no state has been published yet. The first snapshot
        # therefore publishes startup state.
        self.gps_locked: Optional[bool] = None
        self.pps_locked: Optional[bool] = None
        self.rtk_online: Optional[bool] = None
        self.rtk_fixed: Optional[bool] = None
        self.rtk_float: Optional[bool] = None

        self.last_coord_publish = 0.0
        self.last_state_publish = 0.0

        self.running = False

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(
        self,
        message,
    ) -> None:

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
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(
                file
            )

    def resolve_node_id(
        self,
        configured_node_id: str,
    ) -> str:

        value = str(
            configured_node_id
        ).strip()

        if value and value.lower() not in {
            "auto",
            "hostname",
        }:
            return value

        hostname = socket.gethostname()

        match = re.search(
            r"(?:ep[-_])?node[-_](\d+)",
            hostname,
            re.IGNORECASE,
        )

        if match:
            return f"node_{int(match.group(1)):02d}"

        return hostname.replace(
            "-",
            "_",
        )

    def resolve_node_name(
        self,
        configured_node_name: str,
    ) -> str:

        value = str(
            configured_node_name
        ).strip()

        if value and value.lower() not in {
            "auto",
            "hostname",
        }:
            return value

        suffix = self.node_id.replace(
            "node_",
            "",
        )

        return f"EnviroPulse Node {suffix}"

    def resolve_rtk_mode(
        self,
        configured_mode: str,
    ) -> str:

        mode = str(
            configured_mode
        ).strip().lower()

        if mode == "auto":
            base_node_ids = self.rtk_config.get(
                "base_node_ids",
                [],
            )

            if self.node_id in base_node_ids:
                return "base"

            return "rover"

        if mode in {
            "base",
            "rover",
            "disabled",
            "off",
            "none",
        }:
            if mode in {
                "off",
                "none",
            }:
                return "disabled"

            return mode

        return "disabled"

    def configure_rtk_managers(
        self
    ) -> None:

        common = {
            "udp_port": self.rtk_config.get(
                "udp_port",
                5010,
            ),
            "report_interval_sec": self.rtk_config.get(
                "report_interval_sec",
                5,
            ),
        }

        if self.rtk_mode == "base":
            base_config = dict(
                self.rtk_config.get(
                    "base",
                    {},
                )
            )
            base_config.update(
                common
            )

            self.base_manager = RTKBaseManager(
                driver=self.fp9_driver,
                config=base_config,
                debug=self.debug,
            )

            self.log(
                "RTK mode resolved to BASE"
            )

        elif self.rtk_mode == "rover":
            rover_config = dict(
                self.rtk_config.get(
                    "rover",
                    {},
                )
            )
            rover_config.update(
                common
            )

            self.rover_manager = RTKRoverManager(
                driver=self.fp9_driver,
                config=rover_config,
                debug=self.debug,
            )

            self.log(
                "RTK mode resolved to ROVER"
            )

        else:
            self.log(
                "RTK correction transport disabled"
            )

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def start(
        self
    ):

        self.log(
            f"Starting RTK subsystem as {self.node_id} ({self.rtk_mode})"
        )

        self.running = True

        if self.base_manager:
            self.base_manager.start()

        if self.rover_manager:
            self.rover_manager.start()

        self.run()

    def stop(
        self
    ):

        self.log(
            "Stopping RTK subsystem"
        )

        self.running = False

        try:
            if self.base_manager:
                self.base_manager.close()

            if self.rover_manager:
                self.rover_manager.close()

            if self.pps_manager:
                self.pps_manager.close()

            if self.fp9_driver:
                self.fp9_driver.disconnect()

        except Exception as error:
            self.log(
                f"Stop cleanup error: {error}"
            )

    def run(
        self
    ):

        while self.running:

            try:
                # Rovers should push any received RTCM into the F9P before
                # the GPS snapshot is read.
                self.process_rover_corrections()

                gps_snapshot = self.get_gps_snapshot()
                pps_snapshot = self.get_pps_snapshot()

                # Base packets are extracted while the GPS snapshot reads the
                # shared serial stream. Send them after the read.
                self.process_base_corrections()

                force_state_publish = self.should_publish_state_heartbeat()

                self.check_gps_state(
                    gps_snapshot=gps_snapshot,
                    force_publish=force_state_publish,
                )

                self.check_pps_state(
                    pps_snapshot=pps_snapshot,
                    force_publish=force_state_publish,
                )

                self.check_rtk_state(
                    gps_snapshot=gps_snapshot,
                    force_publish=force_state_publish,
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
    # RTK Correction Transport
    # --------------------------------------------------

    def process_rover_corrections(
        self
    ) -> None:

        if self.rover_manager:
            self.rover_manager.process()

    def process_base_corrections(
        self
    ) -> None:

        if self.base_manager:
            self.base_manager.process()

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
                dict,
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
                dict,
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
        force_publish: bool = False,
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
            gps_locked=current_state,
        )

        self.event_services.publish_gps_state(
            event
        )

        self.log(
            f"Published GPS_STATE: {event['payload']['state']}"
        )

    def extract_gps_locked(
        self,
        gps_snapshot: Dict[str, Any],
    ) -> bool:

        return bool(
            gps_snapshot.get(
                "fix_valid",
                gps_snapshot.get(
                    "gps_locked",
                    gps_snapshot.get(
                        "gps_online",
                        False,
                    ),
                ),
            )
        )

    def build_gps_state_event(
        self,
        gps_snapshot: Dict[str, Any],
        gps_locked: bool,
    ) -> Dict[str, Any]:

        payload = {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "subsystem": "rtk",
            "gps_online": gps_locked,
            "gps_locked": gps_locked,
            "fix_valid": gps_locked,
            "fix_quality": gps_snapshot.get(
                "fix_quality",
                0,
            ),
            "fix_label": gps_snapshot.get(
                "fix_label",
                "UNKNOWN",
            ),
            "state": "LOCKED" if gps_locked else "LOST",
            "snapshot": gps_snapshot,
        }

        return self.build_event(
            event_type="GPS_STATE",
            payload=payload,
        )

    # --------------------------------------------------
    # PPS State
    # --------------------------------------------------

    def check_pps_state(
        self,
        pps_snapshot: Dict[str, Any],
        force_publish: bool = False,
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
            pps_locked=current_state,
        )

        self.event_services.publish_pps_state(
            event
        )

        self.log(
            f"Published PPS_STATE: {event['payload']['state']}"
        )

    def extract_pps_locked(
        self,
        pps_snapshot: Dict[str, Any],
    ) -> bool:

        return bool(
            pps_snapshot.get(
                "pps_valid",
                pps_snapshot.get(
                    "pps_locked",
                    pps_snapshot.get(
                        "pps_online",
                        False,
                    ),
                ),
            )
        )

    def build_pps_state_event(
        self,
        pps_snapshot: Dict[str, Any],
        pps_locked: bool,
    ) -> Dict[str, Any]:

        payload = {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "subsystem": "rtk",
            "pps_online": pps_locked,
            "pps_locked": pps_locked,
            "pps_valid": pps_locked,
            "state": "LOCKED" if pps_locked else "LOST",
            "snapshot": pps_snapshot,
        }

        return self.build_event(
            event_type="PPS_STATE",
            payload=payload,
        )

    # --------------------------------------------------
    # RTK State
    # --------------------------------------------------

    def check_rtk_state(
        self,
        gps_snapshot: Dict[str, Any],
        force_publish: bool = False,
    ):

        current_online = self.extract_rtk_online(
            gps_snapshot
        )
        current_fixed = self.extract_rtk_fixed(
            gps_snapshot
        )
        current_float = self.extract_rtk_float(
            gps_snapshot
        )

        state_changed = (
            self.rtk_online is None
            or current_online != self.rtk_online
            or current_fixed != self.rtk_fixed
            or current_float != self.rtk_float
        )

        if not state_changed and not force_publish:
            return

        self.rtk_online = current_online
        self.rtk_fixed = current_fixed
        self.rtk_float = current_float

        event = self.build_rtk_state_event(
            gps_snapshot=gps_snapshot,
            rtk_online=current_online,
            rtk_fixed=current_fixed,
            rtk_float=current_float,
        )

        self.event_services.publish_rtk_state(
            event
        )

        self.log(
            f"Published RTK_STATE: {event['payload']['state']} {event['payload']['rtk_status']}"
        )

    def extract_rtk_online(
        self,
        gps_snapshot: Dict[str, Any],
    ) -> bool:

        if "rtk_online" in gps_snapshot:
            return bool(
                gps_snapshot.get(
                    "rtk_online"
                )
            )

        fix_quality = self.extract_fix_quality(
            gps_snapshot
        )

        if fix_quality is not None:
            return fix_quality in {
                4,
                5,
            }

        status = self.get_rtk_status_string(
            gps_snapshot
        )

        return status in {
            "RTK_FIXED",
            "RTK_FLOAT",
            "FIXED",
            "FLOAT",
        }

    def extract_rtk_fixed(
        self,
        gps_snapshot: Dict[str, Any],
    ) -> bool:

        if "rtk_fixed" in gps_snapshot:
            return bool(
                gps_snapshot.get(
                    "rtk_fixed"
                )
            )

        fix_quality = self.extract_fix_quality(
            gps_snapshot
        )

        return fix_quality == 4

    def extract_rtk_float(
        self,
        gps_snapshot: Dict[str, Any],
    ) -> bool:

        if "rtk_float" in gps_snapshot:
            return bool(
                gps_snapshot.get(
                    "rtk_float"
                )
            )

        fix_quality = self.extract_fix_quality(
            gps_snapshot
        )

        return fix_quality == 5

    def extract_fix_quality(
        self,
        gps_snapshot: Dict[str, Any],
    ) -> Optional[int]:

        value = gps_snapshot.get(
            "fix_quality"
        )

        if value is None:
            return None

        try:
            return int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

    def get_rtk_status_string(
        self,
        gps_snapshot: Dict[str, Any],
    ) -> str:

        status = self.get_first_available(
            gps_snapshot,
            [
                "rtk_status",
                "rtk_state",
                "fix_label",
                "carrier_solution",
                "carrier_solution_status",
            ],
            default="UNKNOWN",
        )

        return str(
            status
        ).strip().upper().replace(
            " ",
            "_",
        )

    def build_rtk_state_event(
        self,
        gps_snapshot: Dict[str, Any],
        rtk_online: bool,
        rtk_fixed: bool,
        rtk_float: bool,
    ) -> Dict[str, Any]:

        status = self.get_first_available(
            gps_snapshot,
            [
                "rtk_status",
                "rtk_state",
                "fix_label",
                "fix_quality",
            ],
            default="UNKNOWN",
        )

        if rtk_fixed:
            state = "ONLINE"
            fix_type = "FIXED"

        elif rtk_float:
            state = "ONLINE"
            fix_type = "FLOAT"

        else:
            state = "OFFLINE"
            fix_type = "NONE"

        payload = {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "subsystem": "rtk",
            "rtk_online": rtk_online,
            "rtk_fixed": rtk_fixed,
            "rtk_float": rtk_float,
            "rtk_fix_type": fix_type,
            "rtk_status": status,
            "fix_quality": gps_snapshot.get(
                "fix_quality",
                0,
            ),
            "state": state,
            "mode": self.rtk_mode,
            "snapshot": gps_snapshot,
        }

        return self.build_event(
            event_type="RTK_STATE",
            payload=payload,
        )

    # --------------------------------------------------
    # Coordinate Publishing
    # --------------------------------------------------

    def publish_coordinates(
        self,
        gps_snapshot: Dict[str, Any],
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
                "latitude",
            ],
        )

        longitude = self.get_first_available(
            gps_snapshot,
            [
                "lon",
                "lng",
                "longitude",
            ],
        )

        if latitude is None or longitude is None:
            self.log(
                "GPS_COORD skipped because latitude or longitude is missing"
            )
            return

        event = self.build_gps_coord_event(
            gps_snapshot=gps_snapshot,
            latitude=latitude,
            longitude=longitude,
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
        longitude,
    ) -> Dict[str, Any]:

        altitude_m = self.get_first_available(
            gps_snapshot,
            [
                "altitude_m",
                "alt_m",
                "altitude",
            ],
        )

        gps_coord = {
            "lat": latitude,
            "lon": longitude,
            "alt": altitude_m,
            "altitude_m": altitude_m,
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
            "fix_valid": self.extract_gps_locked(
                gps_snapshot
            ),
            "fix_quality": gps_snapshot.get(
                "fix_quality",
                0,
            ),
            "rtk_online": self.extract_rtk_online(
                gps_snapshot
            ),
            "rtk_fixed": self.extract_rtk_fixed(
                gps_snapshot
            ),
            "rtk_float": self.extract_rtk_float(
                gps_snapshot
            ),
            "snapshot": gps_snapshot,
        }

        return self.build_event(
            event_type="GPS_COORD",
            payload=payload,
        )

    # --------------------------------------------------
    # Event Helpers
    # --------------------------------------------------

    def build_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:

        return {
            "event_type": event_type,
            "source": self.node_id,
            "target": "server",
            "timestamp": self.get_utc_timestamp(),
            "payload": payload,
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
        default=None,
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
                "Z",
            )
        )


if __name__ == "__main__":

    class MockBus:

        def publish(
            self,
            event,
        ):
            print(
                f"[BUS] {event}"
            )

    dispatcher = RTKDispatcher(
        event_bus=MockBus(),
        debug=True,
    )

    try:
        dispatcher.start()

    except KeyboardInterrupt:
        dispatcher.stop()
