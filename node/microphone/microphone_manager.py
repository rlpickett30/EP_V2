# ============================================================
# microphone_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Microphone
#
# Role:
#   Manager
#
# Purpose:
#   Normalize microphone recording objects into canonical EnviroPulse
#   microphone event dictionaries.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Build shared microphone event payload fields
#   - Build RECORDING_AVAILABLE events
#   - Validate and select guarded WAVs for TDOA transfer
#   - Build TDOA_RECORDING success and failure events
#   - Build MICROPHONE_SYNCED events
#   - Preserve recording lineage
#   - Preserve PPS state context in recording events
#   - Preserve scheduled window timing metadata
#   - Preserve TDOA request and candidate lineage
#
# Does NOT:
#   - Record audio
#   - Access microphone hardware
#   - Publish events
#   - Subscribe to the event bus
#   - Own timing decisions
#   - Own TDOA request targeting
#   - Create replacement recordings for TDOA requests
#   - Transfer WAV files to the server
#   - Own BirdNET analysis
#   - Own recycling policies
#
# Owner:
#   microphone_dispatcher.py
#
# ============================================================

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path


class MicrophoneManager:

    def __init__(
        self,
        node_id=None,
        node_name=None,
        debug=True
    ):

        self.node_id = node_id
        self.node_name = node_name
        self.debug = debug

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:
            print(
                f"[MicrophoneManager] {message}"
            )

    # --------------------------------------------------
    # Shared Helpers
    # --------------------------------------------------

    def get_utc_timestamp(self):

        return (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def get_first_available(self, source, keys, default=None):

        for key in keys:
            value = source.get(key)

            if value is not None:
                return value

        return default

    def get_tdoa_request_id(self, request_payload):

        request_payload = request_payload or {}

        return self.get_first_available(
            request_payload,
            [
                "tdoa_request_id",
                "request_id",
                "event_id",
                "recording_request_id"
            ]
        )

    def get_tdoa_request_lineage(self, request_payload):

        request_payload = request_payload or {}
        request_id = self.get_tdoa_request_id(
            request_payload
        )

        candidate_key = self.get_first_available(
            request_payload,
            ["candidate_key", "candidate_id"]
        )

        candidate_id = self.get_first_available(
            request_payload,
            ["candidate_id", "candidate_key", "avis_lite_id"]
        )

        recording_id = self.get_first_available(
            request_payload,
            ["recording_id", "source_recording_id"]
        )

        return {
            "tdoa_request_id": request_id,
            "request_id": request_id,
            "candidate_id": candidate_id,
            "candidate_key": candidate_key,
            "avis_lite_id": request_payload.get(
                "avis_lite_id"
            ),
            "birdnet_event_id": request_payload.get(
                "birdnet_event_id"
            ),
            "requested_recording_id": recording_id,
            "source_recording_id": self.get_first_available(
                request_payload,
                ["source_recording_id", "recording_id"]
            ),
            "request_timestamp": self.get_first_available(
                request_payload,
                ["request_timestamp", "timestamp"]
            ),
            "requested_start_utc": self.get_first_available(
                request_payload,
                [
                    "requested_start_utc",
                    "start_time_utc",
                    "scheduled_start_utc"
                ]
            ),
            "requested_duration_sec": self.get_first_available(
                request_payload,
                ["duration_sec", "tdoa_duration_sec"]
            )
        }

    def build_tdoa_response_id(
        self,
        request_id,
        recording_id,
        node_id,
        timestamp
    ):

        identity_parts = [
            request_id or recording_id or timestamp,
            node_id or "unknown_node"
        ]

        return "TDOA_RECORDING_" + "_".join(
            str(part)
            for part in identity_parts
        )

    def build_base_payload(
        self,
        recording,
        request_payload=None,
        pps_state=None,
        sync_source="local_clock"
    ):

        request_payload = request_payload or {}
        pps_state = pps_state or {}

        recording_id = recording["recording_id"]

        payload = {
            "node_id": self.get_first_available(
                request_payload,
                ["node_id", "target_node_id"],
                default=self.node_id
            ),
            "node_name": self.get_first_available(
                request_payload,
                ["node_name", "target_node_name"],
                default=self.node_name
            ),
            "recording_id": recording_id,
            "recording_utc": recording.get("recording_utc"),
            "recording_epoch": recording.get("recording_epoch"),
            "recording_path": str(recording.get("wav_path")),
            "wav_path": str(recording.get("wav_path")),

            "guarded_wav_path": (
                str(
                    recording.get(
                        "guarded_wav_path"
                    )
                )
                if recording.get(
                    "guarded_wav_path"
                )
                else None
            ),

            "metadata_path": str(recording.get("metadata_path")),
            "spectrogram_path": (
                str(recording.get("spectrogram_path"))
                if recording.get("spectrogram_path")
                else None
            ),
            "sample_rate": recording.get("sample_rate"),
            "channels": recording.get("channels"),
            "duration_sec": recording.get("duration_sec"),
            "frame_count": recording.get("frame_count"),

            "guarded_duration_sec": recording.get(
                "guarded_duration_sec"
            ),
            "guarded_frame_count": recording.get(
                "guarded_frame_count"
            ),

            "recording_type": recording.get("recording_type"),
            "sync_source": sync_source,
            "pps_locked": bool(pps_state.get("pps_locked", False)),
            "pps_state": pps_state,
            "scheduled_start_utc": recording.get("scheduled_start_utc"),
            "scheduled_start_epoch": recording.get("scheduled_start_epoch"),
            "window_utc": recording.get("window_utc"),
            "window_epoch": recording.get("window_epoch"),
            "window_second": recording.get("window_second"),
            "start_error_ms": recording.get("start_error_ms"),
            "actual_duration_sec": recording.get("actual_duration_sec"),
            "device": recording.get("device"),
            "microphone_type": recording.get("microphone_type"),

            "recording_engine": recording.get(
                "recording_engine"
            ),
            "continuous_stream": recording.get(
                "continuous_stream",
                False
            ),
            "timing_state": recording.get(
                "timing_state"
            ),

            "boundary_utc": recording.get(
                "boundary_utc"
            ),
            "boundary_epoch": recording.get(
                "boundary_epoch"
            ),
            "boundary_second": recording.get(
                "boundary_second"
            ),
            "boundary_sample": recording.get(
                "boundary_sample"
            ),
            "boundary_snapshot_error_ms": recording.get(
                "boundary_snapshot_error_ms"
            ),
            "boundary_snapshot": recording.get(
                "boundary_snapshot"
            ),

            "stream_start_sample": recording.get(
                "stream_start_sample"
            ),
            "stream_end_sample_exclusive": recording.get(
                "stream_end_sample_exclusive"
            ),

            "guarded_stream_start_sample": recording.get(
                "guarded_stream_start_sample"
            ),
            "guarded_stream_end_sample_exclusive": recording.get(
                "guarded_stream_end_sample_exclusive"
            ),

            "pre_roll_frames": recording.get(
                "pre_roll_frames"
            ),
            "post_roll_frames": recording.get(
                "post_roll_frames"
            ),
            "pre_roll_seconds": recording.get(
                "pre_roll_seconds"
            ),
            "post_roll_seconds": recording.get(
                "post_roll_seconds"
            ),

            "stream_status_events": recording.get(
                "stream_status_events",
                []
            ),
            "stream_status_event_count": recording.get(
                "stream_status_event_count",
                0
            ),
            "raw_timing_quality": recording.get(
                "raw_timing_quality",
                "UNKNOWN"
            ),

            "timing_issues": recording.get(
                "timing_issues",
                []
            ),

            "clock_fit_eligible": bool(
                recording.get(
                    "clock_fit_eligible",
                    False
                )
            ),

            "corrected_tdoa_eligible": bool(
                recording.get(
                    "corrected_tdoa_eligible",
                    False
                )
            ),            
        }

        return payload

    # --------------------------------------------------
    # MICROPHONE_SYNCED
    # --------------------------------------------------

    def build_microphone_synced_event(
        self,
        recording,
        pps_state=None,
        sync_source="local_clock",
        scheduled_start_epoch=None,
        scheduled_start_utc=None,
        sync_error_ms=None,
        sync_window_ms=None,
        consecutive_synced_windows=1
    ):

        timestamp = self.get_utc_timestamp()
        pps_state = pps_state or {}

        payload = self.build_base_payload(
            recording=recording,
            pps_state=pps_state,
            sync_source=sync_source
        )

        payload.update({
            "microphone_synced": True,
            "sync_source": sync_source,
            "sync_state": "SYNCED",
            "scheduled_start_epoch": scheduled_start_epoch,
            "scheduled_start_utc": scheduled_start_utc,
            "window_epoch": recording.get("window_epoch"),
            "window_utc": recording.get("window_utc"),
            "window_second": recording.get("window_second"),
            "sync_error_ms": sync_error_ms,
            "sync_window_ms": sync_window_ms,
            "consecutive_synced_windows": consecutive_synced_windows
        })

        event = {
            "event_type": "MICROPHONE_SYNCED",
            "source": "microphone",
            "target": "server",
            "timestamp": timestamp,
            "payload": payload,
            "event_id": payload["recording_id"],
            "recording_id": payload["recording_id"],
            "recording_utc": payload["recording_utc"],
            "recording_epoch": payload["recording_epoch"],
            "recording_path": payload["recording_path"],
            "wav_path": payload["wav_path"],
            "metadata_path": payload["metadata_path"],
            "spectrogram_path": payload.get("spectrogram_path"),
            "microphone_synced": True,
            "sync_error_ms": sync_error_ms,
            "sync_window_ms": sync_window_ms,
            "window_utc": payload.get("window_utc"),
            "window_epoch": payload.get("window_epoch"),
            "window_second": payload.get("window_second")
        }

        return event

    # --------------------------------------------------
    # RECORDING_AVAILABLE
    # --------------------------------------------------

    def build_recording_available_event(
        self,
        recording,
        pps_state=None,
        sync_source="local_clock"
    ):

        timestamp = self.get_utc_timestamp()

        payload = self.build_base_payload(
            recording=recording,
            pps_state=pps_state,
            sync_source=sync_source
        )

        event = {
            "event_type": "RECORDING_AVAILABLE",
            "source": "microphone",
            "target": "birdnet",
            "timestamp": timestamp,
            "payload": payload,
            "event_id": payload["recording_id"],
            "recording_id": payload["recording_id"],
            "recording_utc": payload["recording_utc"],
            "recording_path": payload["recording_path"],
            "wav_path": payload["wav_path"],
            "metadata_path": payload["metadata_path"],
            "spectrogram_path": payload.get("spectrogram_path"),
            "window_utc": payload.get("window_utc"),
            "window_epoch": payload.get("window_epoch"),
            "window_second": payload.get("window_second")
        }

        return event

    # --------------------------------------------------
    # TDOA_RECORDING
    # --------------------------------------------------

    def prepare_tdoa_recording(
        self,
        recording,
        requested_recording_id
    ):

        result = {
            "success": False,
            "recording": None,
            "failure_reason": None,
            "failure_detail": None
        }

        if not isinstance(recording, dict):
            result["failure_reason"] = "recording_payload_invalid"
            result["failure_detail"] = (
                "Indexed recording payload was not a dictionary."
            )
            return result

        recording_id = recording.get("recording_id")

        if recording_id != requested_recording_id:
            result["failure_reason"] = "recording_id_mismatch"
            result["failure_detail"] = (
                f"Requested {requested_recording_id!r}, "
                f"indexed {recording_id!r}."
            )
            return result

        guarded_wav_path = recording.get(
            "guarded_wav_path"
        )

        if not guarded_wav_path:
            result["failure_reason"] = "guarded_wav_path_missing"
            result["failure_detail"] = (
                "The indexed recording has no guarded_wav_path."
            )
            return result

        guarded_path = Path(
            str(guarded_wav_path)
        )

        if not guarded_path.is_file():
            result["failure_reason"] = "guarded_wav_not_found"
            result["failure_detail"] = str(guarded_path)
            return result

        selected_recording = dict(recording)

        core_wav_path = self.get_first_available(
            recording,
            ["core_wav_path", "wav_path", "recording_path"]
        )

        selected_recording.update({
            "core_wav_path": (
                str(core_wav_path)
                if core_wav_path
                else None
            ),
            "recording_path": str(guarded_path),
            "wav_path": str(guarded_path),
            "guarded_wav_path": str(guarded_path),
            "selected_wav_path": str(guarded_path),
            "tdoa_window_type": "guarded_raw",
            "duration_sec": self.get_first_available(
                recording,
                ["guarded_duration_sec", "duration_sec"]
            ),
            "frame_count": self.get_first_available(
                recording,
                ["guarded_frame_count", "frame_count"]
            )
        })

        result.update({
            "success": True,
            "recording": selected_recording
        })

        return result

    def build_tdoa_recording_success_event(
        self,
        recording,
        request_payload=None,
        pps_state=None,
        sync_source="local_clock"
    ):

        timestamp = self.get_utc_timestamp()
        request_payload = request_payload or {}

        lineage = self.get_tdoa_request_lineage(
            request_payload
        )

        payload = self.build_base_payload(
            recording=recording,
            request_payload=request_payload,
            pps_state=pps_state,
            sync_source=sync_source
        )

        payload.update(lineage)
        payload.update({
            "status": "success",
            "failure_reason": None,
            "failure_detail": None,
            "core_wav_path": recording.get(
                "core_wav_path"
            ),
            "selected_wav_path": recording.get(
                "selected_wav_path",
                recording.get("guarded_wav_path")
            ),
            "tdoa_window_type": recording.get(
                "tdoa_window_type",
                "guarded_raw"
            )
        })

        return self.build_tdoa_recording_envelope(
            payload=payload,
            timestamp=timestamp
        )

    def build_tdoa_recording_failure_event(
        self,
        request_payload,
        failure_reason,
        failure_detail=None,
        recording=None
    ):

        timestamp = self.get_utc_timestamp()
        request_payload = request_payload or {}
        recording = (
            recording
            if isinstance(recording, dict)
            else {}
        )

        lineage = self.get_tdoa_request_lineage(
            request_payload
        )

        payload = {
            "node_id": self.get_first_available(
                request_payload,
                ["node_id", "target_node_id"],
                default=self.node_id
            ),
            "node_name": self.get_first_available(
                request_payload,
                ["node_name", "target_node_name"],
                default=self.node_name
            ),
            "recording_id": lineage[
                "requested_recording_id"
            ],
            "recording_utc": recording.get(
                "recording_utc",
                request_payload.get("recording_utc")
            ),
            "recording_epoch": recording.get(
                "recording_epoch"
            ),
            "recording_path": None,
            "wav_path": None,
            "guarded_wav_path": None,
            "selected_wav_path": None,
            "metadata_path": recording.get(
                "metadata_path"
            ),
            "sample_rate": recording.get(
                "sample_rate"
            ),
            "channels": recording.get(
                "channels"
            ),
            "duration_sec": recording.get(
                "guarded_duration_sec",
                recording.get("duration_sec")
            ),
            "frame_count": recording.get(
                "guarded_frame_count",
                recording.get("frame_count")
            ),
            "guarded_duration_sec": recording.get(
                "guarded_duration_sec"
            ),
            "guarded_frame_count": recording.get(
                "guarded_frame_count"
            ),
            "recording_type": recording.get(
                "recording_type"
            ),
            "window_utc": recording.get(
                "window_utc"
            ),
            "window_epoch": recording.get(
                "window_epoch"
            ),
            "window_second": recording.get(
                "window_second"
            ),
            "timing_state": recording.get(
                "timing_state"
            ),
            "raw_timing_quality": recording.get(
                "raw_timing_quality",
                "UNKNOWN"
            ),
            "timing_issues": recording.get(
                "timing_issues",
                []
            ),
            "status": "failure",
            "failure_reason": str(failure_reason),
            "failure_detail": failure_detail
        }

        payload.update(lineage)

        return self.build_tdoa_recording_envelope(
            payload=payload,
            timestamp=timestamp
        )

    def build_tdoa_recording_envelope(
        self,
        payload,
        timestamp
    ):

        request_id = payload.get(
            "tdoa_request_id"
        )

        response_id = self.build_tdoa_response_id(
            request_id=request_id,
            recording_id=payload.get("recording_id"),
            node_id=payload.get("node_id"),
            timestamp=timestamp
        )

        event = {
            "event_type": "TDOA_RECORDING",
            "source": "microphone",
            "target": "sender",
            "timestamp": timestamp,
            "payload": payload,
            "event_id": response_id,
            "status": payload.get("status"),
            "failure_reason": payload.get(
                "failure_reason"
            ),
            "tdoa_request_id": request_id,
            "request_id": request_id,
            "candidate_id": payload.get(
                "candidate_id"
            ),
            "candidate_key": payload.get(
                "candidate_key"
            ),
            "recording_id": payload.get(
                "recording_id"
            ),
            "recording_utc": payload.get(
                "recording_utc"
            ),
            "recording_path": payload.get(
                "recording_path"
            ),
            "wav_path": payload.get(
                "wav_path"
            ),
            "guarded_wav_path": payload.get(
                "guarded_wav_path"
            ),
            "selected_wav_path": payload.get(
                "selected_wav_path"
            ),
            "metadata_path": payload.get(
                "metadata_path"
            ),
            "spectrogram_path": payload.get("spectrogram_path"),
            "window_utc": payload.get("window_utc"),
            "window_epoch": payload.get("window_epoch"),
            "window_second": payload.get("window_second")
        }

        return event
