#!/usr/bin/env python3
"""
environmental_dispatcher.py

Environmental Subsystem Dispatcher

Responsibilities:
- Start and stop environmental drivers
- Poll environmental sensor snapshots
- Publish ENVIRO_STATE when readiness changes or heartbeat is due
- Publish ENVIRO_EVENT on the configured environmental cadence
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from environmental.driver_manager import DriverManager
from environmental.environmental_event_services import EnvironmentalEventServices


class EnvironmentalDispatcher:

    def __init__(
        self,
        event_bus,
        node_id: str = "node_01",
        enviro_interval_sec: Optional[int] = None,
        state_heartbeat_sec: int = 300,
        loop_delay_sec: float = 1.0,
        required_sensors: Tuple[str, ...] = ("sht45", "bmp390"),
        weather_interval_sec: Optional[int] = None,
        debug: bool = True
    ):

        self.debug = debug
        self.node_id = node_id

        # Backward-compatible alias for the old WEATHER cadence name.
        if enviro_interval_sec is None:
            enviro_interval_sec = (
                weather_interval_sec
                if weather_interval_sec is not None
                else 300
            )

        self.enviro_interval_sec = enviro_interval_sec
        self.state_heartbeat_sec = state_heartbeat_sec
        self.loop_delay_sec = loop_delay_sec
        self.required_sensors = required_sensors

        self.driver_manager = DriverManager(
            debug=debug
        )

        self.event_services = EnvironmentalEventServices(
            event_bus=event_bus,
            node_id=node_id,
            debug=debug
        )

        self.last_enviro_publish = 0.0
        self.last_state_publish = 0.0

        self.sensor_states = {
            "sht45": None,
            "bmp390": None
        }

        self.enviro_online = None
        self.running = False

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message: str):

        if self.debug:
            print(f"[EnvironmentalDispatcher] {message}")

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def start(self):

        self.log("Starting environmental subsystem")

        self.driver_manager.start()

        self.running = True
        self.run()

    def stop(self):

        self.log("Stopping environmental subsystem")

        self.running = False
        self.driver_manager.stop()

    # --------------------------------------------------
    # State Logic
    # --------------------------------------------------
    
    def _is_online(self, sensor_snapshot: Optional[Dict[str, Any]]) -> bool:

        if not isinstance(sensor_snapshot, dict):
            return False

        if "online" in sensor_snapshot:
            return bool(sensor_snapshot.get("online"))

        if sensor_snapshot.get("last_error"):
            return False

        if sensor_snapshot.get("driver_start_monotonic") is None:
            return False

        return True

    def _sensor_state(
        self,
        sensor_name: str,
        sensor_snapshot: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:

        if not isinstance(sensor_snapshot, dict):
            return {
                "online": False,
                "started": False,
                "last_error": "missing_snapshot",
                "sample_count": 0
            }

        return {
            "online": self._is_online(sensor_snapshot),
            "started": bool(sensor_snapshot.get("started", False)),
            "last_error": sensor_snapshot.get("last_error"),
            "sample_count": sensor_snapshot.get("sample_count", 0)
        }

    def _build_sensor_states(
        self,
        snapshot: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:

        return {
            "sht45": self._sensor_state(
                "sht45",
                snapshot.get("sht45")
            ),
            "bmp390": self._sensor_state(
                "bmp390",
                snapshot.get("bmp390")
            )
        }

    def _state_label(
        self,
        sensor_states: Dict[str, Dict[str, Any]]
    ) -> str:

        online_count = sum(
            1
            for sensor_name in self.required_sensors
            if sensor_states.get(sensor_name, {}).get("online")
        )

        if online_count == len(self.required_sensors):
            return "ONLINE"

        if online_count == 0:
            return "OFFLINE"

        return "DEGRADED"

    def _is_enviro_online(
        self,
        sensor_states: Dict[str, Dict[str, Any]]
    ) -> bool:

        return all(
            sensor_states.get(sensor_name, {}).get("online", False)
            for sensor_name in self.required_sensors
        )

    def _state_changed(
        self,
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool
    ) -> bool:

        if self.enviro_online is None:
            return True

        if self.enviro_online != enviro_online:
            return True

        for sensor_name, sensor_state in sensor_states.items():

            previous_state = self.sensor_states.get(sensor_name)
            current_online = sensor_state.get("online")

            if previous_state is None:
                return True

            if previous_state != current_online:
                return True

        return False

    def _store_state(
        self,
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool
    ):

        for sensor_name, sensor_state in sensor_states.items():
            self.sensor_states[sensor_name] = sensor_state.get("online")

        self.enviro_online = enviro_online

    def _state_heartbeat_due(self, now: float) -> bool:

        return (
            now - self.last_state_publish
            >= self.state_heartbeat_sec
        )

    # --------------------------------------------------
    # Payload Builders
    # --------------------------------------------------

    def _reading(
        self,
        snapshot: Dict[str, Any],
        sensor_name: str,
        field_name: str
    ):

        sensor_snapshot = snapshot.get(sensor_name)

        if not isinstance(sensor_snapshot, dict):
            return None

        return sensor_snapshot.get(field_name)

    def _build_state_payload(
        self,
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool
    ) -> Dict[str, Any]:

        return {
            "subsystem": "environmental",
            "state": self._state_label(sensor_states),
            "online": enviro_online,
            "enabled": True,
            "enviro_online": enviro_online,
            "required_sensors": list(self.required_sensors),
            "sensors": sensor_states
        }

    def _build_enviro_payload(
        self,
        snapshot: Dict[str, Any],
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool
    ) -> Dict[str, Any]:

        return {
            "subsystem": "environmental",
            "online": enviro_online,
            "state": self._state_label(sensor_states),
            "temperature_c": self._reading(
                snapshot,
                "sht45",
                "temperature_c"
            ),
            "humidity_rh": self._reading(
                snapshot,
                "sht45",
                "humidity_rh"
            ),
            "pressure_hpa": self._reading(
                snapshot,
                "bmp390",
                "pressure_hpa"
            ),
            "altitude_m": self._reading(
                snapshot,
                "bmp390",
                "altitude_m"
            ),
            "sensors": sensor_states,
            "snapshot": snapshot
        }

    # --------------------------------------------------
    # Publishers
    # --------------------------------------------------

    def _publish_enviro_state(
        self,
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool
    ):

        self.event_services.publish_enviro_state(
            self._build_state_payload(
                sensor_states=sensor_states,
                enviro_online=enviro_online
            )
        )

        self.last_state_publish = time.time()

    def _publish_enviro_event(
        self,
        snapshot: Dict[str, Any],
        sensor_states: Dict[str, Dict[str, Any]],
        enviro_online: bool
    ):

        self.event_services.publish_enviro_event(
            self._build_enviro_payload(
                snapshot=snapshot,
                sensor_states=sensor_states,
                enviro_online=enviro_online
            )
        )

        self.last_enviro_publish = time.time()

    # --------------------------------------------------
    # Main Loop
    # --------------------------------------------------

    def run(self):

        while self.running:

            try:

                snapshot = self.driver_manager.get_snapshot()
                sensor_states = self._build_sensor_states(snapshot)
                enviro_online = self._is_enviro_online(sensor_states)

                now = time.time()

                if (
                    self._state_changed(sensor_states, enviro_online)
                    or self._state_heartbeat_due(now)
                ):
                    self._publish_enviro_state(
                        sensor_states=sensor_states,
                        enviro_online=enviro_online
                    )

                if (
                    now - self.last_enviro_publish
                    >= self.enviro_interval_sec
                ):
                    self._publish_enviro_event(
                        snapshot=snapshot,
                        sensor_states=sensor_states,
                        enviro_online=enviro_online
                    )

                self._store_state(
                    sensor_states=sensor_states,
                    enviro_online=enviro_online
                )

            except Exception as e:

                self.log(f"Loop error: {e}")

            time.sleep(self.loop_delay_sec)


if __name__ == "__main__":

    class MockBus:

        def publish(self, event):

            print()
            print("[BUS]")
            print(event)

    dispatcher = EnvironmentalDispatcher(
        event_bus=MockBus(),
        node_id="node_01",
        enviro_interval_sec=30,
        debug=True
    )

    try:

        dispatcher.start()

    except KeyboardInterrupt:

        dispatcher.stop()
