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

    def load_metadata(
        self,
        metadata_path
    ):

        try:

            with open(
                metadata_path,
                "r"
            ) as file:

                return json.load(
                    file
                )

        except Exception:

            return {

                "preserve": False,

                "retention_days":
                    self.default_retention_days
            }

    # --------------------------------------------------
    # Expiration Check
    # --------------------------------------------------

    def is_expired(
        self,
        recording_utc,
        retention_days
    ):

        age_seconds = (
            time.time()
            - recording_utc
        )

        retention_seconds = (
            retention_days
            * 86400
        )

        return (
            age_seconds
            > retention_seconds
        )

    # --------------------------------------------------
    # Cleanup
    # --------------------------------------------------

    def cleanup(self):

        self.log(
            "Starting cleanup"
        )

        wav_files = (
            self.recordings_root.rglob(
                "*.wav"
            )
        )

        deleted = 0

        for wav_path in wav_files:

            metadata_path = (
                wav_path.with_suffix(
                    ".json"
                )
            )

            metadata = (
                self.load_metadata(
                    metadata_path
                )
            )

            try:

                recording_id = (
                    wav_path.stem
                )

                recording_utc = int(
                    recording_id.split(
                        "_"
                    )[1]
                )

            except Exception:

                self.log(
                    f"Bad filename: "
                    f"{wav_path}"
                )

                continue

            retention_days = (
                metadata.get(
                    "retention_days",
                    self.default_retention_days
                )
            )

            if not self.is_expired(
                recording_utc,
                retention_days
            ):

                continue

            try:

                wav_path.unlink()

                deleted += 1

                self.log(
                    f"Deleted WAV: "
                    f"{wav_path}"
                )

            except Exception as e:

                self.log(
                    f"WAV delete failed: "
                    f"{e}"
                )

            try:

                if metadata_path.exists():

                    metadata_path.unlink()

            except Exception as e:

                self.log(
                    f"Metadata delete failed: "
                    f"{e}"
                )

        self.log(
            f"Cleanup complete "
            f"({deleted} deleted)"
        )