# ============================================================
# birdnet_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   BirdNET
#
# Role:
#   Manager
#
# Purpose:
#   Run BirdNET analysis on a supplied WAV recording path and return
#   normalized BirdNET detection packages to the BirdNET dispatcher.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Validate the supplied WAV path
#   - Call birdnet_analyzer.py
#   - Convert BirdNET detections into normalized detection packages
#   - Preserve recording lineage
#
# Does NOT:
#   - Subscribe to the event bus
#   - Publish events
#   - Build final AVIS_LITE platform events
#   - Guess recording paths from recording IDs
#   - Read or write BirdNET configuration
#   - Own GPS state
#
# Owner:
#   birdnet_dispatcher.py
#
# ============================================================

from __future__ import annotations

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from birdnet.birdnet_analyzer import analyze_wav

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import time

from pathlib import Path


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class BirdNetManager:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        debug=True
    ):

        self.debug = debug

    # ========================================================
    # DEBUG
    # ========================================================

    def log(
        self,
        message
    ):

        if self.debug:

            print(
                f"[BirdNetManager] {message}"
            )

    # ========================================================
    # DETECTION PACKAGE BUILDER
    # ========================================================

    def build_detection_package(
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
            "birdnet_event_id": birdnet_event_id,
            "birdnet_event_utc": birdnet_event_utc,
            "recording_id": recording_id,
            "species_code": detection.get(
                "species_code",
                "unknown"
            ),
            "common_name": detection.get(
                "common_name",
                "unknown"
            ),
            "confidence": detection.get(
                "confidence",
                0.0
            ),
            "birdnet_start_time": detection.get(
                "start_time",
                0.0
            ),
            "birdnet_end_time": detection.get(
                "end_time",
                0.0
            )
        }

    # ========================================================
    # MAIN PROCESSING
    # ========================================================

    def process_recording(
        self,
        recording_id,
        recording_path,
        latitude,
        longitude,
        week,
        min_confidence
    ):

        if recording_path is None:

            self.log(
                "Recording ignored because recording_path was missing"
            )

            return []

        wav_path = Path(
            recording_path
        )

        if not wav_path.exists():

            self.log(
                f"Recording ignored because WAV file does not exist: {wav_path}"
            )

            return []

        self.log(
            f"Processing {wav_path}"
        )

        detections = analyze_wav(
            audio_path=wav_path,
            lat=latitude,
            lon=longitude,
            week=week,
            min_conf=min_confidence
        )

        detection_packages = []

        for detection in detections:

            detection_package = self.build_detection_package(
                recording_id=recording_id,
                detection=detection
            )

            detection_packages.append(
                detection_package
            )

        self.log(
            f"Created {len(detection_packages)} BirdNET detection packages"
        )

        return detection_packages