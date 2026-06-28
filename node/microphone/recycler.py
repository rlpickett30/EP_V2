"""
recycler.py

Responsibilities:
- Manage recording retention
- Delete expired recordings
- Delete expired metadata
- Traverse recording directories

This module intentionally knows nothing about:
- EventBus
- Dispatchers
- BirdNET
- TDOA
- GPS
"""

from __future__ import annotations

import json
import time

from datetime import datetime
from datetime import timezone
from pathlib import Path


class Recycler:

    def __init__(
        self,
        recordings_root="recordings",
        default_retention_days=7,
        debug=True
    ):

        self.recordings_root = Path(
            recordings_root
        )

        self.default_retention_days = (
            default_retention_days
        )

        self.debug = debug

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:
            print(
                f"[Recycler] {message}"
            )

    # --------------------------------------------------
    # Metadata
    # --------------------------------------------------

    def load_metadata(self, metadata_path):

        try:
            with open(metadata_path, "r") as file:
                return json.load(file)

        except Exception:
            return {
                "preserve": False,
                "retention_days": self.default_retention_days
            }

    # --------------------------------------------------
    # Time Parsing
    # --------------------------------------------------

    def parse_epoch_from_metadata(self, metadata):

        for key in [
            "recording_epoch",
            "window_epoch",
            "scheduled_start_epoch"
        ]:
            value = metadata.get(key)

            if value is None:
                continue

            try:
                return float(value)
            except Exception:
                continue

        recording_utc = metadata.get("recording_utc")

        if isinstance(recording_utc, str):
            try:
                return datetime.fromisoformat(
                    recording_utc.replace("Z", "+00:00")
                ).timestamp()
            except Exception:
                return None

        return None

    def parse_legacy_epoch_from_filename(self, wav_path):

        try:
            parts = wav_path.stem.split("_")

            if len(parts) >= 2:
                return float(parts[1])

        except Exception:
            return None

        return None

    def get_recording_epoch(self, wav_path, metadata):

        recording_epoch = self.parse_epoch_from_metadata(
            metadata
        )

        if recording_epoch is not None:
            return recording_epoch

        recording_epoch = self.parse_legacy_epoch_from_filename(
            wav_path
        )

        if recording_epoch is not None:
            return recording_epoch

        try:
            return wav_path.stat().st_mtime
        except Exception:
            return None

    # --------------------------------------------------
    # Expiration Check
    # --------------------------------------------------

    def is_expired(self, recording_epoch, retention_days):

        if recording_epoch is None:
            return False

        age_seconds = time.time() - float(recording_epoch)
        retention_seconds = float(retention_days) * 86400.0

        return age_seconds > retention_seconds

    # --------------------------------------------------
    # Cleanup
    # --------------------------------------------------

    def cleanup(self):

        self.log("Starting cleanup")

        wav_files = self.recordings_root.rglob("*.wav")
        deleted = 0

        for wav_path in wav_files:

            metadata_path = wav_path.with_suffix(".json")
            metadata = self.load_metadata(metadata_path)

            if metadata.get("preserve", False):
                continue

            recording_epoch = self.get_recording_epoch(
                wav_path=wav_path,
                metadata=metadata
            )

            retention_days = metadata.get(
                "retention_days",
                self.default_retention_days
            )

            if not self.is_expired(
                recording_epoch,
                retention_days
            ):
                continue

            try:
                wav_path.unlink()
                deleted += 1

                self.log(
                    f"Deleted WAV: {wav_path}"
                )

            except Exception as error:
                self.log(
                    f"WAV delete failed: {error}"
                )

            try:
                spectrogram_path = wav_path.with_suffix(".png")

                if spectrogram_path.exists():
                    spectrogram_path.unlink()

            except Exception as error:
                self.log(
                    f"Spectrogram delete failed: {error}"
                )

            try:
                if metadata_path.exists():
                    metadata_path.unlink()

            except Exception as error:
                self.log(
                    f"Metadata delete failed: {error}"
                )

        self.log(
            f"Cleanup complete ({deleted} deleted)"
        )
