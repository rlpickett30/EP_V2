"""
microphone_manager.py

Responsibilities:

- Build recording events
- Build TDOA recording events
- Generate EnviroPulse recording objects

This module intentionally knows nothing about:

- EventBus
- Dispatchers
- BirdNET
- Audio recording
- Recycling policies
"""

from __future__ import annotations


class MicrophoneManager:

    def __init__(
        self,
        debug=True
    ):

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
    # Recording Event
    # --------------------------------------------------

    def build_recording_available_event(
        self,
        recording
    ):

        event = {

            "event_type":
                "RECORDING_AVAILABLE",

            "event_id":
                recording[
                    "recording_id"
                ],

            "recording_id":
                recording[
                    "recording_id"
                ],

            "recording_utc":
                recording[
                    "recording_utc"
                ],

            "wav_path":
                str(
                    recording[
                        "wav_path"
                    ]
                ),

            "metadata_path":
                str(
                    recording[
                        "metadata_path"
                    ]
                )
        }

        return event

    # --------------------------------------------------
    # TDOA Recording Event
    # --------------------------------------------------

    def build_tdoa_recording_event(
        self,
        recording
    ):

        event = {

            "event_type":
                "TDOA_RECORDING",

            "event_id":
                recording[
                    "recording_id"
                ],

            "recording_id":
                recording[
                    "recording_id"
                ],

            "recording_utc":
                recording[
                    "recording_utc"
                ],

            "wav_path":
                str(
                    recording[
                        "wav_path"
                    ]
                ),

            "metadata_path":
                str(
                    recording[
                        "metadata_path"
                    ]
                )
        }

        return event
