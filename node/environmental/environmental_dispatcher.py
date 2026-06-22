#!/usr/bin/env python3
# ============================================================
# environmental_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Environmental
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own the environmental subsystem workflow.
#
# Expected config source:
#   environmental_config.json
#   node_config.json
#
# Expected config section:
#   environmental_config root
#   node_config["node_id"], node_config["node_name"]
#
# Does:
#   - Load environmental subsystem configuration.
#   - Resolve node identity from provided values or node_config.json.
#   - Start and stop environmental managers.
#   - Poll environmental sensor snapshots.
#   - Track environmental state.
#   - Publish ENVIRO_STATE.
#   - Publish ENVIRO_EVENT when readings are available.
#
# Does NOT:
#   - Own sensor driver implementation.
#   - Publish directly to the event bus.
#   - Subscribe directly to the event bus.
#   - Own platform registry state.
#   - Own node registration.
#
# Owner:
#   node_main.py
#
# ============================================================

from __future__ import annotations

from environmental.driver_manager import DriverManager
from environmental.environmental_event_services import EnvironmentalEventServices

import json
import socket
import time

from pathlib import Path
from typing import Any
from typing import Dict
from typing import Optional


class EnvironmentalDispatcher:

    def __init__(
        self,
        event_bus,
        node_id: Optional[str] = None,
        node_name: Optional[str] = None,
        config_path: Optional[str] = None,
        node_config_path: Optional[str] = None,
        debug: Optional[bool] = None,
    ):

        self.paths = self.resolve_paths(
            config_path=config_path,
            node_config_path=node_config_path,
        )

        self.config = self.load_json_or_default(
            path=self.paths["environmental_config"],
            default_value=self.default_config(),
        )

        node_identity = self.resolve_node_identity(
            node_id=node_id,
            node_name=node_name,
        )

        self.node_id = node_identity["node_id"]
        self.node_name = node_identity["node_name"]

        if debug is None:
            self.debug = bool(
                self.config.get(
                    "debug",
                    True,
                )
            )
        else:
            self.debug = bool(
                debug
            )

        self.enabled = bool(
            self.config.get(
                "enabled",
                True,
            )
        )

        self.enviro_interval_sec = float(
            self.config.get(
                "enviro_interval_sec",
                300,
            )
        )

        self.state_heartbeat_sec = float(
            self.config.get(
                "state_heartbeat_sec",
                300,
            )
        )

        self.loop_delay_sec = float(
            self.config.get(
                "loop_delay_sec",
                1.0,
            )
        )

        self.required_sensors = list(
            self.config.get(
                "required_sensors",
                [],
            )
        )

        self.driver_manager = DriverManager(
            config=self.config,
            debug=self.debug,
        )

        self.event_services = EnvironmentalEventServices(
            event_bus=event_bus,
            node_id=self.node_id,
            debug=self.debug,
        )

        self.last_enviro_publish = 0.0
        self.last_state_publish = 0.0

        self.sensor_states: Dict[str, Optional[bool]] = {}
        self.enviro_online: Optional[bool] = None

        self.running = False

    # ============================================================
    # CONFIG
    # ============================================================

    def resolve_paths(
        self,
        config_path: Optional[str],
        node_config_path: Optional[str],
    ) -> Dict[str, Path]:

        environmental_dir = Path(__file__).resolve().parent
        node_dir = environmental_dir.parent

        if config_path:
            environmental_config = Path(
                config_path
            )
        else:
            environmental_config = (
                environmental_dir / "environmental_config.json"
            )

        if node_config_path:
            node_config = Path(
                node_config_path
            )
        else:
            node_config = node_dir / "node_config.json"

        return {
            "environmental_config": environmental_config,
            "node_config": node_config,
        }

    def default_config(
        self,
    ) -> Dict[str, Any]:

        return {
            "enabled": True,
            "sample_hz": 1.0,
            "enviro_interval_sec": 300,
            "state_heartbeat_sec": 300,
            "loop_delay_sec": 1.0,
            "sea_level_pressure_hpa": 1013.25,
            "required_sensors": [
                "sht45",
                "dps310",
            ],
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
            "debug": True,
        }

    def load_json_or_default(
        self,
        path: Path,
        default_value: Dict[str, Any],
    ) -> Dict[str, Any]:

        try:
            if not path.exists():
                return dict(
                    default_value
                )

            with path.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(
                    file
                )

            if isinstance(
                data,
                dict,
            ):
                return data

            return dict(
                default_value
            )

        except Exception:
            return dict(
                default_value
            )

    # ============================================================
    # NODE IDENTITY
    # ============================================================

    def resolve_node_identity(
        self,
        node_id: Optional[str],
        node_name: Optional[str],
    ) -> Dict[str, str]:

        config_identity = self.load_json_or_default(
            path=self.paths["node_config"],
            default_value={},
        )

        resolved_node_id = (
            node_id
            or config_identity.get(
                "node_id"
            )
            or self.hostname_node_id()
        )

        resolved_node_name = (
            node_name
            or config_identity.get(
                "node_name"
            )
            or self.infer_node_name(
                resolved_node_id
            )
        )

        return {
            "node_id": str(
                resolved_node_id
            ),
            "node_name": str(
                resolved_node_name
            ),
        }

    def hostname_node_id(
        self,
    ) -> str:

        hostname = socket.gethostname()
        return hostname.replace(
            "-",
            "_",
        )

    def infer_node_name(
        self,
        node_id: str,
    ) -> str:

        return node_id.replace(
            "_",
            " "
        ).title()

    # ============================================================
    # DEBUG
    # ============================================================

    def log(
        self,
        message: str,
    ) -> None:

        if self.debug:
            print(
                f"[EnvironmentalDispatcher] {message}"
            )

    # ============================================================
    # LIFECYCLE
    # ============================================================

    def start(
        self,
    ) -> None:

        self.log(
            f"Starting environmental subsystem as {self.node_id}"
        )

        if self.enabled:
            self.driver_manager.start()
        else:
            self.log(
                "Environmental subsystem disabled by config"
            )

        self.running = True
        self.run()

    def stop(
        self,
    ) -> None:

        self.log(
            "Stopping environmental subsystem"
        )

        self.running = False
        self.driver_manager.stop()

    # ============================================================
    # STATE LOGIC
    # ============================================================

    def is_sensor_online(
        self,
        sensor_snapshot: Optional[Dict[str, Any]],
    ) -> bool:

        if not isinstance(
            sensor_snapshot,
            dict,
        ):
            return False

        return bool(
            sensor_snapshot.get(
                "online",
                False,
            )
        )

    def build_sensor_state(
        self,
        sensor_snapshot: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:

        if not isinstance(
            sensor_snapshot,
            dict,
        ):
            return {
                "online": False,
                "started": False,
                "last_error": "missing_snapshot",
                "sample_count": 0,
            }

        return {
            "online": self.is_sensor_online(
                sensor_snapshot
            ),
            "started": bool(
                sensor_snapshot.get(
                    "started",
                    False,
                )
            ),
            "last_error": sensor_snapshot.get(
                "last_error"
            ),
            "sample_count": sensor_snapshot.get(
                "sample_count",
                0,
            ),
        }

    def build_sensor_states(
        self,
        snapshot: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:

        sensor_states: Dict[str, Dict[str, Any]] = {}

        for sensor_name, sensor_snapshot in snapshot.items():
            if sensor_name in {
                "timestamp",
                "enabled",
            }:
                continue

            sensor_states[sensor_name] = self.build_sensor_state(
                sensor_snapshot
            )

        return sensor_states

    def state_label(
        self,
        sensor_states: Dict[str, Dict[str, Any]],
    ) -> str:

        if not self.enabled:
            return "DISABLED"

        if not self.required_sensors:
            return "UNCONFIGURED"

        online_count = sum(
            1
            for sensor_name in self.required_sensors
            if sensor_states.get(
                sensor_name,
                {},
            ).get(
                "online",
                False,
            )
        )

        if online_count == len(
            self.required_sensors
        ):
            return "ONLINE"

        if online_count == 0:
            return "OFFLINE"

        return "DEGRADED"

    def is_enviro_online(
        self,
        sensor_states: Dict[str, Dict[str, Any]],
    ) -> bool:

        if not self.enabled:
            return False

        if not self.required_sensors:
            return False

        return all(
            sensor_states.get(
                sensor_name,
                {},
            ).get(
                "online",
                False,
            )
            for sensor_name in self.required_sensors
        )

    def state_changed(
        self,
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool,
    ) -> bool:

        if self.enviro_online is None:
            return True

        if self.enviro_online != enviro_online:
            return True

        for sensor_name, sensor_state in sensor_states.items():
            previous_state = self.sensor_states.get(
                sensor_name
            )

            current_online = sensor_state.get(
                "online"
            )

            if previous_state is None:
                return True

            if previous_state != current_online:
                return True

        return False

    def store_state(
        self,
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool,
    ) -> None:

        for sensor_name, sensor_state in sensor_states.items():
            self.sensor_states[sensor_name] = sensor_state.get(
                "online"
            )

        self.enviro_online = enviro_online

    def state_heartbeat_due(
        self,
        now: float,
    ) -> bool:

        return (
            now - self.last_state_publish
            >= self.state_heartbeat_sec
        )

    # ============================================================
    # READING HELPERS
    # ============================================================

    def has_reportable_enviro_reading(
        self,
        snapshot: Dict[str, Any],
    ) -> bool:

        for sensor_name, sensor_snapshot in snapshot.items():
            if sensor_name in {
                "timestamp",
                "enabled",
            }:
                continue

            if not isinstance(
                sensor_snapshot,
                dict,
            ):
                continue

            if sensor_snapshot.get(
                "sample_count",
                0,
            ) <= 0:
                continue

            for field_name in (
                "temperature_c",
                "humidity_rh",
                "pressure_hpa",
                "altitude_m",
            ):
                if sensor_snapshot.get(
                    field_name
                ) is not None:
                    return True

        return False

    def first_reading(
        self,
        snapshot: Dict[str, Any],
        sensor_order,
        field_name: str,
    ):

        for sensor_name in sensor_order:
            sensor_snapshot = snapshot.get(
                sensor_name
            )

            if not isinstance(
                sensor_snapshot,
                dict,
            ):
                continue

            value = sensor_snapshot.get(
                field_name
            )

            if value is not None:
                return value

        return None

    # ============================================================
    # PAYLOAD BUILDERS
    # ============================================================

    def build_state_payload(
        self,
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool,
    ) -> Dict[str, Any]:

        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "subsystem": "environmental",
            "state": self.state_label(
                sensor_states
            ),
            "online": enviro_online,
            "enabled": self.enabled,
            "enviro_online": enviro_online,
            "required_sensors": list(
                self.required_sensors
            ),
            "sensors": sensor_states,
        }

    def build_enviro_payload(
        self,
        snapshot: Dict[str, Any],
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool,
    ) -> Dict[str, Any]:

        temperature_c = self.first_reading(
            snapshot,
            [
                "sht45",
                "dps310",
                "bmp390",
            ],
            "temperature_c",
        )

        humidity_rh = self.first_reading(
            snapshot,
            [
                "sht45",
            ],
            "humidity_rh",
        )

        pressure_hpa = self.first_reading(
            snapshot,
            [
                "dps310",
                "bmp390",
            ],
            "pressure_hpa",
        )

        altitude_m = self.first_reading(
            snapshot,
            [
                "dps310",
                "bmp390",
            ],
            "altitude_m",
        )

        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "subsystem": "environmental",
            "online": enviro_online,
            "enabled": self.enabled,
            "state": self.state_label(
                sensor_states
            ),
            "temperature_c": temperature_c,
            "humidity_rh": humidity_rh,
            "humidity_percent": humidity_rh,
            "pressure_hpa": pressure_hpa,
            "altitude_m": altitude_m,
            "sensors": sensor_states,
            "snapshot": snapshot,
        }

    # ============================================================
    # PUBLISHERS
    # ============================================================

    def publish_enviro_state(
        self,
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool,
    ) -> None:

        self.event_services.publish_enviro_state(
            self.build_state_payload(
                sensor_states=sensor_states,
                enviro_online=enviro_online,
            )
        )

        self.last_state_publish = time.time()

    def publish_enviro_event(
        self,
        snapshot: Dict[str, Any],
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool,
    ) -> None:

        self.event_services.publish_enviro_event(
            self.build_enviro_payload(
                snapshot=snapshot,
                sensor_states=sensor_states,
                enviro_online=enviro_online,
            )
        )

        self.last_enviro_publish = time.time()

    # ============================================================
    # MAIN LOOP
    # ============================================================

    def run(
        self,
    ) -> None:

        while self.running:
            try:
                snapshot = self.driver_manager.get_snapshot()
                sensor_states = self.build_sensor_states(
                    snapshot
                )
                enviro_online = self.is_enviro_online(
                    sensor_states
                )

                now = time.time()

                state_changed = self.state_changed(
                    sensor_states=sensor_states,
                    enviro_online=enviro_online,
                )

                if (
                    state_changed
                    or self.state_heartbeat_due(
                        now
                    )
                ):
                    self.publish_enviro_state(
                        sensor_states=sensor_states,
                        enviro_online=enviro_online,
                    )

                enviro_due = (
                    now - self.last_enviro_publish
                    >= self.enviro_interval_sec
                )

                has_reportable_reading = (
                    self.has_reportable_enviro_reading(
                        snapshot=snapshot
                    )
                )

                if (
                    self.enabled
                    and has_reportable_reading
                    and (
                        enviro_due
                        or state_changed
                    )
                ):
                    self.publish_enviro_event(
                        snapshot=snapshot,
                        sensor_states=sensor_states,
                        enviro_online=enviro_online,
                    )

                self.store_state(
                    sensor_states=sensor_states,
                    enviro_online=enviro_online,
                )

            except Exception as error:
                self.log(
                    f"Loop error: {error}"
                )

            time.sleep(
                self.loop_delay_sec
            )


if __name__ == "__main__":

    class MockBus:

        def publish(
            self,
            event,
        ):
            print()
            print("[BUS]")
            print(event)

    dispatcher = EnvironmentalDispatcher(
        event_bus=MockBus(),
        node_id="node_test",
        node_name="EnviroPulse Test Node",
        debug=True,
    )

    try:
        dispatcher.start()

    except KeyboardInterrupt:
        dispatcher.stop()