#!/usr/bin/env python3
"""
environmental_event_services.py

Environmental Event Publisher
"""

from __future__ import annotations


class EnvironmentalEventServices:

    def __init__(self, event_bus, debug: bool = True):

        self.event_bus = event_bus
        self.debug = debug

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message: str):

        if self.debug:
            print(
                f"[EnvironmentalEventServices] {message}"
            )

    # --------------------------------------------------
    # Generic Publisher
    # --------------------------------------------------

    def publish(self, event: dict):

        try:

            self.event_bus.publish(event)

            self.log(
                f"Published: "
                f"{event.get('event_type', 'UNKNOWN')}"
            )

        except Exception as e:

            self.log(f"Publish failed: {e}")

    # --------------------------------------------------
    # Weather
    # --------------------------------------------------

    def publish_weather(
        self,
        weather_event: dict
    ):

        self.publish(weather_event)

    # --------------------------------------------------
    # Sensor Status
    # --------------------------------------------------

    def publish_sensor_online(
        self,
        sensor_name: str
    ):

        event = {
            "event_type":
            f"{sensor_name.upper()}_ONLINE"
        }

        self.publish(event)

    def publish_sensor_failure(
        self,
        sensor_name: str
    ):

        event = {
            "event_type":
            f"{sensor_name.upper()}_FAILURE"
        }

        self.publish(event)


if __name__ == "__main__":

    class MockBus:

        def publish(self, event):

            print(f"[BUS] {event}")

    bus = MockBus()

    events = EnvironmentalEventServices(
        event_bus=bus,
        debug=True
    )

    events.publish_weather({
        "event_type": "WEATHER",
        "temperature_c": 22.5,
        "humidity_rh": 41.2,
        "pressure_hpa": 845.3
    })

    events.publish_sensor_online(
        "sht45"
    )

    events.publish_sensor_failure(
        "bmp390"
    )