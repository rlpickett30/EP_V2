"""
birdnet_manager.py

Responsibilities:

- Locate recordings
- Run BirdNET analysis
- Convert BirdNET detections into EnviroPulse events
- Generate AVIS event IDs
- Preserve event lineage

This module intentionally knows nothing about:

- EventBus
- Publishers
- Subscribers
- GPS hardware
- Timing loops
- State machines
"""

from __future__ import annotations

import time

from pathlib import Path

from birdnet.birdnet_analyzer import analyze_wav


class BirdNetManager:

    def __init__(
        self,
        recordings_path,
        debug=True
    ):

        self.recordings_path = Path(
            recordings_path
        )

        self.debug = debug

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:

            print(
                f"[BirdNetManager] {message}"
            )

    # --------------------------------------------------
    # Recording Path Lookup
    # --------------------------------------------------

    def get_recording_path(
        self,
        recording_id
    ):

        return (
            self.recordings_path
            / f"{recording_id}.wav"
        )

    # --------------------------------------------------
    # Event Builder
    # --------------------------------------------------

    def build_avis_event(
        self,
        recording_id,
        detection
    ):

        birdnet_event_utc = int(
            time.time()
        )

        birdnet_event_id = (
            f"AVIS_{birdnet_event_utc}"
        )

        return {

            # --------------------------------------------------
            # Event Identity
            # --------------------------------------------------

            "event_type":
                "AVIS_LITE",

            "birdnet_event_id":
                birdnet_event_id,

            "birdnet_event_utc":
                birdnet_event_utc,

            # --------------------------------------------------
            # Lineage
            # --------------------------------------------------

            "recording_id":
                recording_id,

            # --------------------------------------------------
            # Detection
            # --------------------------------------------------

            "species_code":
                detection["species_code"],

            "common_name":
                detection["common_name"],

            "confidence":
                detection["confidence"],

            # --------------------------------------------------
            # BirdNET Timing
            # --------------------------------------------------

            "birdnet_start_time":
                detection["start_time"],

            "birdnet_end_time":
                detection["end_time"]
        }

    # --------------------------------------------------
    # Main Processing
    # --------------------------------------------------

    def process_recording(
        self,
        recording_id,
        latitude,
        longitude,
        week,
        min_confidence
    ):

        wav_path = self.get_recording_path(
            recording_id
        )

        self.log(
            f"Processing {wav_path}"
        )

        detections = analyze_wav(
            audio_path=wav_path,
            latitude=latitude,
            longitude=longitude,
            week=week,
            min_confidence=min_confidence
        )

        events = []

        for detection in detections:

            event = self.build_avis_event(
                recording_id,
                detection
            )

            events.append(
                event
            )

        self.log(
            f"Created {len(events)} AVIS events"
        )

        return events