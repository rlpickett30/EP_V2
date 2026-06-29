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
#   Run BirdNET analysis on a supplied WAV recording path, generate one
#   compact spectrogram package for the same recording, and return
#   normalized BirdNET detection packages to the BirdNET dispatcher.
#
# Expected config source:
#   birdnet_config.json
#
# Expected config section:
#   spectrogram
#
# Does:
#   - Validate the supplied WAV path
#   - Call birdnet_analyzer.py
#   - Coordinate spectrogram_manager.py
#   - Convert BirdNET detections into normalized detection packages
#   - Attach one serialized spectrogram package to each detection package
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
from birdnet.spectrogram_manager import SpectrogramManager

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
        debug=True,
        spectrogram_config=None
    ):

        self.debug = debug

        self.spectrogram_manager = SpectrogramManager(
            config=spectrogram_config,
            debug=self.debug
        )

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
        detection,
        spectrogram_package=None,
        detection_index=0
    ):

        birdnet_event_utc = int(
            time.time()
        )

        species_code = detection.get(
            "species_code",
            "unknown"
        )

        start_time = detection.get(
            "start_time",
            0.0
        )

        try:

            start_ms = int(
                float(start_time) * 1000.0
            )

        except Exception:

            start_ms = 0

        birdnet_event_id = (
            f"AVIS_{recording_id}_{species_code}_{start_ms:05d}_{detection_index:02d}"
        )

        detection_package = {
            "birdnet_event_id": birdnet_event_id,
            "birdnet_event_utc": birdnet_event_utc,
            "recording_id": recording_id,
            "detection_index": detection_index,
            "primary_detection": detection_index == 0,
            "species_code": species_code,
            "common_name": detection.get(
                "common_name",
                "unknown"
            ),
            "scientific_name": detection.get(
                "scientific_name",
                "unknown"
            ),
            "confidence": detection.get(
                "confidence",
                0.0
            ),
            "birdnet_start_time": start_time,
            "birdnet_end_time": detection.get(
                "end_time",
                0.0
            )
        }

        if isinstance(
            spectrogram_package,
            dict
        ):

            detection_package["spectrogram"] = spectrogram_package
            detection_package["spectrogram_attached"] = True

        else:

            detection_package["spectrogram_attached"] = False

        return detection_package

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

        if not detections:

            self.log(
                "No BirdNET detections returned; spectrogram was not attached"
            )

            return []

        spectrogram_package = self.spectrogram_manager.build_spectrogram_package(
            wav_path=wav_path
        )

        detection_packages = []

        for detection_index, detection in enumerate(
            detections
        ):

            # Only the primary detection carries the image. Secondary
            # detections remain lightweight so one 15-second recording does
            # not create several duplicate spectrogram payloads.
            detection_spectrogram = (
                spectrogram_package
                if detection_index == 0
                else None
            )

            detection_package = self.build_detection_package(
                recording_id=recording_id,
                detection=detection,
                spectrogram_package=detection_spectrogram,
                detection_index=detection_index
            )

            detection_packages.append(
                detection_package
            )

        self.log(
            (
                f"Created {len(detection_packages)} BirdNET detection packages; "
                "spectrogram attached to primary detection only"
            )
        )

        return detection_packages
