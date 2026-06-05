"""
birdnet_event_services.py

BirdNET Event Mailbox

Responsibilities:

- Subscribe to BirdNET events
- Publish BirdNET events

This module intentionally contains no:

- BirdNET logic
- GPS logic
- State tracking
- Timing logic
- Recording logic
- Configuration logic

It is simply the communication layer
between the BirdNET subsystem and
the EventBus.
"""

from __future__ import annotations


class BirdNetEventServices:

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
                f"[BirdNetEventServices] {message}"
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
    # Generic Subscriber
    # --------------------------------------------------

    def subscribe(
        self,
        event_type,
        callback
    ):

        try:

            self.event_bus.subscribe(
                event_type,
                callback
            )

            self.log(
                f"Subscribed: {event_type}"
            )

        except Exception as e:

            self.log(
                f"Subscribe failed: {e}"
            )

    # --------------------------------------------------
    # BirdNET Publications
    # --------------------------------------------------

    def publish_avis_lite(
        self,
        avis_event
    ):

        self.publish(
            avis_event
        )

    # --------------------------------------------------
    # BirdNET Subscriptions
    # --------------------------------------------------

    def subscribe_recording_available(
        self,
        callback
    ):

        self.subscribe(
            "RECORDING_AVAILABLE",
            callback
        )

    def subscribe_gps_coord(
        self,
        callback
    ):

        self.subscribe(
            "GPS_COORD",
            callback
        )