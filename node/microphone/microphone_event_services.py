# ============================================================
# microphone_event_services.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Microphone
#
# Role:
#   Event Services
#
# Purpose:
#   Connect the microphone subsystem to the EnviroPulse event bus.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Subscribe microphone dispatcher callbacks to microphone input events
#   - Subscribe to PPS_STATE events
#   - Subscribe to PPS_EDGE events
#   - Subscribe to GPS_STATE events
#   - Subscribe to TDOA_REQUEST events
#   - Publish RECORDING_AVAILABLE events
#   - Publish TDOA_RECORDING events
#   - Publish MICROPHONE_SYNCED events
#   - Provide a thin communication layer between Microphone and the event bus
#
# Does NOT:
#   - Record audio
#   - Inspect event payloads
#   - Track PPS or GPS state
#   - Make workflow decisions
#   - Handle recording timing
#   - Access microphone hardware
#   - Handle configuration
#   - Own microphone subsystem startup
#
# Owner:
#   microphone_dispatcher.py
#
# ============================================================

from __future__ import annotations


RECORDING_AVAILABLE = "RECORDING_AVAILABLE"
TDOA_RECORDING = "TDOA_RECORDING"
MICROPHONE_SYNCED = "MICROPHONE_SYNCED"

PPS_STATE = "PPS_STATE"
PPS_EDGE = "PPS_EDGE"
GPS_STATE = "GPS_STATE"
TDOA_REQUEST = "TDOA_REQUEST"


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

    def publish_microphone_synced(self, event):

        self.publish(event)

    # --------------------------------------------------
    # Subscribers
    # --------------------------------------------------

    def subscribe_pps_state(self, callback):

        self.subscribe(
            PPS_STATE,
            callback
        )

    def subscribe_pps_edge(self, callback):

        self.subscribe(
            PPS_EDGE,
            callback
        )

    def subscribe_gps_state(self, callback):

        self.subscribe(
            GPS_STATE,
            callback
        )

    def subscribe_tdoa_request(self, callback):

        self.subscribe(
            TDOA_REQUEST,
            callback
        )