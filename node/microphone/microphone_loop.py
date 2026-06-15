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

import time
import uuid
import wave

from pathlib import Path
from datetime import datetime
from datetime import timezone

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

        self.recordings_root = Path(recordings_root)
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
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
                if device.get("max_input_channels", 0) > 0
            ]

            if not input_devices:
                self.log("No microphone devices detected")
                return False

            return True

        except Exception as error:
            self.log(
                f"Device query failed: {error}"
            )
            return False

    # --------------------------------------------------
    # Time Helpers
    # --------------------------------------------------

    def get_utc_timestamp(self):

        return (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    # --------------------------------------------------
    # Directory Builder
    # --------------------------------------------------

    def build_recording_path(
        self,
        recording_type="recording",
        recording_id=None
    ):

        now = datetime.now(timezone.utc)
        epoch = int(now.timestamp())

        if recording_id is None:
            recording_id = (
                f"{recording_type}_{epoch}_{uuid.uuid4().hex[:8]}"
            )

        recording_dir = (
            self.recordings_root
            / now.strftime("%Y")
            / now.strftime("%m")
            / now.strftime("%d")
        )

        recording_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        wav_path = recording_dir / f"{recording_id}.wav"
        metadata_path = recording_dir / f"{recording_id}.json"

        return {
            "recording_id": recording_id,
            "wav_path": wav_path,
            "metadata_path": metadata_path
        }

    # --------------------------------------------------
    # WAV Writer
    # --------------------------------------------------

    def write_wav(self, wav_path, audio):

        audio = np.asarray(audio)

        if audio.dtype != np.int16:
            audio = np.clip(audio, -1.0, 1.0)
            audio = (audio * 32767).astype(np.int16)

        with wave.open(str(wav_path), "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(audio.tobytes())

    # --------------------------------------------------
    # Recording
    # --------------------------------------------------

    def record(
        self,
        duration_sec,
        recording_type="recording",
        request_id=None,
        pps_state=None,
        sync_source="local_clock",
        scheduled_start_utc=None
    ):

        duration_sec = float(duration_sec)
        frame_count = int(duration_sec * self.sample_rate)

        paths = self.build_recording_path(
            recording_type=recording_type
        )

        recording_started_monotonic = time.monotonic()
        recording_epoch = time.time()
        recording_utc = self.get_utc_timestamp()

        self.log(
            f"Recording {duration_sec:.3f}s to {paths['wav_path']}"
        )

        audio = sd.rec(
            frame_count,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16"
        )

        sd.wait()

        recording_finished_monotonic = time.monotonic()

        self.write_wav(
            paths["wav_path"],
            audio
        )

        return {
            "recording_id": paths["recording_id"],
            "recording_utc": recording_utc,
            "recording_epoch": recording_epoch,
            "wav_path": paths["wav_path"],
            "metadata_path": paths["metadata_path"],
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "duration_sec": duration_sec,
            "frame_count": frame_count,
            "recording_type": recording_type,
            "request_id": request_id,
            "sync_source": sync_source,
            "scheduled_start_utc": scheduled_start_utc,
            "pps_state": pps_state or {},
            "started_monotonic": recording_started_monotonic,
            "finished_monotonic": recording_finished_monotonic
        }
