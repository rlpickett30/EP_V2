"""
RTK_event_services.py

EnviroPulse V2.0

Subsystem:
    RTK

Role:
    Event Services

Purpose:
    Connect the RTK subsystem to the EnviroPulse event bus.

Publishes:
    - RTK_STATE
    - GPS_STATE
    - PPS_STATE
    - GPS_COORD

Subscribes:
    - None

Does:
    - Publish canonical RTK output events
    - Provide a thin communication layer between RTK and the event bus

Does NOT:
    - Track GPS, PPS, or RTK state
    - Inspect event payloads
    - Make workflow decisions
    - Access hardware
    - Handle configuration
"""

from __future__ import annotations


class RTKEventServices:

    def __init__(
        self,
        event_bus,
        debug=True
    ):

        self.event_bus = event_bus
        self.debug = debug

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(
        self,
        message
    ):

        if self.debug:

            print(
                f"[RTKEventServices] {message}"
            )

    # --------------------------------------------------
    # Generic Publisher
    # --------------------------------------------------

    def publish(
        self,
        event
    ):

        try:

            self.event_bus.publish(
                event
            )

            self.log(
                f"Published: {event.get('event_type')}"
            )

        except Exception as error:

            self.log(
                f"Publish failed: {error}"
            )

    # --------------------------------------------------
    # RTK Publications
    # --------------------------------------------------

    def publish_rtk_state(
        self,
        event
    ):

        self.publish(
            event
        )

    def publish_gps_state(
        self,
        event
    ):

        self.publish(
            event
        )

    def publish_pps_state(
        self,
        event
    ):

        self.publish(
            event
        )

    def publish_gps_coord(
        self,
        event
    ):

        self.publish(
            event
        )
