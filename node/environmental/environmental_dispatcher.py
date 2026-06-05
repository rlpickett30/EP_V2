#!/usr/bin/env python3
"""
environmental_dispatcher.py

Environmental Subsystem Dispatcher
"""

from __future__ import annotations

import time

from environmental.driver_manager import DriverManager
from environmental.environmental_event_services import EnvironmentalEventServices


class EnvironmentalDispatcher:

    def __init__(
        self,
        event_bus,
        weather_interval_sec: int = 300,
        loop_delay_sec: float = 1.0,
        debug: bool = True
    ):

        self.debug = debug

        self.weather_interval_sec = weather_interval_sec
        self.loop_delay_sec = loop_delay_sec

        self.driver_manager = DriverManager(
            debug=debug
        )

        self.event_services = EnvironmentalEventServices(
            event_bus=event_bus,
            debug=debug
        )

        self.last_weather_publish = 0

        self.sensor_states = {
            "sht45": None,
            "bmp390": None
        }

        self.running = False

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

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

    def _is_online(self, sensor_snapshot):

        if sensor_snapshot is None:
            return False

        if sensor_snapshot.get("last_error"):
            return False

        return True

    def _check_sensor_state(
        self,
        sensor_name,
        current_state
    ):

        previous_state = self.sensor_states[sensor_name]

        if previous_state is None:

            self.sensor_states[sensor_name] = current_state
            return

        if previous_state and not current_state:

            self.event_services.publish_sensor_failure(
                sensor_name
            )

        elif not previous_state and current_state:

            self.event_services.publish_sensor_online(
                sensor_name
            )

        self.sensor_states[sensor_name] = current_state

    # --------------------------------------------------
    # Weather Event
    # --------------------------------------------------

    def _publish_weather(self, snapshot):

        weather_event = {
            "event_type": "WEATHER",
            "timestamp": time.time(),
            "snapshot": snapshot
        }

        self.event_services.publish_weather(
            weather_event
        )

    # --------------------------------------------------
    # Main Loop
    # --------------------------------------------------

    def run(self):

        self.last_weather_publish = time.time()

        while self.running:

            try:

                snapshot = (
                    self.driver_manager.get_snapshot()
                )

                self._check_sensor_state(
                    "sht45",
                    self._is_online(
                        snapshot.get("sht45")
                    )
                )

                self._check_sensor_state(
                    "bmp390",
                    self._is_online(
                        snapshot.get("bmp390")
                    )
                )

                now = time.time()

                if (
                    now - self.last_weather_publish
                    >= self.weather_interval_sec
                ):

                    self._publish_weather(snapshot)

                    self.last_weather_publish = now

            except Exception as e:

                self.log(f"Loop error: {e}")

            time.sleep(
                self.loop_delay_sec
            )


if __name__ == "__main__":

    class MockBus:

        def publish(self, event):

            print()
            print("[BUS]")
            print(event)

    dispatcher = EnvironmentalDispatcher(
        event_bus=MockBus(),
        weather_interval_sec=30,
        debug=True
    )

    try:

        dispatcher.start()

    except KeyboardInterrupt:

        dispatcher.stop()