"""
microphone_dispatcher.py

Responsibilities:
- Load microphone configuration
- Own microphone loop
- Own microphone manager
- Own recycler
- Own microphone event services
- Track PPS_STATE
- Track GPS_STATE
- Control normal recording timing
- Control TDOA request recording
- Control recycler timing

Canonical microphone event contract:
- Subscribes: PPS_STATE, GPS_STATE, TDOA_REQUEST
- Publishes: RECORDING_AVAILABLE, TDOA_RECORDING, MICROPHONE_SYNCED

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
        self.microphone_type = self.get_active_microphone_type()
        self.active_microphone_config = self.get_active_microphone_config()
        self.microphone_enabled = self.microphone_type != "none"

        self.apply_active_microphone_config()

        self.loop = MicrophoneLoop(
            recordings_root=self.config["recordings_root"],
            sample_rate=self.config["sample_rate"],
            channels=self.config["channels"],
            device=self.config.get("device"),
            spectrogram_config=self.get_spectrogram_config(),
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

        self.gps_locked = False
        self.last_gps_state = {}

        self.running = False
        self.last_recycler_time = 0

        self.recording_index = {}
        self.last_recorded_window_epoch = None
        self.consecutive_synced_windows = 0
        self._duration_clamp_logged = False

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

    def get_active_microphone_type(self):

        microphone_type = str(
            self.config.get("microphone_type", "USB")
        ).strip()

        if microphone_type.upper() in {"USB", "SPH0645"}:
            return microphone_type.upper()

        if microphone_type.lower() in {"none", "off", "disabled"}:
            return "none"

        return "USB"

    def get_active_microphone_config(self):

        microphone_sections = self.config.get("microphones", {})

        if not isinstance(microphone_sections, dict):
            microphone_sections = {}

        active = microphone_sections.get(self.microphone_type)

        if not isinstance(active, dict):
            active = {}

        return active

    def apply_active_microphone_config(self):

        if self.microphone_type == "none":
            self.config["device"] = None
            return

        self.config["device"] = self.active_microphone_config.get(
            "device",
            self.config.get("device"),
        )

        self.config["sample_rate"] = int(
            self.active_microphone_config.get(
                "sample_rate",
                self.config.get("sample_rate", 48000),
            )
        )

        self.config["channels"] = int(
            self.active_microphone_config.get(
                "channels",
                self.config.get("channels", 1),
            )
        )

    def get_spectrogram_config(self):

        spectrogram_config = self.config.get("spectrogram", {})

        if not isinstance(spectrogram_config, dict):
            spectrogram_config = {}

        if "enabled" not in spectrogram_config:
            spectrogram_config["enabled"] = bool(
                self.config.get("generate_spectrogram", False)
            )

        return spectrogram_config

    # --------------------------------------------------
    # Startup
    # --------------------------------------------------

    def start(self):

        self.log(
            f"Starting microphone subsystem type={self.microphone_type} "
            f"device={self.config.get('device')}"
        )
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

        self.event_services.subscribe_gps_state(
            self.handle_gps_state
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

    def epoch_to_utc_timestamp(self, epoch):

        return (
            datetime.fromtimestamp(
                float(epoch),
                timezone.utc
            )
            .replace(microsecond=0)
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
                "pps_online",
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

        snapshot = payload.get("snapshot", {})
        if not isinstance(snapshot, dict):
            snapshot = {}

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
            "pps_online": self.pps_locked,
            "state": "LOCKED" if self.pps_locked else "LOST",
            "last_pps_utc": self.get_first_available(
                payload,
                [
                    "last_pps_utc",
                    "pps_utc",
                    "pps_time_utc",
                    "time_utc"
                ]
            ),
            "pps_seq": self.get_first_available(
                payload,
                ["pps_seq", "sequence", "pps_sequence", "pulse_count"],
                default=snapshot.get("pps_seq")
            ),
            "last_pps_kernel_time": self.get_first_available(
                payload,
                ["last_pps_kernel_time"],
                default=snapshot.get("last_pps_kernel_time")
            ),
            "snapshot": snapshot
        }

        self.last_pps_event_monotonic = time.monotonic()

        self.log(
            f"PPS state updated: {self.last_pps_state['state']}"
        )

    # --------------------------------------------------
    # GPS State
    # --------------------------------------------------

    def handle_gps_state(self, event):

        payload = self.get_payload(event)

        gps_locked = self.get_first_available(
            payload,
            [
                "gps_locked",
                "gps_online",
                "fix_valid",
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
            gps_locked = True

        self.gps_locked = bool(gps_locked)

        snapshot = payload.get("snapshot", {})
        if not isinstance(snapshot, dict):
            snapshot = {}

        self.last_gps_state = {
            "event_type": "GPS_STATE",
            "timestamp": self.get_first_available(
                payload,
                ["timestamp"],
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
            "gps_locked": self.gps_locked,
            "gps_online": self.gps_locked,
            "fix_valid": self.gps_locked,
            "state": "LOCKED" if self.gps_locked else "LOST",
            "snapshot": snapshot
        }

        self.log(
            f"GPS state updated: {self.last_gps_state['state']}"
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
            "pps_online": self.pps_locked,
            "state": "LOCKED" if self.pps_locked else "LOST"
        }

    # --------------------------------------------------
    # Recording Permission
    # --------------------------------------------------

    def recording_allowed(self, for_tdoa=False):

        if not self.microphone_enabled:
            return False

        require_pps = self.config.get(
            "require_pps_lock_for_tdoa"
            if for_tdoa
            else "require_pps_lock",
            False
        )

        if require_pps and not self.pps_locked:
            return False

        require_gps = self.config.get(
            "require_gps_lock_for_tdoa"
            if for_tdoa
            else "require_gps_lock",
            require_pps
        )

        if require_gps and not self.gps_locked:
            return False

        if self.config.get(
            "check_microphone_available_before_recording",
            False
        ):
            return self.loop.available()

        return True

    # --------------------------------------------------
    # Window Scheduling
    # --------------------------------------------------

    def get_recording_window_seconds(self):

        configured = self.config.get(
            "recording_window_seconds",
            [0, 15, 30, 45]
        )

        seconds = []

        for value in configured:
            try:
                second = int(value)
            except Exception:
                continue

            if 0 <= second <= 59:
                seconds.append(second)

        if not seconds:
            seconds = [0, 15, 30, 45]

        return sorted(set(seconds))

    def get_next_window_epoch(self, now_epoch=None):

        if now_epoch is None:
            now_epoch = time.time()

        lead_seconds = float(
            self.config.get(
                "microphone_pps_lead_seconds",
                0.05
            )
        )

        search_epoch = now_epoch + lead_seconds
        base_epoch = int(math.floor(search_epoch))
        window_seconds = self.get_recording_window_seconds()

        for offset in range(0, 125):
            candidate_epoch = base_epoch + offset
            candidate_dt = datetime.fromtimestamp(
                candidate_epoch,
                timezone.utc
            )

            if candidate_dt.second not in window_seconds:
                continue

            if candidate_epoch <= search_epoch:
                continue

            if candidate_epoch == self.last_recorded_window_epoch:
                continue

            return candidate_epoch

        return None

    def wait_for_microphone_sync_window(self):

        if not self.recording_allowed(for_tdoa=False):
            return "not_locked", None, None, None

        if not self.config.get(
            "align_recordings_to_pps_boundary",
            True
        ):
            now_epoch = time.time()
            now_dt = datetime.fromtimestamp(
                now_epoch,
                timezone.utc
            )

            return (
                "local_clock",
                now_epoch,
                self.epoch_to_utc_timestamp(now_epoch),
                now_dt.second
            )

        target_epoch = self.get_next_window_epoch()

        if target_epoch is None:
            return "no_window", None, None, None

        while self.running:
            if not self.recording_allowed(for_tdoa=False):
                return "lost_lock", None, None, None

            wait_seconds = target_epoch - time.time()

            if wait_seconds <= 0:
                break

            time.sleep(
                min(wait_seconds, 0.05)
            )

        if not self.running:
            return "stopped", None, None, None

        window_dt = datetime.fromtimestamp(
            target_epoch,
            timezone.utc
        )

        scheduled_start_utc = self.epoch_to_utc_timestamp(
            target_epoch
        )

        return (
            "pps_quarter_minute_window",
            target_epoch,
            scheduled_start_utc,
            window_dt.second
        )

    # --------------------------------------------------
    # TDOA Alignment
    # --------------------------------------------------

    def wait_for_pps_boundary_if_available(self, request_payload):

        if not self.recording_allowed(for_tdoa=True):
            return "not_locked", None, None, None

        if not self.config.get(
            "align_tdoa_to_pps_boundary",
            True
        ):
            now_epoch = time.time()
            now_dt = datetime.fromtimestamp(
                now_epoch,
                timezone.utc
            )

            return (
                "local_clock",
                now_epoch,
                self.epoch_to_utc_timestamp(now_epoch),
                now_dt.second
            )

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

        while self.running:
            if not self.recording_allowed(for_tdoa=True):
                return "lost_lock", None, None, None

            wait_seconds = target_epoch - time.time()

            if wait_seconds <= 0:
                break

            time.sleep(
                min(wait_seconds, 0.05)
            )

        if not self.running:
            return "stopped", None, None, None

        scheduled_start_utc = self.epoch_to_utc_timestamp(
            target_epoch
        )

        window_second = datetime.fromtimestamp(
            target_epoch,
            timezone.utc
        ).second

        return (
            "pps_tdoa_boundary",
            target_epoch,
            scheduled_start_utc,
            window_second
        )

    # --------------------------------------------------
    # Sync Scoring
    # --------------------------------------------------

    def calculate_microphone_sync_error_ms(
        self,
        recording,
        scheduled_start_epoch
    ):

        if scheduled_start_epoch is None:
            return None

        recording_epoch = recording.get("recording_epoch")

        if recording_epoch is None:
            return None

        try:
            return abs(
                float(recording_epoch) - float(scheduled_start_epoch)
            ) * 1000.0

        except Exception:
            return None

    def microphone_sync_passed(
        self,
        sync_source,
        sync_error_ms
    ):

        if not self.pps_locked:
            return False

        if not self.gps_locked:
            return False

        if sync_source not in {
            "pps_quarter_minute_window",
            "pps_tdoa_boundary"
        }:
            return False

        if sync_error_ms is None:
            return False

        sync_window_ms = float(
            self.config.get(
                "microphone_sync_window_ms",
                250.0
            )
        )

        return sync_error_ms <= sync_window_ms

    def maybe_publish_microphone_synced(
        self,
        recording,
        pps_state,
        sync_source,
        scheduled_start_epoch=None,
        scheduled_start_utc=None
    ):

        sync_error_ms = self.calculate_microphone_sync_error_ms(
            recording=recording,
            scheduled_start_epoch=scheduled_start_epoch
        )

        sync_window_ms = float(
            self.config.get(
                "microphone_sync_window_ms",
                250.0
            )
        )

        if not self.microphone_sync_passed(
            sync_source=sync_source,
            sync_error_ms=sync_error_ms
        ):
            self.consecutive_synced_windows = 0
            return None

        self.consecutive_synced_windows += 1

        event = self.manager.build_microphone_synced_event(
            recording=recording,
            pps_state=pps_state,
            sync_source=sync_source,
            scheduled_start_epoch=scheduled_start_epoch,
            scheduled_start_utc=scheduled_start_utc,
            sync_error_ms=sync_error_ms,
            sync_window_ms=sync_window_ms,
            consecutive_synced_windows=self.consecutive_synced_windows
        )

        self.event_services.publish_microphone_synced(event)

        self.log(
            f"Published MICROPHONE_SYNCED: {event['recording_id']} "
            f"sync_error_ms={sync_error_ms:.3f}"
        )

        return event

    def attach_recording_context(self, recording):

        if not isinstance(recording, dict):
            return recording

        recording["microphone_type"] = self.microphone_type
        recording["device"] = self.config.get("device")

        return recording

    # --------------------------------------------------
    # Recording Duration Budget
    # --------------------------------------------------

    def get_min_window_spacing_seconds(self):

        window_seconds = self.get_recording_window_seconds()

        if len(window_seconds) < 2:

            return float(
                self.config.get(
                    "recording_interval_sec",
                    15.0
                )
            )

        gaps = []

        for index, second in enumerate(window_seconds):

            next_second = window_seconds[
                (index + 1) % len(window_seconds)
            ]

            gap = next_second - second

            if gap <= 0:

                gap += 60

            gaps.append(
                gap
            )

        return float(
            min(gaps)
        )

    def get_effective_recording_duration_sec(self):

        try:

            configured_duration = float(
                self.config.get(
                    "recording_duration_sec",
                    14.0
                )
            )

        except Exception:

            configured_duration = 14.0

        if not self.config.get(
            "align_recordings_to_pps_boundary",
            True
        ):

            return configured_duration

        try:

            guard_seconds = float(
                self.config.get(
                    "recording_guard_seconds",
                    1.0
                )
            )

        except Exception:

            guard_seconds = 1.0

        min_spacing = self.get_min_window_spacing_seconds()
        max_duration = max(
            1.0,
            min_spacing - max(0.0, guard_seconds)
        )

        if configured_duration > max_duration:

            if not self._duration_clamp_logged:

                self.log(
                    (
                        "Recording duration clamped to protect timing: "
                        f"configured={configured_duration:.3f}s "
                        f"effective={max_duration:.3f}s "
                        f"window_spacing={min_spacing:.3f}s "
                        f"guard={guard_seconds:.3f}s"
                    )
                )

                self._duration_clamp_logged = True

            return max_duration

        return configured_duration

    # --------------------------------------------------
    # Normal Recording
    # --------------------------------------------------

    def make_recording(self):

        if not self.recording_allowed(for_tdoa=False):
            self.log(
                "Recording skipped because PPS/GPS lock is not available"
            )
            return None

        (
            sync_source,
            scheduled_start_epoch,
            scheduled_start_utc,
            window_second
        ) = self.wait_for_microphone_sync_window()

        if scheduled_start_epoch is None:
            self.log(
                "Recording skipped because no synchronized window was available"
            )
            return None

        pps_state = self.get_pps_state_snapshot()

        recording = self.loop.record(
            duration_sec=self.get_effective_recording_duration_sec(),
            recording_type="recording",
            pps_state=pps_state,
            sync_source=sync_source,
            scheduled_start_epoch=scheduled_start_epoch,
            scheduled_start_utc=scheduled_start_utc,
            window_second=window_second
        )

        if recording is None:
            self.log(
                "Recording skipped because microphone loop returned None"
            )
            return None

        recording = self.attach_recording_context(recording)
        self.last_recorded_window_epoch = scheduled_start_epoch

        event = self.manager.build_recording_available_event(
            recording=recording,
            pps_state=pps_state,
            sync_source=sync_source
        )

        self.recording_index[event["recording_id"]] = event
        self.write_initial_metadata(event)
        self.event_services.publish_recording_available(event)

        self.maybe_publish_microphone_synced(
            recording=recording,
            pps_state=pps_state,
            sync_source=sync_source,
            scheduled_start_epoch=scheduled_start_epoch,
            scheduled_start_utc=scheduled_start_utc
        )

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
                "TDOA_REQUEST received but PPS/GPS lock is not available"
            )
            return

        duration_sec = self.get_first_available(
            request_payload,
            ["duration_sec", "tdoa_duration_sec"],
            default=self.config["tdoa_recording_duration_sec"]
        )

        (
            sync_source,
            scheduled_start_epoch,
            scheduled_start_utc,
            window_second
        ) = self.wait_for_pps_boundary_if_available(
            request_payload
        )

        if scheduled_start_epoch is None:
            self.log(
                "TDOA_REQUEST skipped because no synchronized start was available"
            )
            return

        recording = self.loop.record(
            duration_sec=duration_sec,
            recording_type="tdoa",
            request_id=self.get_first_available(
                request_payload,
                ["tdoa_request_id", "request_id", "event_id"]
            ),
            pps_state=pps_state,
            sync_source=sync_source,
            scheduled_start_epoch=scheduled_start_epoch,
            scheduled_start_utc=scheduled_start_utc,
            window_second=window_second
        )

        if recording is None:
            self.log("TDOA recording failed")
            return

        recording = self.attach_recording_context(recording)

        tdoa_event = self.manager.build_tdoa_recording_event(
            recording=recording,
            request_payload=request_payload,
            pps_state=pps_state,
            sync_source=sync_source
        )

        self.recording_index[tdoa_event["recording_id"]] = tdoa_event
        self.write_initial_metadata(tdoa_event)
        self.event_services.publish_tdoa_recording(tdoa_event)

        self.maybe_publish_microphone_synced(
            recording=recording,
            pps_state=pps_state,
            sync_source=sync_source,
            scheduled_start_epoch=scheduled_start_epoch,
            scheduled_start_utc=scheduled_start_utc
        )

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
            "scheduled_start_utc": payload.get("scheduled_start_utc"),
            "scheduled_start_epoch": payload.get("scheduled_start_epoch"),
            "window_utc": payload.get("window_utc"),
            "window_epoch": payload.get("window_epoch"),
            "window_second": payload.get("window_second"),
            "recording_path": payload.get("recording_path"),
            "wav_path": payload.get("wav_path"),
            "sample_rate": payload.get("sample_rate"),
            "channels": payload.get("channels"),
            "duration_sec": payload.get("duration_sec"),
            "recording_type": payload.get("recording_type"),
            "sync_source": payload.get("sync_source"),
            "start_error_ms": payload.get("start_error_ms"),
            "actual_duration_sec": payload.get("actual_duration_sec"),
            "device": payload.get("device"),
            "microphone_type": payload.get("microphone_type"),
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
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        with open(metadata_path, "w") as file:
            json.dump(metadata, file, indent=4)

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

        self.last_recycler_time = time.time()

        while self.running:
            now = time.time()

            recycler_interval = self.config[
                "recycler_interval_sec"
            ]

            if self.recording_allowed(for_tdoa=False):
                self.make_recording()
            else:
                self.log(
                    "Waiting for PPS/GPS lock before recording"
                )
                time.sleep(1)

            now = time.time()

            if now - self.last_recycler_time >= recycler_interval:
                self.run_recycler()
                self.last_recycler_time = now
