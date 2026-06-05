"""
microphone_loop.py

Responsibilities:

- Detect audio input devices
- Create recording directories
- Record audio
- Save WAV files
- Return recording information

This module intentionally knows nothing about:

- EventBus
- Dispatchers
- BirdNET
- TDOA
- AVIS
- Recycling policies
"""

from __future__ import annotations

import wave

from pathlib import Path
from datetime import datetime

import numpy as np
import sounddevice as sd


class MicrophoneLoop:

    def __init__(
        self,
        recordings_root="recordings",
        sample_rate=96000,
        channels=1,
        debug=True
    ):

        self.recordings_root = Path(
            recordings_root
        )

        self.sample_rate = sample_rate
        self.channels = channels
        self.debug = debug

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:

            print(
                f"[MicrophoneLoop] {message}"
            )

    # --------------------------------------------------
    # Device Detection
    # --------------------------------------------------

    def available(self):

        try:

            devices = sd.query_devices()

            input_devices = [
                device
                for device in devices
                if device["max_input_channels"] > 0
            ]

            if not input_devices:

                self.log(
                    "No microphone devices detected"
                )

                return False

            return True

        except Exception as e:

            self.log(
                f"Device query failed: {e}"
            )

            return False

    # --------------------------------------------------
    # Directory Builder
    # --------------------------------------------------

    def build_recording_path(self):

        ...