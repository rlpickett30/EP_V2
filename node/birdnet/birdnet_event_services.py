# ============================================================
# birdnet_event_services.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   BirdNET
#
# Role:
#   Event Services
#
# Purpose:
#   Connect the BirdNET subsystem to the EnviroPulse event bus.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Subscribe BirdNET dispatcher callbacks to BirdNET input events
#   - Publish BirdNET output events
#   - Provide a thin communication layer between BirdNET and the event bus
#
# Does NOT:
#   - Analyze WAV files
#   - Inspect event payloads
#   - Make workflow decisions
#   - Track BirdNET state
#   - Modify configuration
#
# Owner:
#   birdnet_dispatcher.py
#
# ============================================================

from __future__ import annotations


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class BirdNetEventServices:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        debug=True
    ):

        self.event_bus = event_bus
        self.debug = debug

    # ========================================================
    # DEBUG
    # ========================================================

    def log(
        self,
        message
    ):

        if self.debug:

            print(
                f"[BirdNetEventServices] {message}"
            )

    # ========================================================
    # GENERIC EVENT BUS ACCESS
    # ========================================================

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
                f"Subscribed to {event_type}"
            )

        except Exception as error:

            self.log(
                f"Subscribe failed for {event_type}: {error}"
            )

    def publish(
        self,
        event
    ):

        try:

            self.event_bus.publish(
                event
            )

            self.log(
                f"Published {event.get('event_type')}"
            )

        except Exception as error:

            self.log(
                f"Publish failed: {error}"
            )

    # ========================================================
    # BIRDNET SUBSCRIPTIONS
    # ========================================================

    def subscribe_gps_coord(
        self,
        callback
    ):

        self.subscribe(
            "GPS_COORD",
            callback
        )

    def subscribe_recording_available(
        self,
        callback
    ):

        self.subscribe(
            "RECORDING_AVAILABLE",
            callback
        )

    # ========================================================
    # BIRDNET PUBLICATIONS
    # ========================================================

    def publish_avis_lite(
        self,
        avis_lite_event
    ):

        self.publish(
            avis_lite_event
        )