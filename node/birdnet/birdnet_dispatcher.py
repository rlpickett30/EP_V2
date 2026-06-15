# ============================================================
# birdnet_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   BirdNET
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own the BirdNET subsystem workflow.
#
# Expected config source:
#   birdnet_config.json
#
# Expected config section:
#   Full file
#
# Does:
#   - Load BirdNET configuration
#   - Start the BirdNET subsystem
#   - Register BirdNET event subscriptions
#   - Track runtime BirdNET location settings
#   - Handle GPS_COORD events
#   - Handle RECORDING_AVAILABLE events
#   - Coordinate BirdNetManager
#   - Publish AVIS_LITE events through BirdNetEventServices
#
# Does NOT:
#   - Analyze WAV files directly
#   - Subscribe directly to the event bus
#   - Publish directly to the event bus
#   - Rewrite runtime GPS values back into config
#   - Publish state events
#   - Publish mode events
#   - Own node registration
#
# Owner:
#   Main / Subsystem root
#
# ============================================================

from __future__ import annotations

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from birdnet.birdnet_event_services import BirdNetEventServices
from birdnet.birdnet_manager import BirdNetManager

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json

from datetime import datetime
from datetime import timezone


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class BirdNetDispatcher:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        config_path="birdnet/birdnet_config.json",
        debug=None
    ):

        self.config_path = config_path
        self.config = self.load_config()

        if debug is None:

            self.debug = self.config.get(
                "debug",
                True
            )

        else:

            self.debug = debug

        # ----------------------------------------------------
        # Runtime location state.
        #
        # Important:
        # These values intentionally start from the configured
        # Durango defaults every boot. GPS updates may change
        # runtime values, but this dispatcher does not write
        # last-seen GPS values back into config.
        # ----------------------------------------------------

        self.current_latitude = self.config.get(
            "default_latitude"
        )

        self.current_longitude = self.config.get(
            "default_longitude"
        )

        self.gps_acquired = False

        self.manager = BirdNetManager(
            recordings_path=self.config[
                "recordings_path"
            ],
            debug=self.debug
        )

        self.event_services = BirdNetEventServices(
            event_bus=event_bus,
            debug=self.debug
        )

    # ========================================================
    # DEBUG
    # ========================================================

    def log(
        self,
        message
    ):

        if self.debug:

            print(
                f"[BirdNetDispatcher] {message}"
            )

    # ========================================================
    # CONFIG
    # ========================================================

    def load_config(
        self
    ):

        with open(
            self.config_path,
            "r"
        ) as file:

            return json.load(
                file
            )

    # ========================================================
    # STARTUP
    # ========================================================

    def start(
        self
    ):

        self.log(
            "Starting BirdNET subsystem"
        )

        self.register_subscriptions()

        self.log(
            "BirdNET subsystem started"
        )

    # ========================================================
    # EVENT REGISTRATION
    # ========================================================

    def register_subscriptions(
        self
    ):

        self.event_services.subscribe_gps_coord(
            self.handle_gps_coord
        )

        self.event_services.subscribe_recording_available(
            self.handle_recording_available
        )

        self.log(
            "Subscriptions registered"
        )

    # ========================================================
    # EVENT HANDLING: GPS_COORD
    # ========================================================

    def handle_gps_coord(
        self,
        event
    ):

        if not self.should_use_gps_updates():

            self.log(
                "Ignoring GPS_COORD because GPS updates are disabled"
            )

            return

        payload = self.get_payload(
            event
        )

        gps_coord = payload.get(
            "gps_coord",
            {}
        )

        latitude = gps_coord.get(
            "lat",
            payload.get(
                "lat",
                payload.get(
                    "latitude"
                )
            )
        )

        longitude = gps_coord.get(
            "lon",
            payload.get(
                "lon",
                payload.get(
                    "longitude"
                )
            )
        )

        if latitude is None or longitude is None:

            self.log(
                "GPS_COORD ignored because lat/lon were missing"
            )

            return

        self.current_latitude = latitude
        self.current_longitude = longitude
        self.gps_acquired = True

        self.log(
            f"Runtime GPS updated: {latitude}, {longitude}"
        )

    # ========================================================
    # EVENT HANDLING: RECORDING_AVAILABLE
    # ========================================================

    def handle_recording_available(
        self,
        event
    ):

        payload = self.get_payload(
            event
        )

        recording_id = payload.get(
            "recording_id",
            event.get(
                "recording_id"
            )
        )

        if recording_id is None:

            self.log(
                "RECORDING_AVAILABLE ignored because recording_id was missing"
            )

            return

        recording_path = payload.get(
            "recording_path",
            event.get(
                "recording_path"
            )
        )

        self.log(
            f"Recording received: {recording_id}"
        )

        avis_lite_events = self.manager.process_recording(
            recording_id=recording_id,
            latitude=self.current_latitude,
            longitude=self.current_longitude,
            week=self.get_week(),
            min_confidence=self.config[
                "min_confidence"
            ]
        )

        for avis_lite_event in avis_lite_events:

            simulator_form_event = self.build_simulator_form_avis_lite(
                avis_lite_event=avis_lite_event,
                source_payload=payload,
                recording_id=recording_id,
                recording_path=recording_path
            )

            self.event_services.publish_avis_lite(
                simulator_form_event
            )

    # ========================================================
    # AVIS_LITE EVENT NORMALIZATION
    # ========================================================

    def build_simulator_form_avis_lite(
        self,
        avis_lite_event,
        source_payload,
        recording_id,
        recording_path
    ):

        detection_time_utc = self.get_utc_timestamp()

        payload = {
            "node_id": source_payload.get(
                "node_id"
            ),
            "node_name": source_payload.get(
                "node_name"
            ),
            "species_common": self.get_first_available(
                avis_lite_event,
                [
                    "species_common",
                    "common_name"
                ],
                default="unknown"
            ),
            "species_scientific": self.get_first_available(
                avis_lite_event,
                [
                    "species_scientific",
                    "scientific_name"
                ],
                default="unknown"
            ),
            "confidence": avis_lite_event.get(
                "confidence",
                0.0
            ),
            "detection_time_utc": self.get_first_available(
                avis_lite_event,
                [
                    "detection_time_utc",
                    "birdnet_event_utc"
                ],
                default=detection_time_utc
            ),
            "recording_id": recording_id,
            "recording_path": recording_path
        }

        return {
            "event_type": "AVIS_LITE",
            "source": "birdnet",
            "target": "sender",
            "timestamp": detection_time_utc,
            "payload": payload
        }

    # ========================================================
    # WEEK SELECTION
    # ========================================================

    def get_week(
        self
    ):

        if self.config.get(
            "week_mode"
        ) == "manual":

            return self.config.get(
                "manual_week"
            )

        return (
            datetime.now(
                timezone.utc
            )
            .isocalendar()
            .week
        )

    # ========================================================
    # RUNTIME LOCATION SETTINGS
    # ========================================================

    def should_use_gps_updates(
        self
    ):

        if not self.config.get(
            "use_gps_updates",
            True
        ):

            return False

        if self.config.get(
            "location_mode",
            "auto"
        ) != "auto":

            return False

        return True

    # ========================================================
    # EVENT HELPERS
    # ========================================================

    def get_payload(
        self,
        event
    ):

        if not isinstance(
            event,
            dict
        ):

            return {}

        payload = event.get(
            "payload"
        )

        if isinstance(
            payload,
            dict
        ):

            return payload

        return event

    def get_first_available(
        self,
        source,
        keys,
        default=None
    ):

        for key in keys:

            value = source.get(
                key
            )

            if value is not None:

                return value

        return default

    def get_utc_timestamp(
        self
    ):

        return (
            datetime.now(
                timezone.utc
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z"
            )
        )