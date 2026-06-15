"""
microphone_dispatcher.py

Responsibilities:
- Load microphone configuration
- Own microphone loop
- Own microphone manager
- Own recycler
- Own microphone event services
- Track PPS_STATE
- Control normal recording timing
- Control TDOA request recording
- Control recycler timing

Canonical microphone event contract:
- Subscribes: PPS_STATE, TDOA_REQUEST
- Publishes: RECORDING_AVAILABLE, TDOA_RECORDING

This module intentionally knows nothing about:
- Audio hardware internals
- BirdNET internals
- Sender internals
- EventBus internals
"""

from __future__ import annotations

import json
import math
import time

from datetime import datetime
from datetime import timezone
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
        debug=None
    ):

        self.config_path = config_path
        self.config = self.load_config()

        if debug is None:
            self.debug = self.config.get("debug", True)
        else:
            self.debug = debug

        self.node_id = self.config.get("node_id")
        self.node_name = self.config.get("node_name")

        self.loop = MicrophoneLoop(
            recordings_root=self.config["recordings_root"],
            sample_rate=self.config["sample_rate"],
            channels=self.config["channels"],
            debug=self.debug
        )

        self.manager = MicrophoneManager(
            node_id=self.node_id,
            node_name=self.node_name,
            debug=self.debug
        )

        self.recycler = Recycler(
            recordings_root=self.config["recordings_root"],
            default_retention_days=self.config[
                "storage_retention_days"
            ],
            debug=self.debug
        )

        self.event_services = MicrophoneEventServices(
            event_bus=event_bus,
            debug=self.debug
        )

        self.pps_locked = False
        self.last_pps_state = {}
        self.last_pps_event_monotonic = None

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

        self.event_services.subscribe_pps_state(
            self.handle_pps_state
        )

        self.event_services.subscribe_tdoa_request(
            self.handle_tdoa_request
        )

        self.log("Subscriptions registered")

    # --------------------------------------------------
    # Event Helpers
    # --------------------------------------------------

    def get_payload(self, event):

        if not isinstance(event, dict):
            return {}

        payload = event.get("payload")

        if isinstance(payload, dict):
            merged = dict(event)
            merged.update(payload)
            return merged

        return event

    def get_first_available(self, source, keys, default=None):

        for key in keys:
            value = source.get(key)

            if value is not None:
                return value

        return default

    def get_utc_timestamp(self):

        return (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    # --------------------------------------------------
    # PPS State
    # --------------------------------------------------

    def handle_pps_state(self, event):

        payload = self.get_payload(event)

        pps_locked = self.get_first_available(
            payload,
            [
                "pps_locked",
                "pps_valid",
                "locked",
                "online",
                "enabled"
            ],
            default=False
        )

        state_label = str(
            payload.get("state", "")
        ).upper()

        if state_label in [
            "LOCKED",
            "ONLINE",
            "READY",
            "ENABLED"
        ]:
            pps_locked = True

        self.pps_locked = bool(pps_locked)

        self.last_pps_state = {
            "event_type": "PPS_STATE",
            "timestamp": self.get_first_available(
                payload,
                ["timestamp", "pps_timestamp"],
                default=self.get_utc_timestamp()
            ),
            "node_id": self.get_first_available(
                payload,
                ["node_id"],
                default=self.node_id
            ),
            "node_name": self.get_first_available(
                payload,
                ["node_name"],
                default=self.node_name
            ),
            "pps_locked": self.pps_locked,
            "pps_valid": self.pps_locked,
            "state": "LOCKED" if self.pps_locked else "UNLOCKED",
            "last_pps_utc": self.get_first_available(
                payload,
                [
                    "last_pps_utc",
                    "pps_utc",
                    "pps_time_utc",
                    "time_utc"
                ]
            ),
            "sequence": self.get_first_available(
                payload,
                ["sequence", "pps_sequence", "pulse_count"]
            )
        }

        self.last_pps_event_monotonic = time.monotonic()

        self.log(
            f"PPS state updated: {self.last_pps_state['state']}"
        )

    def get_pps_state_snapshot(self):

        if self.last_pps_state:
            return dict(self.last_pps_state)

        return {
            "event_type": "PPS_STATE",
            "node_id": self.node_id,
            "node_name": self.node_name,
            "pps_locked": self.pps_locked,
            "pps_valid": self.pps_locked,
            "state": "LOCKED" if self.pps_locked else "UNLOCKED"
        }

    # --------------------------------------------------
    # Recording Permission
    # --------------------------------------------------

    def recording_allowed(self, for_tdoa=False):

        require_pps = self.config.get(
            "require_pps_lock_for_tdoa"
            if for_tdoa
            else "require_pps_lock",
            False
        )

        if require_pps and not self.pps_locked:
            return False

        if self.config.get(
            "check_microphone_available_before_recording",
            False
        ):
            return self.loop.available()

        return True

    # --------------------------------------------------
    # PPS Alignment
    # --------------------------------------------------

    def wait_for_pps_boundary_if_available(self, request_payload):

        if not self.pps_locked:
            return "local_clock", None

        if not self.config.get(
            "align_tdoa_to_pps_boundary",
            True
        ):
            return "pps_locked_no_boundary_wait", None

        requested_epoch = self.get_first_available(
            request_payload,
            [
                "start_epoch",
                "start_epoch_utc",
                "start_time_epoch",
                "scheduled_start_epoch"
            ]
        )

        lead_seconds = float(
            self.config.get("tdoa_pps_lead_seconds", 1.0)
        )

        now = time.time()

        if requested_epoch is not None:
            try:
                target_epoch = float(requested_epoch)
            except Exception:
                target_epoch = math.ceil(now + lead_seconds)
        else:
            target_epoch = math.ceil(now + lead_seconds)

        wait_seconds = target_epoch - now

        if wait_seconds > 0:
            self.log(
                f"Waiting {wait_seconds:.3f}s for PPS-aligned TDOA start"
            )
            time.sleep(wait_seconds)

        scheduled_start_utc = (
            datetime.fromtimestamp(target_epoch, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

        return "pps_soft_boundary", scheduled_start_utc

    # --------------------------------------------------
    # Normal Recording
    # --------------------------------------------------

    def make_recording(self):

        if not self.recording_allowed(for_tdoa=False):
            self.log(
                "Recording skipped because recording is not allowed"
            )
            return None

        pps_state = self.get_pps_state_snapshot()
        sync_source = "pps_locked" if self.pps_locked else "local_clock"

        recording = self.loop.record(
            duration_sec=self.config["recording_duration_sec"],
            recording_type="recording",
            pps_state=pps_state,
            sync_source=sync_source
        )

        event = self.manager.build_recording_available_event(
            recording=recording,
            pps_state=pps_state,
            sync_source=sync_source
        )

        self.recording_index[event["recording_id"]] = event

        self.write_initial_metadata(event)

        self.event_services.publish_recording_available(event)

        self.log(
            f"Published RECORDING_AVAILABLE: {event['recording_id']}"
        )

        return event

    # --------------------------------------------------
    # TDOA Request
    # --------------------------------------------------

    def request_targets_this_node(self, request_payload):

        target_node_id = request_payload.get("target_node_id")
        target_nodes = request_payload.get("target_nodes")
        target = request_payload.get("target")

        if target_node_id in ["all", "broadcast"]:
            return True

        if self.node_id and target_node_id == self.node_id:
            return True

        if isinstance(target_nodes, list):
            return self.node_id in target_nodes

        if target in [None, "microphone", "node", "all", "broadcast"]:
            return True

        if self.node_id and target == self.node_id:
            return True

        return target_node_id is None and target_nodes is None

    def handle_tdoa_request(self, event):

        request_payload = self.get_payload(event)

        if not self.request_targets_this_node(request_payload):
            self.log("TDOA_REQUEST ignored for another node")
            return

        recording_id = self.get_first_available(
            request_payload,
            ["recording_id", "source_recording_id"]
        )

        pps_state = self.get_pps_state_snapshot()

        if recording_id and recording_id in self.recording_index:
            recording_event = self.recording_index[recording_id]

            tdoa_event = self.manager.build_tdoa_recording_event(
                recording=recording_event["payload"],
                request_payload=request_payload,
                pps_state=pps_state,
                sync_source=recording_event["payload"].get(
                    "sync_source",
                    "local_clock"
                )
            )

            self.event_services.publish_tdoa_recording(tdoa_event)

            self.log(
                f"Published TDOA_RECORDING pointer: {recording_id}"
            )

            return

        if not self.recording_allowed(for_tdoa=True):
            self.log(
                "TDOA_REQUEST received but TDOA recording is not allowed"
            )
            return

        duration_sec = self.get_first_available(
            request_payload,
            ["duration_sec", "tdoa_duration_sec"],
            default=self.config["tdoa_recording_duration_sec"]
        )

        sync_source, scheduled_start_utc = (
            self.wait_for_pps_boundary_if_available(
                request_payload
            )
        )

        recording = self.loop.record(
            duration_sec=duration_sec,
            recording_type="tdoa",
            request_id=self.get_first_available(
                request_payload,
                ["tdoa_request_id", "request_id", "event_id"]
            ),
            pps_state=pps_state,
            sync_source=sync_source,
            scheduled_start_utc=scheduled_start_utc
        )

        tdoa_event = self.manager.build_tdoa_recording_event(
            recording=recording,
            request_payload=request_payload,
            pps_state=pps_state,
            sync_source=sync_source
        )

        self.recording_index[tdoa_event["recording_id"]] = tdoa_event

        self.write_initial_metadata(tdoa_event)

        self.event_services.publish_tdoa_recording(tdoa_event)

        self.log(
            f"Published TDOA_RECORDING: {tdoa_event['recording_id']}"
        )

    # --------------------------------------------------
    # Metadata
    # --------------------------------------------------

    def write_initial_metadata(self, event):

        payload = event.get("payload", event)

        metadata = {
            "event_type": event.get("event_type"),
            "recording_id": payload["recording_id"],
            "recording_utc": payload.get("recording_utc"),
            "recording_epoch": payload.get("recording_epoch"),
            "recording_path": payload.get("recording_path"),
            "wav_path": payload.get("wav_path"),
            "sample_rate": payload.get("sample_rate"),
            "channels": payload.get("channels"),
            "duration_sec": payload.get("duration_sec"),
            "recording_type": payload.get("recording_type"),
            "sync_source": payload.get("sync_source"),
            "pps_locked": payload.get("pps_locked"),
            "pps_state": payload.get("pps_state", {}),
            "tdoa_request_id": payload.get("tdoa_request_id"),
            "preserve": False,
            "species_detected": False,
            "retention_days": self.config[
                "storage_retention_days"
            ]
        }

        self.save_metadata(
            payload["metadata_path"],
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
