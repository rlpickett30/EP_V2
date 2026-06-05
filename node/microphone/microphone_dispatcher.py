"""
microphone_dispatcher.py

Responsibilities:

- Load microphone configuration
- Own microphone loop
- Own microphone manager
- Own recycler
- Own microphone event services
- Track PPS state
- Control recording timing
- Control recycler timing
- React to AVIS_LITE
- React to TDOA_REQUEST

This module intentionally knows nothing about:

- Audio hardware internals
- BirdNET internals
- Sender internals
- EventBus internals
"""

from __future__ import annotations

import json
import time

from pathlib import Path

from microphone.microphone_loop import MicrophoneLoop
from microphone.microphone_manager import MicrophoneManager
from microphone.microphone_event_services import MicrophoneEventServices
from microphone.recycler import Recycler


class MicrophoneDispatcher:

    def __init__(
        self,
        event_bus,
        config_path="microphone/microphone_config.json",
        debug=True
    ):

        self.debug = debug
        self.config_path = config_path
        self.config = self.load_config()

        self.loop = MicrophoneLoop(
            recordings_root=self.config["recordings_root"],
            sample_rate=self.config["sample_rate"],
            channels=self.config["channels"],
            debug=self.config.get("debug", debug)
        )

        self.manager = MicrophoneManager(
            debug=self.config.get("debug", debug)
        )

        self.recycler = Recycler(
            recordings_root=self.config["recordings_root"],
            default_retention_days=self.config["storage_retention_days"],
            debug=self.config.get("debug", debug)
        )

        self.event_services = MicrophoneEventServices(
            event_bus=event_bus,
            debug=self.config.get("debug", debug)
        )

        self.pps_locked = False
        self.running = False

        self.last_recording_time = 0
        self.last_recycler_time = 0

        self.recording_index = {}

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:
            print(f"[MicrophoneDispatcher] {message}")

    # --------------------------------------------------
    # Config
    # --------------------------------------------------

    def load_config(self):

        with open(self.config_path, "r") as file:
            return json.load(file)

    # --------------------------------------------------
    # Startup
    # --------------------------------------------------

    def start(self):

        self.log("Starting microphone subsystem")

        self.register_subscriptions()

        self.running = True
        self.run()

    def stop(self):

        self.log("Stopping microphone subsystem")
        self.running = False

    # --------------------------------------------------
    # Subscriptions
    # --------------------------------------------------

    def register_subscriptions(self):

        self.event_services.subscribe_pps_lock(
            self.handle_pps_lock
        )

        self.event_services.subscribe_pps_lost(
            self.handle_pps_lost
        )

        self.event_services.subscribe_avis_lite(
            self.handle_avis_lite
        )

        self.event_services.subscribe_tdoa_request(
            self.handle_tdoa_request
        )

        self.log("Subscriptions registered")

    # --------------------------------------------------
    # PPS Handlers
    # --------------------------------------------------

    def handle_pps_lock(self, event):

        self.pps_locked = True

        self.log("PPS lock received")

    def handle_pps_lost(self, event):

        self.pps_locked = False

        self.log("PPS lost received")

    # --------------------------------------------------
    # Recording Permission
    # --------------------------------------------------

    def recording_allowed(self):

        require_pps = self.config.get(
            "require_pps_lock",
            False
        )

        if require_pps and not self.pps_locked:
            return False

        return True

    # --------------------------------------------------
    # Normal Recording
    # --------------------------------------------------

    def make_recording(self):

        if not self.recording_allowed():

            self.log(
                "Recording skipped because PPS lock is required"
            )

            return

        recording = self.loop.record(
            duration_sec=self.config["recording_duration_sec"]
        )

        event = self.manager.build_recording_available_event(
            recording
        )

        self.recording_index[
            event["recording_id"]
        ] = event

        self.write_initial_metadata(event)

        self.event_services.publish_recording_available(
            event
        )

        self.log(
            f"Published recording: {event['recording_id']}"
        )

    # --------------------------------------------------
    # TDOA Request
    # --------------------------------------------------

    def handle_tdoa_request(self, event):

        recording_id = event.get("recording_id")

        if recording_id and recording_id in self.recording_index:

            recording_event = self.recording_index[
                recording_id
            ]

            tdoa_event = self.manager.build_tdoa_recording_event(
                recording_event
            )

            self.event_services.publish_tdoa_recording(
                tdoa_event
            )

            self.log(
                f"Published TDOA pointer: {recording_id}"
            )

            return

        self.log(
            "TDOA request did not match a known recording"
        )

    # --------------------------------------------------
    # AVIS Retention
    # --------------------------------------------------

    def handle_avis_lite(self, event):

        recording_id = event.get("recording_id")

        if not recording_id:

            self.log("AVIS_LITE missing recording_id")
            return

        recording_event = self.recording_index.get(
            recording_id
        )

        if not recording_event:

            self.log(
                f"AVIS_LITE references unknown recording: {recording_id}"
            )

            return

        metadata_path = Path(
            recording_event["metadata_path"]
        )

        metadata = self.load_metadata(metadata_path)

        metadata["preserve"] = True
        metadata["retention_days"] = self.config[
            "bird_recording_retention_days"
        ]
        metadata["species_detected"] = True

        species = event.get("common_name")

        if species:

            if "species" not in metadata:
                metadata["species"] = []

            if species not in metadata["species"]:
                metadata["species"].append(species)

        self.save_metadata(
            metadata_path,
            metadata
        )

        self.log(
            f"Marked recording for preservation: {recording_id}"
        )

    # --------------------------------------------------
    # Metadata
    # --------------------------------------------------

    def write_initial_metadata(self, event):

        metadata = {

            "recording_id": event["recording_id"],

            "recording_utc": event["recording_utc"],

            "wav_path": event["wav_path"],

            "preserve": False,

            "species_detected": False,

            "retention_days": self.config[
                "storage_retention_days"
            ]
        }

        self.save_metadata(
            event["metadata_path"],
            metadata
        )

    def load_metadata(self, metadata_path):

        try:

            with open(metadata_path, "r") as file:
                return json.load(file)

        except Exception:

            return {}

    def save_metadata(self, metadata_path, metadata):

        metadata_path = Path(metadata_path)

        metadata_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with open(metadata_path, "w") as file:

            json.dump(
                metadata,
                file,
                indent=4
            )

    # --------------------------------------------------
    # Recycler
    # --------------------------------------------------

    def run_recycler(self):

        self.recycler.cleanup()

        self.log("Recycler completed")

    # --------------------------------------------------
    # Main Loop
    # --------------------------------------------------

    def run(self):

        self.last_recording_time = time.time()
        self.last_recycler_time = time.time()

        while self.running:

            now = time.time()

            recording_interval = self.config[
                "recording_interval_sec"
            ]

            recycler_interval = self.config[
                "recycler_interval_sec"
            ]

            if now - self.last_recording_time >= recording_interval:

                self.make_recording()
                self.last_recording_time = now

            if now - self.last_recycler_time >= recycler_interval:

                self.run_recycler()
                self.last_recycler_time = now

            time.sleep(1)