#!/usr/bin/env python3
"""
environmental_event_services.py

Environmental Event Publisher

Publishes only the environmental contract events used by the node:
- ENVIRO_STATE
- ENVIRO_EVENT
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


class EnvironmentalEventServices:

    def __init__(
        self,
        event_bus,
        node_id: str,
        target: str = "server",
        debug: bool = True
    ):

        self.event_bus = event_bus
        self.node_id = node_id
        self.target = target
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
    # Event Builder
    # --------------------------------------------------

    def _timestamp(self) -> str:

        return datetime.now(timezone.utc).isoformat()

    def _build_event(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:

        return {
            "event_type": event_type,
            "source": self.node_id,
            "target": self.target,
            "timestamp": self._timestamp(),
            "payload": payload
        }

    # --------------------------------------------------
    # Generic Publisher
    # --------------------------------------------------

    def publish(self, event: Dict[str, Any]):

        try:

            self.event_bus.publish(event)

            self.log(
                f"Published: "
                f"{event.get('event_type', 'UNKNOWN')}"
            )

        except Exception as e:

            self.log(f"Publish failed: {e}")

    # --------------------------------------------------
    # Environmental Contract Events
    # --------------------------------------------------

    def publish_enviro_state(
        self,
        state_payload: Dict[str, Any]
    ):

        payload = {
            "node_id": self.node_id,
            **state_payload
        }

        self.publish(
            self._build_event(
                event_type="ENVIRO_STATE",
                payload=payload
            )
        )

    def publish_enviro_event(
        self,
        enviro_payload: Dict[str, Any]
    ):

        payload = {
            "node_id": self.node_id,
            **enviro_payload
        }

        self.publish(
            self._build_event(
                event_type="ENVIRO_EVENT",
                payload=payload
            )
        )


if __name__ == "__main__":

    class MockBus:

        def publish(self, event):

            print(f"[BUS] {event}")

    bus = MockBus()

    events = EnvironmentalEventServices(
        event_bus=bus,
        node_id="node_01",
        debug=True
    )

    events.publish_enviro_state({
        "subsystem": "environmental",
        "state": "ONLINE",
        "online": True,
        "enabled": True,
        "enviro_online": True,
        "sensors": {
            "sht45": {"online": True, "last_error": None},
            "bmp390": {"online": True, "last_error": None}
        }
    })

    events.publish_enviro_event({
        "temperature_c": 22.5,
        "humidity_rh": 41.2,
        "pressure_hpa": 845.3,
        "snapshot": {}
    })
