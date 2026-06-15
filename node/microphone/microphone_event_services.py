"""
microphone_event_services.py

Microphone Event Mailbox

Responsibilities:
- Publish microphone events
- Register microphone subscriptions

Canonical microphone event contract:
- Subscribes: PPS_STATE, TDOA_REQUEST
- Publishes: RECORDING_AVAILABLE, TDOA_RECORDING

This module intentionally contains no recording logic, timing logic,
state tracking, request decisions, or hardware access.
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

    def publish(self, event):

        try:
            self.event_bus.publish(event)

            self.log(
                f"Published: {event.get('event_type')}"
            )

        except Exception as error:
            self.log(
                f"Publish failed: {error}"
            )

    # --------------------------------------------------
    # Generic Subscriber
    # --------------------------------------------------

    def subscribe(self, event_type, callback):

        try:
            self.event_bus.subscribe(
                event_type,
                callback
            )

            self.log(
                f"Subscribed: {event_type}"
            )

        except Exception as error:
            self.log(
                f"Subscribe failed for {event_type}: {error}"
            )

    # --------------------------------------------------
    # Publishers
    # --------------------------------------------------

    def publish_recording_available(self, event):

        self.publish(event)

    def publish_tdoa_recording(self, event):

        self.publish(event)

    # --------------------------------------------------
    # Subscribers
    # --------------------------------------------------

    def subscribe_pps_state(self, callback):

        self.subscribe(
            "PPS_STATE",
            callback
        )

    def subscribe_tdoa_request(self, callback):

        self.subscribe(
            "TDOA_REQUEST",
            callback
        )
