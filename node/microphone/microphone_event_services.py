"""
microphone_event_services.py

Microphone Event Mailbox

Responsibilities:

- Publish microphone events
- Register microphone subscriptions

This module intentionally contains no:

- Recording logic
- Recycling logic
- Timing logic
- State tracking
- Event decisions
"""

from __future__ import annotations


class MicrophoneEventServices:

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
                f"[MicrophoneEventServices] {message}"
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
                f"Subscribed: "
                f"{event_type}"
            )

        except Exception as e:

            self.log(
                f"Subscribe failed: {e}"
            )

    # --------------------------------------------------
    # Publishers
    # --------------------------------------------------

    def publish_recording_available(
        self,
        event
    ):

        self.publish(event)

    def publish_tdoa_recording(
        self,
        event
    ):

        self.publish(event)

    # --------------------------------------------------
    # Subscribers
    # --------------------------------------------------

    def subscribe_pps_lock(
        self,
        callback
    ):

        self.subscribe(
            "PPS_LOCK",
            callback
        )

    def subscribe_pps_lost(
        self,
        callback
    ):

        self.subscribe(
            "PPS_LOST",
            callback
        )

    def subscribe_avis_lite(
        self,
        callback
    ):

        self.subscribe(
            "AVIS_LITE",
            callback
        )

    def subscribe_tdoa_request(
        self,
        callback
    ):

        self.subscribe(
            "TDOA_REQUEST",
            callback
        )