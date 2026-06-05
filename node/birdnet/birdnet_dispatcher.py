"""
birdnet_dispatcher.py

Responsibilities:

- Load configuration
- Manage BirdNET settings
- Handle GPS injection
- Handle BirdNET subscriptions
- React to incoming events
- Coordinate manager and event services

This module intentionally knows nothing about:

- BirdNET internals
- WAV analysis
- EventBus internals
"""

from __future__ import annotations

import json

from datetime import datetime

from birdnet.birdnet_manager import BirdNetManager
from birdnet.birdnet_event_services import BirdNetEventServices


class BirdNetDispatcher:

    def __init__(
        self,
        event_bus,
        config_path="birdnet/birdnet_config.json",
        debug=True
    ):

        self.debug = debug

        self.config_path = config_path

        self.config = self.load_config()

        self.manager = BirdNetManager(
            recordings_path=self.config[
                "recordings_path"
            ],
            debug=debug
        )

        self.event_services = (
            BirdNetEventServices(
                event_bus=event_bus,
                debug=debug
            )
        )

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:

            print(
                f"[BirdNetDispatcher] {message}"
            )

    # --------------------------------------------------
    # Config
    # --------------------------------------------------

    def load_config(self):

        with open(
            self.config_path,
            "r"
        ) as file:

            return json.load(file)

    def save_config(self):

        with open(
            self.config_path,
            "w"
        ) as file:

            json.dump(
                self.config,
                file,
                indent=4
            )

    # --------------------------------------------------
    # Startup
    # --------------------------------------------------

    def start(self):

        self.log(
            "Starting BirdNET subsystem"
        )

        self.register_subscriptions()

    # --------------------------------------------------
    # Event Registration
    # --------------------------------------------------

    def register_subscriptions(self):

        self.event_services.subscribe(
            "RECORDING_AVAILABLE",
            self.handle_recording_available
        )

        self.event_services.subscribe(
            "GPS_LOCK",
            self.handle_gps_lock
        )

        self.log(
            "Subscriptions registered"
        )

    # --------------------------------------------------
    # GPS
    # --------------------------------------------------

    def handle_gps_lock(
        self,
        event
    ):

        if (
            not self.config[
                "use_gps_updates"
            ]
            and
            self.config[
                "gps_acquired"
            ]
        ):

            self.log(
                "Ignoring GPS update"
            )

            return

        self.config[
            "current_latitude"
        ] = event["latitude"]

        self.config[
            "current_longitude"
        ] = event["longitude"]

        self.config[
            "gps_acquired"
        ] = True

        self.save_config()

        self.log(
            f"GPS updated: "
            f"{event['latitude']}, "
            f"{event['longitude']}"
        )

    # --------------------------------------------------
    # Recording Processing
    # --------------------------------------------------

    def handle_recording_available(
        self,
        event
    ):

        recording_id = event[
            "recording_id"
        ]

        self.log(
            f"Recording received: "
            f"{recording_id}"
        )

        latitude = self.config[
            "current_latitude"
        ]

        longitude = self.config[
            "current_longitude"
        ]

        min_confidence = self.config[
            "min_confidence"
        ]

        week = self.get_week()

        avis_events = (
            self.manager.process_recording(
                recording_id=recording_id,
                latitude=latitude,
                longitude=longitude,
                week=week,
                min_confidence=min_confidence
            )
        )

        for avis_event in avis_events:

            self.event_services.publish_avis_lite(
                avis_event
            )

    # --------------------------------------------------
    # Week Selection
    # --------------------------------------------------

    def get_week(self):

        if (
            self.config[
                "week_mode"
            ]
            == "manual"
        ):

            return self.config[
                "manual_week"
            ]

        return (
            datetime.utcnow()
            .isocalendar()
            .week
        )