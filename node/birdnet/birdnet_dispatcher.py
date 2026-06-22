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
#   Own the BirdNET subsystem workflow. Receive recording and GPS events,
#   coordinate BirdNetManager analysis, and publish canonical AVIS_LITE
#   events through BirdNetEventServices.
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
#   - Track runtime BirdNET location state
#   - Handle GPS_COORD events
#   - Handle RECORDING_AVAILABLE events
#   - Coordinate BirdNetManager
#   - Build canonical AVIS_LITE events
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
#   - Send AVIS_LITE to the server directly
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

        self.event_bus = event_bus
        self.config_path = config_path
        self.config = self.load_config()

        if debug is None:

            self.debug = self.config.get(
                "debug",
                True
            )

        else:

            self.debug = debug

        self.current_latitude = self.config.get(
            "current_latitude",
            self.config.get(
                "default_latitude"
            )
        )

        self.current_longitude = self.config.get(
            "current_longitude",
            self.config.get(
                "default_longitude"
            )
        )

        self.gps_acquired = bool(
            self.config.get(
                "gps_acquired",
                False
            )
        )

        self.started = False

        self.manager = BirdNetManager(
            debug=self.debug
        )

        self.event_services = BirdNetEventServices(
            event_bus=self.event_bus,
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

        if self.started:

            self.log(
                "BirdNET subsystem already started"
            )

            return

        self.log(
            "Starting BirdNET subsystem"
        )

        self.register_subscriptions()

        self.started = True

        self.log(
            "BirdNET subsystem started"
        )

    def stop(
        self
    ):

        self.started = False

        self.log(
            "BirdNET subsystem stopped"
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
                "GPS_COORD ignored because GPS updates are disabled"
            )

            return

        payload = self.get_payload(
            event
        )

        gps_coord = payload.get(
            "gps_coord",
            {}
        )

        latitude = self.get_first_available(
            gps_coord,
            [
                "lat",
                "latitude"
            ],
            default=self.get_first_available(
                payload,
                [
                    "lat",
                    "latitude"
                ]
            )
        )

        longitude = self.get_first_available(
            gps_coord,
            [
                "lon",
                "longitude"
            ],
            default=self.get_first_available(
                payload,
                [
                    "lon",
                    "longitude"
                ]
            )
        )

        if latitude is None or longitude is None:

            self.log(
                "GPS_COORD ignored because latitude or longitude was missing"
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

        event_dict = self.get_event_dict(
            event
        )

        payload = self.get_payload(
            event_dict
        )

        recording_id = self.get_first_available(
            payload,
            [
                "recording_id",
                "event_id"
            ],
            default=self.get_first_available(
                event_dict,
                [
                    "recording_id",
                    "event_id"
                ]
            )
        )

        if recording_id is None:

            self.log(
                "RECORDING_AVAILABLE ignored because recording_id was missing"
            )

            return

        recording_path = self.get_first_available(
            payload,
            [
                "recording_path",
                "wav_path"
            ],
            default=self.get_first_available(
                event_dict,
                [
                    "recording_path",
                    "wav_path"
                ]
            )
        )

        if recording_path is None:

            self.log(
                "RECORDING_AVAILABLE ignored because recording_path was missing"
            )

            return

        self.log(
            f"Recording received: {recording_id}"
        )

        try:

            detection_packages = self.manager.process_recording(
                recording_id=recording_id,
                recording_path=recording_path,
                latitude=self.current_latitude,
                longitude=self.current_longitude,
                week=self.get_week(),
                min_confidence=self.get_min_confidence()
            )

        except Exception as error:

            self.log(
                f"BirdNET processing failed for {recording_id}: {error}"
            )

            return

        if not detection_packages:

            self.log(
                f"No BirdNET detections met threshold for {recording_id}"
            )

            return

        for detection_package in detection_packages:

            avis_lite_event = self.build_avis_lite_event(
                detection_package=detection_package,
                source_payload=payload,
                recording_id=recording_id,
                recording_path=recording_path
            )

            self.event_services.publish_avis_lite(
                avis_lite_event
            )

        self.log(
            f"Published {len(detection_packages)} AVIS_LITE event(s) for {recording_id}"
        )

    # ========================================================
    # AVIS_LITE EVENT NORMALIZATION
    # ========================================================

    def build_avis_lite_event(
        self,
        detection_package,
        source_payload,
        recording_id,
        recording_path
    ):

        detection_time_utc = self.get_utc_timestamp()

        species_common = self.get_first_available(
            detection_package,
            [
                "species_common",
                "common_name"
            ],
            default="unknown"
        )

        species_scientific = self.get_first_available(
            detection_package,
            [
                "species_scientific",
                "scientific_name"
            ],
            default="unknown"
        )

        species_code = self.get_first_available(
            detection_package,
            [
                "species_code"
            ],
            default="unknown"
        )

        confidence = self.get_first_available(
            detection_package,
            [
                "confidence"
            ],
            default=0.0
        )

        birdnet_event_id = self.get_first_available(
            detection_package,
            [
                "birdnet_event_id"
            ]
        )

        birdnet_event_utc = self.get_first_available(
            detection_package,
            [
                "birdnet_event_utc"
            ]
        )

        birdnet_start_time = self.get_first_available(
            detection_package,
            [
                "birdnet_start_time",
                "start_time"
            ]
        )

        birdnet_end_time = self.get_first_available(
            detection_package,
            [
                "birdnet_end_time",
                "end_time"
            ]
        )

        payload = {
            "node_id": source_payload.get(
                "node_id"
            ),
            "node_name": source_payload.get(
                "node_name"
            ),
            "species_common": species_common,
            "species_scientific": species_scientific,
            "species_code": species_code,
            "confidence": confidence,
            "detection_time_utc": detection_time_utc,
            "birdnet_event_id": birdnet_event_id,
            "birdnet_event_utc": birdnet_event_utc,
            "birdnet_start_time": birdnet_start_time,
            "birdnet_end_time": birdnet_end_time,
            "recording_id": recording_id,
            "recording_path": recording_path,
            "wav_path": source_payload.get(
                "wav_path",
                recording_path
            ),
            "recording_utc": source_payload.get(
                "recording_utc"
            ),
            "sample_rate": source_payload.get(
                "sample_rate"
            ),
            "channels": source_payload.get(
                "channels"
            ),
            "duration_sec": source_payload.get(
                "duration_sec"
            ),
            "recording_type": source_payload.get(
                "recording_type"
            ),
            "sync_source": source_payload.get(
                "sync_source"
            ),
            "pps_locked": source_payload.get(
                "pps_locked"
            )
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

    def get_min_confidence(
        self
    ):

        return self.config.get(
            "min_confidence",
            0.25
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

    def get_event_dict(
        self,
        event
    ):

        if isinstance(
            event,
            dict
        ):

            return event

        return {}

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

        if not isinstance(
            source,
            dict
        ):

            return default

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