# ============================================================
# microphone_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Microphone
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own the microphone subsystem workflow. Coordinate microphone recording,
#   PPS/GPS state awareness, synchronized recording windows, TDOA recording
#   requests, metadata writing, and recording cleanup.
#
# Expected config source:
#   microphone_config.json
#
# Expected config section:
#   Full file
#
# Does:
#   - Load microphone configuration
#   - Resolve active microphone type and active microphone settings
#   - Own MicrophoneLoop
#   - Own MicrophoneManager
#   - Own Recycler
#   - Own MicrophoneEventServices
#   - Subscribe to PPS_STATE events through MicrophoneEventServices
#   - Subscribe to GPS_STATE events through MicrophoneEventServices
#   - Subscribe to TDOA_REQUEST events through MicrophoneEventServices
#   - Track PPS lock state
#   - Track GPS lock state
#   - Control normal recording timing
#   - Align normal recordings to configured PPS windows when available
#   - Control TDOA request recording
#   - Align TDOA recordings to requested PPS boundaries when available
#   - Publish RECORDING_AVAILABLE events through MicrophoneEventServices
#   - Publish TDOA_RECORDING events through MicrophoneEventServices
#   - Publish MICROPHONE_SYNCED events through MicrophoneEventServices
#   - Write initial recording metadata
#   - Control recycler timing
#
# Does NOT:
#   - Own audio hardware internals
#   - Record audio directly
#   - Build WAV files directly
#   - Publish directly to the event bus
#   - Subscribe directly to the event bus
#   - Own BirdNET analysis
#   - Own sender transport
#   - Own platform registry state
#   - Own node registration
#
# Owner:
#   node_main.py
#
# ============================================================

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
            recording_engine=self.config.get(
                "recording_engine",
                "scheduled_start_stop"
            ),
            continuous_capture_config=self.config.get(
                "continuous_capture",
                {}
            ),
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

        try:

            if self.microphone_enabled:

                self.loop.start_continuous()

            self.run()

        finally:

            self.running = False
            self.loop.stop_continuous()

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

        if recording.get(
            "recording_engine"
        ) == "continuous_pps":

            self.consecutive_synced_windows = 0

            self.log(
                (
                    "MICROPHONE_SYNCED withheld: "
                    "continuous sample clock has not yet "
                    "been fitted to PPS"
                )
            )

            return None

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
    
    def attach_timing_quality(self, recording):

        if not isinstance(recording, dict):
            return recording

        status_events = recording.get(
            "stream_status_events",
            []
        )

        if not isinstance(status_events, list):
            status_events = []

        timing_issues = []

        for status_event in status_events:

            if isinstance(status_event, dict):
                status_text = str(
                    status_event.get(
                        "status",
                        ""
                    )
                ).strip().lower()

            else:
                status_text = str(
                    status_event
                ).strip().lower()

            if not status_text:
                continue

            if "overflow" in status_text:

                issue = "input_overflow"

            elif "underflow" in status_text:

                issue = "input_underflow"

            else:

                issue = "portaudio_status"

            if issue not in timing_issues:
                timing_issues.append(issue)

        raw_timing_quality = (
            "DEGRADED"
            if timing_issues
            else
            "CLEAN"
        )

        recording_engine = str(
            recording.get(
                "recording_engine",
                ""
            )
        )

        clock_fit_eligible = bool(
            recording_engine == "continuous_pps"
            and
            not timing_issues
        )

        corrected_tdoa_eligible = bool(
            clock_fit_eligible
            and
            recording.get("timing_state")
            ==
            "pps_clock_fitted"
        )

        recording["raw_timing_quality"] = (
            raw_timing_quality
        )

        recording["timing_issues"] = (
            timing_issues
        )

        recording["clock_fit_eligible"] = (
            clock_fit_eligible
        )

        recording["corrected_tdoa_eligible"] = (
            corrected_tdoa_eligible
        )

        if timing_issues:

            self.log(
                (
                    "Recording timing degraded: "
                    f"recording_id="
                    f"{recording.get('recording_id')} "
                    f"issues={timing_issues}"
                )
            )

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
    
    def uses_completed_boundary_windows(self):

        return bool(
            self.loop.recording_engine
            ==
            "continuous_pps"
            and
            self.config.get(
                "align_recordings_to_pps_boundary",
                True
            )
        )
    
    def make_completed_boundary_recording(
        self,
        sync_source,
        boundary_epoch,
        boundary_utc,
        boundary_second,
        pps_state
    ):

        operation_started_monotonic = time.monotonic()

        boundary_snapshot = (
            self.loop.snapshot_stream_position()
        )

        core_duration_sec = (
            self.get_min_window_spacing_seconds()
        )

        window_start_epoch = (
            float(boundary_epoch)
            -
            core_duration_sec
        )

        window_start_utc = (
            self.epoch_to_utc_timestamp(
                window_start_epoch
            )
        )

        window_start_second = (
            datetime.fromtimestamp(
                window_start_epoch,
                timezone.utc
            ).second
        )

        try:

            window = (
                self.loop
                .read_guarded_window_from_boundary(
                    boundary_snapshot=(
                        boundary_snapshot
                    ),
                    core_duration_sec=(
                        core_duration_sec
                    )
                )
            )

        except RuntimeError as error:

            self.log(
                (
                    "Completed boundary window skipped: "
                    f"{error}"
                )
            )

            return None

        paths = self.loop.build_recording_path(
            recording_type="recording",
            scheduled_start_epoch=(
                window_start_epoch
            ),
            scheduled_start_utc=(
                window_start_utc
            )
        )

        file_result = (
            self.loop.write_boundary_window_files(
                paths=paths,
                window=window
            )
        )

        operation_finished_monotonic = (
            time.monotonic()
        )

        boundary_snapshot_epoch = (
            boundary_snapshot[
                "snapshot_realtime_ns"
            ]
            /
            1e9
        )

        boundary_snapshot_error_ms = (
            boundary_snapshot_epoch
            -
            float(boundary_epoch)
        ) * 1000.0

        self.log(
            (
                "Completed boundary window written: "
                f"core={window_start_utc}"
                f"->{boundary_utc} "
                f"core_samples="
                f"{window['core_start_sample']}:"
                f"{window['core_end_sample_exclusive']} "
                f"guarded_samples="
                f"{window['guarded_start_sample']}:"
                f"{window['guarded_end_sample_exclusive']}"
            )
        )

        return {
            "recording_id": paths[
                "recording_id"
            ],

            "recording_utc": window_start_utc,
            "recording_epoch": window_start_epoch,

            "scheduled_start_utc": (
                window_start_utc
            ),
            "scheduled_start_epoch": (
                window_start_epoch
            ),

            "window_utc": window_start_utc,
            "window_epoch": window_start_epoch,
            "window_second": window_start_second,

            "boundary_utc": boundary_utc,
            "boundary_epoch": boundary_epoch,
            "boundary_second": boundary_second,

            "wav_path": file_result[
                "wav_path"
            ],
            "guarded_wav_path": file_result[
                "guarded_wav_path"
            ],
            "metadata_path": paths[
                "metadata_path"
            ],
            "spectrogram_path": None,

            "sample_rate": self.loop.sample_rate,
            "channels": self.loop.channels,

            "duration_sec": file_result[
                "core_duration_sec"
            ],
            "frame_count": file_result[
                "core_frame_count"
            ],

            "guarded_duration_sec": file_result[
                "guarded_duration_sec"
            ],
            "guarded_frame_count": file_result[
                "guarded_frame_count"
            ],

            "recording_type": "recording",
            "request_id": None,

            "sync_source": sync_source,
            "pps_state": pps_state or {},

            "started_monotonic": (
                operation_started_monotonic
            ),
            "finished_monotonic": (
                operation_finished_monotonic
            ),
            "actual_duration_sec": (
                operation_finished_monotonic
                -
                operation_started_monotonic
            ),

            "start_error_ms": None,
            "boundary_snapshot_error_ms": (
                boundary_snapshot_error_ms
            ),

            "device": self.config.get(
                "device"
            ),

            "recording_engine": (
                "continuous_pps"
            ),
            "continuous_stream": True,

            "timing_state": (
                "boundary_candidate_unmodeled"
            ),

            "boundary_snapshot": (
                boundary_snapshot
            ),
            "boundary_sample": window[
                "boundary_sample"
            ],

            "stream_start_sample": window[
                "core_start_sample"
            ],
            "stream_end_sample_exclusive": (
                window[
                    "core_end_sample_exclusive"
                ]
            ),

            "guarded_stream_start_sample": (
                window[
                    "guarded_start_sample"
                ]
            ),
            "guarded_stream_end_sample_exclusive": (
                window[
                    "guarded_end_sample_exclusive"
                ]
            ),

            "pre_roll_frames": window[
                "pre_roll_frames"
            ],
            "post_roll_frames": window[
                "post_roll_frames"
            ],
            "pre_roll_seconds": window[
                "pre_roll_seconds"
            ],
            "post_roll_seconds": window[
                "post_roll_seconds"
            ],

            "stream_status_events": window[
                "stream_status_events"
            ],
            "stream_status_event_count": (
                window[
                    "stream_status_event_count"
                ]
            )
        }
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

        if self.uses_completed_boundary_windows():

            recording = (
                self.make_completed_boundary_recording(
                    sync_source=sync_source,
                    boundary_epoch=(
                        scheduled_start_epoch
                    ),
                    boundary_utc=(
                        scheduled_start_utc
                    ),
                    boundary_second=window_second,
                    pps_state=pps_state
                )
            )

        else:

            recording = self.loop.record(
                duration_sec=(
                    self.get_effective_recording_duration_sec()
                ),
                recording_type="recording",
                pps_state=pps_state,
                sync_source=sync_source,
                scheduled_start_epoch=(
                    scheduled_start_epoch
                ),
                scheduled_start_utc=(
                    scheduled_start_utc
                ),
                window_second=window_second
            )

        if recording is None:
            self.log(
                "Recording skipped because microphone loop returned None"
            )
            return None

        recording = self.attach_recording_context(
            recording
        )

        recording = self.attach_timing_quality(
            recording
        )

        self.last_recorded_window_epoch = (
            scheduled_start_epoch
        )

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

    def get_tdoa_request_item_for_this_node(self, request_payload):

        request_items = request_payload.get("request_items")

        if not isinstance(request_items, dict):
            return {}

        node_item = request_items.get(self.node_id)

        if isinstance(node_item, dict):
            return dict(node_item)

        return {}

    def merge_tdoa_request_item(self, request_payload):

        merged_payload = dict(request_payload)

        node_item = self.get_tdoa_request_item_for_this_node(
            request_payload
        )

        for key, value in node_item.items():
            if value is not None:
                merged_payload[key] = value

        return merged_payload

    def handle_tdoa_request(self, event):

        request_payload = self.get_payload(event)

        if not self.request_targets_this_node(request_payload):
            self.log("TDOA_REQUEST ignored for another node")
            return

        request_payload = self.merge_tdoa_request_item(
            request_payload
        )

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

        recording = self.attach_recording_context(
            recording
        )

        recording = self.attach_timing_quality(
            recording
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
            "tdoa_request_id": payload.get(
                "tdoa_request_id"
            ),

            "guarded_wav_path": payload.get(
                "guarded_wav_path"
            ),

            "frame_count": payload.get(
                "frame_count"
            ),

            "guarded_duration_sec": payload.get(
                "guarded_duration_sec"
            ),

            "guarded_frame_count": payload.get(
                "guarded_frame_count"
            ),

            "timing_quality": {
                "schema_version": 1,

                "raw_timing_quality": payload.get(
                    "raw_timing_quality",
                    "UNKNOWN"
                ),

                "timing_issues": payload.get(
                    "timing_issues",
                    []
                ),

                "clock_fit_eligible": bool(
                    payload.get(
                        "clock_fit_eligible",
                        False
                    )
                ),

                "corrected_tdoa_eligible": bool(
                    payload.get(
                        "corrected_tdoa_eligible",
                        False
                    )
                )
            },

            "timing_evidence": {
                "schema_version": 1,

                "recording_engine": payload.get(
                    "recording_engine"
                ),

                "continuous_stream": payload.get(
                    "continuous_stream",
                    False
                ),

                "timing_state": payload.get(
                    "timing_state"
                ),

                "boundary": {
                    "utc": payload.get(
                        "boundary_utc"
                    ),

                    "epoch": payload.get(
                        "boundary_epoch"
                    ),

                    "second": payload.get(
                        "boundary_second"
                    ),

                    "sample": payload.get(
                        "boundary_sample"
                    ),

                    "snapshot_error_ms": payload.get(
                        "boundary_snapshot_error_ms"
                    ),

                    "snapshot": payload.get(
                        "boundary_snapshot"
                    )
                },

                "core_sample_range": {
                    "start_sample": payload.get(
                        "stream_start_sample"
                    ),

                    "end_sample_exclusive": payload.get(
                        "stream_end_sample_exclusive"
                    ),

                    "frame_count": payload.get(
                        "frame_count"
                    ),

                    "duration_sec": payload.get(
                        "duration_sec"
                    )
                },

                "guarded_sample_range": {
                    "start_sample": payload.get(
                        "guarded_stream_start_sample"
                    ),

                    "end_sample_exclusive": payload.get(
                        "guarded_stream_end_sample_exclusive"
                    ),

                    "frame_count": payload.get(
                        "guarded_frame_count"
                    ),

                    "duration_sec": payload.get(
                        "guarded_duration_sec"
                    )
                },

                "guards": {
                    "pre_roll_frames": payload.get(
                        "pre_roll_frames"
                    ),

                    "post_roll_frames": payload.get(
                        "post_roll_frames"
                    ),

                    "pre_roll_seconds": payload.get(
                        "pre_roll_seconds"
                    ),

                    "post_roll_seconds": payload.get(
                        "post_roll_seconds"
                    )
                },

                "stream_status_events": payload.get(
                    "stream_status_events",
                    []
                ),

                "stream_status_event_count": payload.get(
                    "stream_status_event_count",
                    0
                )
            },

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
