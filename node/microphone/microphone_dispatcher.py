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
#   - Own PPSAnchorJournal
#   - Subscribe to PPS_STATE events through MicrophoneEventServices
#   - Subscribe to PPS_EDGE events through MicrophoneEventServices
#   - Build local PPS/sample lookup records without declaring sync
#   - Persist finalized PPS/sample anchor evidence without declaring sync
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

import copy
import json
import math
import threading
import time

from datetime import datetime
from datetime import timezone
from pathlib import Path
from queue import Empty
from queue import Full
from queue import Queue

from microphone.microphone_loop import MicrophoneLoop
from microphone.microphone_manager import MicrophoneManager
from microphone.microphone_event_services import MicrophoneEventServices
from microphone.pps_anchor_journal import PPSAnchorJournal
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

        self.pps_anchor_journal = PPSAnchorJournal(
            recordings_root=self.config["recordings_root"],
            node_id=self.node_id,
            debug=self.debug
        )

        self.pps_locked = False
        self.last_pps_state = {}
        self.last_pps_event_monotonic = None

        # Local PPS/sample lookup evidence. These records are not clock
        # fits and are not published. Finalized records are persisted
        # asynchronously by PPSAnchorJournal.
        self.latest_pps_sample_anchor = None
        self.pps_anchor_attempt_count = 0
        self.pps_anchor_accepted_count = 0
        self.pps_anchor_rejected_count = 0

        # PPS edges arrive before PortAudio necessarily delivers the
        # callback block following the edge. Keep the event callback quick
        # and resolve the sample position from a bounded dispatcher-owned
        # queue after callback evidence becomes available.
        self.pps_pending_queue_capacity = 4
        self.pps_resolution_timeout_seconds = 0.25
        self.pps_resolution_max_attempts = 16
        self.pps_resolution_wait_slice_seconds = 0.05

        self._pending_pps_edges = Queue(
            maxsize=self.pps_pending_queue_capacity
        )
        self._pps_resolver_stop_event = threading.Event()
        self._pps_resolver_thread = None
        self._pps_anchor_lock = threading.Lock()

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

            self.pps_anchor_journal.start()
            self.start_pps_anchor_resolver()
            self.run()

        finally:

            self.running = False
            self.stop_pps_anchor_resolver()
            self.pps_anchor_journal.stop()
            self.loop.stop_continuous()

    def stop(self):

        self.log("Stopping microphone subsystem")
        self.running = False
        self._pps_resolver_stop_event.set()

    def start_pps_anchor_resolver(self):

        thread = self._pps_resolver_thread

        if thread is not None and thread.is_alive():
            return

        self._pps_resolver_stop_event.clear()

        self._pps_resolver_thread = threading.Thread(
            target=self._pps_anchor_resolver_worker,
            name="MicrophonePPSResolver",
            daemon=True
        )

        self._pps_resolver_thread.start()

        self.log(
            (
                "PPS anchor resolver started: "
                f"queue_capacity={self.pps_pending_queue_capacity} "
                f"timeout_seconds="
                f"{self.pps_resolution_timeout_seconds:.3f}"
            )
        )

    def stop_pps_anchor_resolver(self):

        self._pps_resolver_stop_event.set()

        thread = self._pps_resolver_thread

        if thread is None:
            return

        thread.join(timeout=2.0)

        if thread.is_alive():
            self.log(
                "PPS anchor resolver did not stop within 2 seconds"
            )
        else:
            self.log("PPS anchor resolver stopped")

        self._pps_resolver_thread = None


    # --------------------------------------------------
    # Subscriptions
    # --------------------------------------------------

    def register_subscriptions(self):

        self.event_services.subscribe_pps_state(
            self.handle_pps_state
        )

        self.event_services.subscribe_pps_edge(
            self.handle_pps_edge
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
    # PPS Sample Lookup
    # --------------------------------------------------

    def _make_rejected_lookup(
        self,
        target_monotonic_ns,
        reasons,
        candidate_lookup=None,
        **extra
    ):

        if isinstance(reasons, str):
            reasons = [reasons]

        result = {
            "accepted": False,
            "lookup_method": "rejected",
            "quality_reasons": list(
                dict.fromkeys(reasons)
            ),
            "target_monotonic_ns": (
                target_monotonic_ns
            ),
            "reference_blocks": {}
        }

        if isinstance(candidate_lookup, dict):

            result.update(
                copy.deepcopy(candidate_lookup)
            )

            candidate_method = result.get(
                "lookup_method"
            )

            candidate_reasons = list(
                result.get(
                    "quality_reasons",
                    []
                )
            )

            result["accepted"] = False
            result["lookup_method"] = "rejected"
            result["candidate_lookup_method"] = (
                candidate_method
            )
            result["quality_reasons"] = list(
                dict.fromkeys(
                    candidate_reasons
                    +
                    list(reasons)
                )
            )

        result.update(extra)

        return result

    def _capture_stream_snapshot_for_pps(self):

        try:
            return self.loop.snapshot_stream_position()

        except Exception as error:
            return {
                "stream_snapshot_available": False,
                "exception_type": type(error).__name__,
                "exception_message": str(error)
            }

    def _build_pending_pps_edge(
        self,
        event,
        payload,
        snapshot,
        pps_seq,
        pps_edge_monotonic_ns,
        received_monotonic_ns,
        received_realtime_ns
    ):

        enqueued_monotonic_ns = time.monotonic_ns()

        return {
            "schema_version": 1,
            "pending_state": "queued",
            "received_monotonic_ns": (
                received_monotonic_ns
            ),
            "received_realtime_ns": (
                received_realtime_ns
            ),
            "enqueued_monotonic_ns": (
                enqueued_monotonic_ns
            ),
            "resolution_deadline_monotonic_ns": (
                enqueued_monotonic_ns
                +
                int(
                    round(
                        self.pps_resolution_timeout_seconds
                        *
                        1e9
                    )
                )
            ),
            "node_id": self.node_id,
            "node_name": self.node_name,
            "pps_seq": pps_seq,
            "pps_kernel_realtime_ns": (
                self.get_first_available(
                    payload,
                    ["pps_kernel_realtime_ns"],
                    default=snapshot.get(
                        "pps_kernel_realtime_ns"
                    )
                )
            ),
            "pps_edge_monotonic_ns": (
                pps_edge_monotonic_ns
            ),
            "sequence_gap": self.get_first_available(
                payload,
                ["sequence_gap", "pps_sequence_gap"],
                default=snapshot.get("sequence_gap")
            ),
            "missed_edge_count": self.get_first_available(
                payload,
                ["missed_edge_count", "missed_edges"],
                default=snapshot.get(
                    "missed_edge_count"
                )
            ),
            "sequence_reset": self.get_first_available(
                payload,
                ["sequence_reset", "pps_sequence_reset"],
                default=snapshot.get("sequence_reset")
            ),
            "raw_pps_event": copy.deepcopy(event),
            "stream_snapshot_at_enqueue": (
                self._capture_stream_snapshot_for_pps()
            )
        }

    def handle_pps_edge(self, event):

        received_monotonic_ns = time.monotonic_ns()
        received_realtime_ns = time.time_ns()

        payload = self.get_payload(event)

        snapshot = payload.get("snapshot", {})
        if not isinstance(snapshot, dict):
            snapshot = {}

        pps_seq = self.get_first_available(
            payload,
            [
                "pps_seq",
                "sequence",
                "pps_sequence",
                "pulse_count"
            ],
            default=snapshot.get("pps_seq")
        )

        pps_edge_monotonic_ns = self.get_first_available(
            payload,
            ["pps_edge_monotonic_ns"],
            default=snapshot.get("pps_edge_monotonic_ns")
        )

        pending = self._build_pending_pps_edge(
            event=event,
            payload=payload,
            snapshot=snapshot,
            pps_seq=pps_seq,
            pps_edge_monotonic_ns=(
                pps_edge_monotonic_ns
            ),
            received_monotonic_ns=(
                received_monotonic_ns
            ),
            received_realtime_ns=(
                received_realtime_ns
            )
        )

        if pps_edge_monotonic_ns is None:

            lookup_result = self._make_rejected_lookup(
                target_monotonic_ns=None,
                reasons=[
                    "missing_pps_edge_monotonic_ns"
                ]
            )

            return self._finalize_pps_anchor(
                pending=pending,
                lookup_result=lookup_result,
                resolver_state="rejected_before_queue",
                resolution_attempts=[]
            )

        try:
            pending["pps_edge_monotonic_ns"] = int(
                pps_edge_monotonic_ns
            )

        except (TypeError, ValueError):

            lookup_result = self._make_rejected_lookup(
                target_monotonic_ns=None,
                reasons=[
                    "invalid_pps_edge_monotonic_ns"
                ]
            )

            return self._finalize_pps_anchor(
                pending=pending,
                lookup_result=lookup_result,
                resolver_state="rejected_before_queue",
                resolution_attempts=[]
            )

        try:
            self._pending_pps_edges.put_nowait(
                pending
            )

        except Full:

            lookup_result = self._make_rejected_lookup(
                target_monotonic_ns=(
                    pending["pps_edge_monotonic_ns"]
                ),
                reasons=[
                    "pending_pps_queue_full"
                ],
                pending_queue_capacity=(
                    self.pps_pending_queue_capacity
                )
            )

            return self._finalize_pps_anchor(
                pending=pending,
                lookup_result=lookup_result,
                resolver_state="rejected_queue_full",
                resolution_attempts=[]
            )

        self.log(
            (
                "PPS edge queued for sample resolution: "
                f"seq={pps_seq} "
                f"pending={self._pending_pps_edges.qsize()}"
            )
        )

        return pending

    def _pps_anchor_resolver_worker(self):

        while True:

            if (
                self._pps_resolver_stop_event.is_set()
                and
                self._pending_pps_edges.empty()
            ):
                return

            try:
                pending = self._pending_pps_edges.get(
                    timeout=0.05
                )

            except Empty:
                continue

            try:

                if self._pps_resolver_stop_event.is_set():

                    lookup_result = self._make_rejected_lookup(
                        target_monotonic_ns=pending.get(
                            "pps_edge_monotonic_ns"
                        ),
                        reasons=[
                            "pps_resolver_stopped"
                        ]
                    )

                    self._finalize_pps_anchor(
                        pending=pending,
                        lookup_result=lookup_result,
                        resolver_state="rejected_resolver_stopped",
                        resolution_attempts=[]
                    )

                else:

                    self._resolve_pending_pps_edge(
                        pending
                    )

            except Exception as error:

                lookup_result = self._make_rejected_lookup(
                    target_monotonic_ns=pending.get(
                        "pps_edge_monotonic_ns"
                    ),
                    reasons=[
                        "pps_resolver_exception"
                    ],
                    exception_type=type(error).__name__,
                    exception_message=str(error)
                )

                self._finalize_pps_anchor(
                    pending=pending,
                    lookup_result=lookup_result,
                    resolver_state="rejected_resolver_exception",
                    resolution_attempts=[]
                )

            finally:
                self._pending_pps_edges.task_done()

    def _pending_stream_invalidation_reason(
        self,
        pending,
        current_snapshot
    ):

        enqueue_snapshot = pending.get(
            "stream_snapshot_at_enqueue",
            {}
        )

        if not isinstance(enqueue_snapshot, dict):
            enqueue_snapshot = {}

        if not isinstance(current_snapshot, dict):
            return "continuous_stream_inactive"

        enqueue_stream_instance_id = (
            enqueue_snapshot.get(
                "stream_instance_id"
            )
        )

        current_stream_instance_id = (
            current_snapshot.get(
                "stream_instance_id"
            )
        )

        if (
            enqueue_stream_instance_id is None
            or
            current_stream_instance_id is None
        ):
            return "continuous_stream_inactive"

        if (
            enqueue_stream_instance_id
            !=
            current_stream_instance_id
        ):
            return "pending_stream_instance_changed"

        enqueue_timing_segment_id = (
            enqueue_snapshot.get(
                "timing_segment_id"
            )
        )

        current_timing_segment_id = (
            current_snapshot.get(
                "timing_segment_id"
            )
        )

        if (
            enqueue_timing_segment_id is None
            or
            current_timing_segment_id is None
        ):
            return "pending_timing_segment_unavailable"

        if (
            int(enqueue_timing_segment_id)
            !=
            int(current_timing_segment_id)
        ):
            return "pending_timing_segment_changed"

        return None

    def _lookup_invalidation_reason(
        self,
        pending,
        lookup_result
    ):

        if not isinstance(lookup_result, dict):
            return "sample_lookup_result_invalid"

        enqueue_snapshot = pending.get(
            "stream_snapshot_at_enqueue",
            {}
        )

        if not isinstance(enqueue_snapshot, dict):
            enqueue_snapshot = {}

        enqueue_stream_instance_id = (
            enqueue_snapshot.get(
                "stream_instance_id"
            )
        )

        lookup_stream_instance_id = (
            lookup_result.get(
                "stream_instance_id"
            )
        )

        if (
            lookup_stream_instance_id is not None
            and
            enqueue_stream_instance_id is not None
            and
            lookup_stream_instance_id
            !=
            enqueue_stream_instance_id
        ):
            return "pending_lookup_stream_instance_mismatch"

        enqueue_timing_segment_id = (
            enqueue_snapshot.get(
                "timing_segment_id"
            )
        )

        lookup_timing_segment_id = (
            lookup_result.get(
                "timing_segment_id"
            )
        )

        if (
            lookup_timing_segment_id is not None
            and
            enqueue_timing_segment_id is not None
            and
            int(lookup_timing_segment_id)
            !=
            int(enqueue_timing_segment_id)
        ):
            return "pending_lookup_timing_segment_mismatch"

        return None

    def _lookup_can_improve_after_callback(
        self,
        lookup_result
    ):

        if not isinstance(lookup_result, dict):
            return False

        if (
            lookup_result.get("accepted")
            and
            lookup_result.get("lookup_method")
            ==
            "callback_pair_extrapolation"
        ):
            return True

        reasons = set(
            lookup_result.get(
                "quality_reasons",
                []
            )
        )

        if not reasons:
            return False

        transient_reasons = {
            "insufficient_callback_history",
            "extrapolation_distance_exceeded",
            "no_bracketing_callback_pair"
        }

        if reasons.issubset(transient_reasons):
            return True

        reference_blocks = lookup_result.get(
            "reference_blocks",
            {}
        )

        if not isinstance(reference_blocks, dict):
            return False

        right = reference_blocks.get("right")

        if not isinstance(right, dict):
            return False

        try:
            target_ns = int(
                lookup_result["target_monotonic_ns"]
            )
            right_ns = int(
                right["estimated_adc_monotonic_ns"]
            )

        except (KeyError, TypeError, ValueError):
            return False

        return bool(
            target_ns > right_ns
            and
            reasons.issubset(
                transient_reasons
                |
                {"local_rate_outside_sanity_range"}
            )
        )

    def _resolve_pending_pps_edge(self, pending):

        resolution_started_monotonic_ns = (
            time.monotonic_ns()
        )

        deadline_monotonic_ns = int(
            pending[
                "resolution_deadline_monotonic_ns"
            ]
        )

        target_monotonic_ns = int(
            pending["pps_edge_monotonic_ns"]
        )

        resolution_attempts = []
        last_lookup_result = None

        while True:

            if self._pps_resolver_stop_event.is_set():

                lookup_result = self._make_rejected_lookup(
                    target_monotonic_ns=(
                        target_monotonic_ns
                    ),
                    reasons=[
                        "pps_resolver_stopped"
                    ],
                    candidate_lookup=(
                        last_lookup_result
                    )
                )

                return self._finalize_pps_anchor(
                    pending=pending,
                    lookup_result=lookup_result,
                    resolver_state="rejected_resolver_stopped",
                    resolution_attempts=(
                        resolution_attempts
                    ),
                    resolution_started_monotonic_ns=(
                        resolution_started_monotonic_ns
                    )
                )

            current_snapshot = (
                self._capture_stream_snapshot_for_pps()
            )

            invalidation_reason = (
                self._pending_stream_invalidation_reason(
                    pending=pending,
                    current_snapshot=current_snapshot
                )
            )

            if invalidation_reason:

                lookup_result = self._make_rejected_lookup(
                    target_monotonic_ns=(
                        target_monotonic_ns
                    ),
                    reasons=[
                        invalidation_reason
                    ],
                    candidate_lookup=(
                        last_lookup_result
                    ),
                    stream_snapshot_at_rejection=(
                        current_snapshot
                    )
                )

                return self._finalize_pps_anchor(
                    pending=pending,
                    lookup_result=lookup_result,
                    resolver_state="rejected_discontinuity",
                    resolution_attempts=(
                        resolution_attempts
                    ),
                    resolution_started_monotonic_ns=(
                        resolution_started_monotonic_ns
                    )
                )

            now_monotonic_ns = time.monotonic_ns()

            if now_monotonic_ns >= deadline_monotonic_ns:

                lookup_result = self._make_rejected_lookup(
                    target_monotonic_ns=(
                        target_monotonic_ns
                    ),
                    reasons=[
                        "pending_resolution_timeout"
                    ],
                    candidate_lookup=(
                        last_lookup_result
                    )
                )

                return self._finalize_pps_anchor(
                    pending=pending,
                    lookup_result=lookup_result,
                    resolver_state="rejected_timeout",
                    resolution_attempts=(
                        resolution_attempts
                    ),
                    resolution_started_monotonic_ns=(
                        resolution_started_monotonic_ns
                    )
                )

            try:
                lookup_result = (
                    self.loop
                    .lookup_sample_position_at_monotonic_ns(
                        target_monotonic_ns
                    )
                )

            except Exception as error:

                lookup_result = self._make_rejected_lookup(
                    target_monotonic_ns=(
                        target_monotonic_ns
                    ),
                    reasons=[
                        "sample_lookup_exception"
                    ],
                    exception_type=(
                        type(error).__name__
                    ),
                    exception_message=str(error)
                )

            last_lookup_result = lookup_result

            resolution_attempts.append(
                copy.deepcopy(lookup_result)
            )

            lookup_invalidation_reason = (
                self._lookup_invalidation_reason(
                    pending=pending,
                    lookup_result=lookup_result
                )
            )

            if lookup_invalidation_reason:

                rejected_lookup = self._make_rejected_lookup(
                    target_monotonic_ns=(
                        target_monotonic_ns
                    ),
                    reasons=[
                        lookup_invalidation_reason
                    ],
                    candidate_lookup=lookup_result
                )

                return self._finalize_pps_anchor(
                    pending=pending,
                    lookup_result=rejected_lookup,
                    resolver_state="rejected_discontinuity",
                    resolution_attempts=(
                        resolution_attempts
                    ),
                    resolution_started_monotonic_ns=(
                        resolution_started_monotonic_ns
                    )
                )

            post_lookup_snapshot = (
                self._capture_stream_snapshot_for_pps()
            )

            invalidation_reason = (
                self._pending_stream_invalidation_reason(
                    pending=pending,
                    current_snapshot=(
                        post_lookup_snapshot
                    )
                )
            )

            if invalidation_reason:

                rejected_lookup = self._make_rejected_lookup(
                    target_monotonic_ns=(
                        target_monotonic_ns
                    ),
                    reasons=[
                        invalidation_reason
                    ],
                    candidate_lookup=lookup_result,
                    stream_snapshot_at_rejection=(
                        post_lookup_snapshot
                    )
                )

                return self._finalize_pps_anchor(
                    pending=pending,
                    lookup_result=rejected_lookup,
                    resolver_state="rejected_discontinuity",
                    resolution_attempts=(
                        resolution_attempts
                    ),
                    resolution_started_monotonic_ns=(
                        resolution_started_monotonic_ns
                    )
                )

            if (
                lookup_result.get("accepted")
                and
                lookup_result.get("lookup_method")
                ==
                "callback_pair_interpolation"
            ):

                return self._finalize_pps_anchor(
                    pending=pending,
                    lookup_result=lookup_result,
                    resolver_state="resolved_interpolation",
                    resolution_attempts=(
                        resolution_attempts
                    ),
                    resolution_started_monotonic_ns=(
                        resolution_started_monotonic_ns
                    )
                )

            if not self._lookup_can_improve_after_callback(
                lookup_result
            ):

                return self._finalize_pps_anchor(
                    pending=pending,
                    lookup_result=lookup_result,
                    resolver_state="rejected_lookup_quality",
                    resolution_attempts=(
                        resolution_attempts
                    ),
                    resolution_started_monotonic_ns=(
                        resolution_started_monotonic_ns
                    )
                )

            if (
                len(resolution_attempts)
                >=
                self.pps_resolution_max_attempts
            ):

                rejected_lookup = self._make_rejected_lookup(
                    target_monotonic_ns=(
                        target_monotonic_ns
                    ),
                    reasons=[
                        "pending_resolution_attempt_limit"
                    ],
                    candidate_lookup=lookup_result
                )

                return self._finalize_pps_anchor(
                    pending=pending,
                    lookup_result=rejected_lookup,
                    resolver_state="rejected_attempt_limit",
                    resolution_attempts=(
                        resolution_attempts
                    ),
                    resolution_started_monotonic_ns=(
                        resolution_started_monotonic_ns
                    )
                )

            callback_index = current_snapshot.get(
                "latest_block_callback_index"
            )

            if callback_index is None:
                callback_index = current_snapshot.get(
                    "callback_count",
                    0
                )

            remaining_seconds = max(
                0.0,
                (
                    deadline_monotonic_ns
                    -
                    time.monotonic_ns()
                )
                /
                1e9
            )

            if remaining_seconds <= 0:
                continue

            self.loop.wait_for_callback_after_index(
                callback_index=callback_index,
                timeout_seconds=min(
                    remaining_seconds,
                    self.pps_resolution_wait_slice_seconds
                )
            )

    def _finalize_pps_anchor(
        self,
        pending,
        lookup_result,
        resolver_state,
        resolution_attempts,
        resolution_started_monotonic_ns=None
    ):

        resolution_finished_monotonic_ns = (
            time.monotonic_ns()
        )

        if resolution_started_monotonic_ns is None:
            resolution_started_monotonic_ns = (
                resolution_finished_monotonic_ns
            )

        accepted = bool(
            lookup_result.get("accepted", False)
        )

        if (
            accepted
            and
            lookup_result.get("lookup_method")
            !=
            "callback_pair_interpolation"
        ):

            lookup_result = self._make_rejected_lookup(
                target_monotonic_ns=pending.get(
                    "pps_edge_monotonic_ns"
                ),
                reasons=[
                    "non_interpolated_anchor_not_accepted"
                ],
                candidate_lookup=lookup_result
            )

            accepted = False
            resolver_state = (
                "rejected_non_interpolated_candidate"
            )

        with self._pps_anchor_lock:

            self.pps_anchor_attempt_count += 1

            if accepted:
                self.pps_anchor_accepted_count += 1
            else:
                self.pps_anchor_rejected_count += 1

            attempt_count = self.pps_anchor_attempt_count
            accepted_count = self.pps_anchor_accepted_count
            rejected_count = self.pps_anchor_rejected_count

            anchor_record = {
                "schema_version": 1,
                "anchor_state": "sample_lookup_only",
                "anchor_accepted": accepted,
                "anchor_quality": (
                    "ACCEPTED"
                    if accepted
                    else "REJECTED"
                ),
                "quality_reasons": list(
                    lookup_result.get(
                        "quality_reasons",
                        []
                    )
                ),
                "created_utc": self.get_utc_timestamp(),
                "received_monotonic_ns": pending.get(
                    "received_monotonic_ns"
                ),
                "received_realtime_ns": pending.get(
                    "received_realtime_ns"
                ),
                "enqueued_monotonic_ns": pending.get(
                    "enqueued_monotonic_ns"
                ),
                "resolution_started_monotonic_ns": (
                    resolution_started_monotonic_ns
                ),
                "resolution_finished_monotonic_ns": (
                    resolution_finished_monotonic_ns
                ),
                "resolution_elapsed_ms": (
                    resolution_finished_monotonic_ns
                    -
                    pending.get(
                        "enqueued_monotonic_ns",
                        resolution_started_monotonic_ns
                    )
                )
                /
                1e6,
                "resolver_state": resolver_state,
                "resolution_attempt_count": len(
                    resolution_attempts
                ),
                "resolution_attempts": copy.deepcopy(
                    resolution_attempts
                ),
                "node_id": self.node_id,
                "node_name": self.node_name,
                "pps_seq": pending.get("pps_seq"),
                "pps_kernel_realtime_ns": pending.get(
                    "pps_kernel_realtime_ns"
                ),
                "pps_edge_monotonic_ns": pending.get(
                    "pps_edge_monotonic_ns"
                ),
                "sequence_gap": pending.get(
                    "sequence_gap"
                ),
                "missed_edge_count": pending.get(
                    "missed_edge_count"
                ),
                "sequence_reset": pending.get(
                    "sequence_reset"
                ),
                "raw_pps_event": copy.deepcopy(
                    pending.get("raw_pps_event")
                ),
                "stream_snapshot_at_enqueue": (
                    copy.deepcopy(
                        pending.get(
                            "stream_snapshot_at_enqueue",
                            {}
                        )
                    )
                ),
                "sample_lookup": copy.deepcopy(
                    lookup_result
                ),
                "timing_state": (
                    "pps_anchor_candidate_unfitted"
                ),
                "corrected_tdoa_eligible": False,
                "microphone_synced": False,
                "attempt_count": attempt_count,
                "accepted_count": accepted_count,
                "rejected_count": rejected_count
            }

            self.latest_pps_sample_anchor = (
                anchor_record
            )

        self.pps_anchor_journal.enqueue(
            anchor_record
        )

        if accepted:

            self.log(
                (
                    "PPS sample lookup accepted: "
                    f"seq={pending.get('pps_seq')} "
                    f"method="
                    f"{lookup_result.get('lookup_method')} "
                    f"sample="
                    f"{lookup_result.get('sample_position_fractional')} "
                    f"segment="
                    f"{lookup_result.get('timing_segment_id')} "
                    f"attempts={len(resolution_attempts)}"
                )
            )

        else:

            self.log(
                (
                    "PPS sample lookup rejected: "
                    f"seq={pending.get('pps_seq')} "
                    f"resolver_state={resolver_state} "
                    f"reasons="
                    f"{lookup_result.get('quality_reasons', [])}"
                )
            )

        return anchor_record

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