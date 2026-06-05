"""
RTK_event_services.py

RTK Event Mailbox

Responsibilities:

- Publish RTK events

This module intentionally contains no:

- GPS logic
- PPS logic
- State tracking
- Hardware access
- Event decisions
- Configuration handling

It is simply the RTK mailbox.
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

    def log(self, message):

        if self.debug:

            print(
                f"[RTKEventServices] {message}"
            )

    # --------------------------------------------------
    # Generic Publisher
    # --------------------------------------------------

    def publish(self, event):

        try:

            self.event_bus.publish(
                event
            )

            self.log(
                f"Published: "
                f"{event.get('event_type')}"
            )

        except Exception as e:

            self.log(
                f"Publish failed: {e}"
            )

    # --------------------------------------------------
    # GPS Events
    # --------------------------------------------------

    def publish_gps_lock(
        self,
        event
    ):

        self.publish(event)

    def publish_gps_lost(
        self,
        event
    ):

        self.publish(event)

    def publish_gps_coord(
        self,
        event
    ):

        self.publish(event)

    # --------------------------------------------------
    # PPS Events
    # --------------------------------------------------

    def publish_pps_lock(
        self,
        event
    ):

        self.publish(event)

    def publish_pps_lost(
        self,
        event
    ):

        self.publish(event)