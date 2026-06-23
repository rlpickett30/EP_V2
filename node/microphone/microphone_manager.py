"""
microphone_manager.py

Responsibilities:
- Build RECORDING_AVAILABLE events
- Build TDOA_RECORDING events
- Normalize microphone recording objects into EnviroPulse event form

This module intentionally knows nothing about:
- EventBus
- Dispatchers
- BirdNET
- Audio recording
- Recycling policies
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone


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
            "metadata_path": str(recording.get("metadata_path")),
            "sample_rate": recording.get("sample_rate"),
            "channels": recording.get("channels"),
            "duration_sec": recording.get("duration_sec"),
            "frame_count": recording.get("frame_count"),
            "recording_type": recording.get("recording_type"),
            "sync_source": sync_source,
            "pps_locked": bool(pps_state.get("pps_locked", False)),
            "pps_state": pps_state
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

            # Flat compatibility fields for older local callbacks.
            "event_id": payload["recording_id"],
            "recording_id": payload["recording_id"],
            "recording_utc": payload["recording_utc"],
            "recording_epoch": payload["recording_epoch"],
            "recording_path": payload["recording_path"],
            "wav_path": payload["wav_path"],
            "metadata_path": payload["metadata_path"],
            "microphone_synced": True,
            "sync_error_ms": sync_error_ms,
            "sync_window_ms": sync_window_ms
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

            # Flat compatibility fields for older local callbacks.
            "event_id": payload["recording_id"],
            "recording_id": payload["recording_id"],
            "recording_utc": payload["recording_utc"],
            "recording_path": payload["recording_path"],
            "wav_path": payload["wav_path"],
            "metadata_path": payload["metadata_path"]
        }

        return event

    # --------------------------------------------------
    # TDOA_RECORDING
    # --------------------------------------------------

    def build_tdoa_recording_event(
        self,
        recording,
        request_payload=None,
        pps_state=None,
        sync_source="local_clock"
    ):

        timestamp = self.get_utc_timestamp()
        request_payload = request_payload or {}

        request_id = self.get_first_available(
            request_payload,
            [
                "tdoa_request_id",
                "request_id",
                "event_id",
                "recording_request_id"
            ]
        )

        payload = self.build_base_payload(
            recording=recording,
            request_payload=request_payload,
            pps_state=pps_state,
            sync_source=sync_source
        )

        payload.update({
            "tdoa_request_id": request_id,
            "request_id": request_id,
            "request_timestamp": self.get_first_available(
                request_payload,
                ["request_timestamp", "timestamp"]
            ),
            "requested_start_utc": self.get_first_available(
                request_payload,
                ["requested_start_utc", "start_time_utc", "scheduled_start_utc"]
            ),
            "requested_duration_sec": self.get_first_available(
                request_payload,
                ["duration_sec", "tdoa_duration_sec"]
            )
        })

        event = {
            "event_type": "TDOA_RECORDING",
            "source": "microphone",
            "target": "sender",
            "timestamp": timestamp,
            "payload": payload,

            # Flat compatibility fields for older local callbacks.
            "event_id": payload["recording_id"],
            "tdoa_request_id": request_id,
            "request_id": request_id,
            "recording_id": payload["recording_id"],
            "recording_utc": payload["recording_utc"],
            "recording_path": payload["recording_path"],
            "wav_path": payload["wav_path"],
            "metadata_path": payload["metadata_path"]
        }

        return event
