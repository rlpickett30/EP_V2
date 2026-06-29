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
        sample_rate=48000,
        channels=1,
        device=None,
        spectrogram_config=None,
        debug=True
    ):

        self.recordings_root = Path(recordings_root)
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.device = device
        self.spectrogram_config = spectrogram_config or {}
        self.write_file_spectrogram = bool(
            self.spectrogram_config.get(
                "write_file",
                False
            )
            or self.spectrogram_config.get(
                "write_png_file",
                False
            )
        )
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

    def epoch_to_utc_timestamp(self, epoch):

        return (
            datetime.fromtimestamp(
                float(epoch),
                timezone.utc
            )
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def utc_timestamp_to_safe_name(self, timestamp):

        return (
            str(timestamp)
            .replace(":", "-")
            .replace("+00-00", "")
            .replace("Z", "")
        )

    # --------------------------------------------------
    # Directory Builder
    # --------------------------------------------------

    def build_recording_path(
        self,
        recording_type="recording",
        recording_id=None,
        scheduled_start_epoch=None,
        scheduled_start_utc=None
    ):

        if scheduled_start_epoch is not None:
            window_time = datetime.fromtimestamp(
                float(scheduled_start_epoch),
                timezone.utc
            )
        else:
            window_time = datetime.now(timezone.utc)

        epoch = int(window_time.timestamp())

        if recording_id is None:
            if scheduled_start_utc:
                safe_window = self.utc_timestamp_to_safe_name(
                    scheduled_start_utc
                )

                recording_id = (
                    f"{recording_type}_{safe_window}"
                )

            else:
                recording_id = (
                    f"{recording_type}_{epoch}_{uuid.uuid4().hex[:8]}"
                )

        recording_dir = (
            self.recordings_root
            / window_time.strftime("%Y")
            / window_time.strftime("%m")
            / window_time.strftime("%d")
        )

        recording_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        wav_path = recording_dir / f"{recording_id}.wav"
        metadata_path = recording_dir / f"{recording_id}.json"
        spectrogram_path = recording_dir / f"{recording_id}.png"

        return {
            "recording_id": recording_id,
            "wav_path": wav_path,
            "metadata_path": metadata_path,
            "spectrogram_path": spectrogram_path
        }

    # --------------------------------------------------
    # WAV Writer
    # --------------------------------------------------

    def write_wav(self, wav_path, audio):

        audio = np.asarray(audio)

        # Keep int16 recordings untouched.
        if audio.dtype == np.int16:
            output = audio

        else:
            audio = audio.astype(np.float32)
            audio = audio - np.mean(audio)

            peak = float(np.max(np.abs(audio)))

            if peak > 0:
                audio = audio * min(0.85 / peak, 4.0)

            audio = np.clip(audio, -1.0, 1.0)
            output = (audio * 32767).astype(np.int16)
            
        with wave.open(str(wav_path), "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(output.tobytes())

    # --------------------------------------------------
    # Spectrogram
    # --------------------------------------------------

    def generate_spectrogram(self, wav_path, spectrogram_path, audio):

        if not self.spectrogram_config.get("enabled", False):
            return None

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except Exception as error:
            self.log(f"Spectrogram unavailable: {error}")
            return None

        try:
            samples = np.asarray(audio)

            if samples.ndim > 1:
                samples = samples[:, 0]

            samples = samples.astype(np.float32)

            if samples.size == 0:
                return None

            peak = float(np.max(np.abs(samples)))

            if peak > 0:
                samples = samples / peak

            cmap = self.spectrogram_config.get("cmap", "magma")
            nfft = int(self.spectrogram_config.get("nfft", 2048))
            noverlap = int(self.spectrogram_config.get("noverlap", 1536))
            dpi = int(self.spectrogram_config.get("dpi", 140))
            max_frequency_hz = self.spectrogram_config.get(
                "max_frequency_hz",
                6000,
            )

            fig, ax = plt.subplots(figsize=(7.0, 3.6), dpi=dpi)
            fig.patch.set_facecolor("white")
            ax.set_facecolor("black")

            ax.specgram(
                samples,
                NFFT=nfft,
                Fs=self.sample_rate,
                noverlap=noverlap,
                cmap=cmap,
            )

            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Frequency (kHz)")

            if max_frequency_hz is not None:
                ax.set_ylim(0, float(max_frequency_hz))

            ticks = ax.get_yticks()
            ax.set_yticks(ticks)
            ax.set_yticklabels([
                f"{tick / 1000.0:g}"
                for tick in ticks
            ])

            ax.grid(False)
            fig.tight_layout()
            fig.savefig(str(spectrogram_path))
            plt.close(fig)

            return spectrogram_path

        except Exception as error:
            self.log(f"Spectrogram generation failed: {error}")
            return None

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
        scheduled_start_epoch=None,
        scheduled_start_utc=None,
        window_second=None
    ):

        duration_sec = float(duration_sec)
        frame_count = int(duration_sec * self.sample_rate)

        if scheduled_start_epoch is not None and scheduled_start_utc is None:
            scheduled_start_utc = self.epoch_to_utc_timestamp(
                scheduled_start_epoch
            )

        paths = self.build_recording_path(
            recording_type=recording_type,
            scheduled_start_epoch=scheduled_start_epoch,
            scheduled_start_utc=scheduled_start_utc
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
            dtype="int16",
            device=self.device
        )
    

        sd.wait()

        recording_finished_monotonic = time.monotonic()

        self.write_wav(
            paths["wav_path"],
            audio
        )

        spectrogram_path = None

        # Keep the microphone timing path minimal. Recording-side PNG
        # generation can take long enough to miss the next quarter-minute
        # window. BirdNET now builds AVIS_LITE spectrogram payloads from its
        # asynchronous worker instead.
        if self.write_file_spectrogram:

            spectrogram_path = self.generate_spectrogram(
                wav_path=paths["wav_path"],
                spectrogram_path=paths["spectrogram_path"],
                audio=audio
            )

        actual_duration_sec = (
            recording_finished_monotonic - recording_started_monotonic
        )

        start_error_ms = None

        if scheduled_start_epoch is not None:
            try:
                start_error_ms = (
                    float(recording_epoch) - float(scheduled_start_epoch)
                ) * 1000.0
            except Exception:
                start_error_ms = None

        return {
            "recording_id": paths["recording_id"],
            "recording_utc": recording_utc,
            "recording_epoch": recording_epoch,
            "scheduled_start_utc": scheduled_start_utc,
            "scheduled_start_epoch": scheduled_start_epoch,
            "window_utc": scheduled_start_utc,
            "window_epoch": scheduled_start_epoch,
            "window_second": window_second,
            "wav_path": paths["wav_path"],
            "metadata_path": paths["metadata_path"],
            "spectrogram_path": spectrogram_path,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "duration_sec": duration_sec,
            "frame_count": frame_count,
            "recording_type": recording_type,
            "request_id": request_id,
            "sync_source": sync_source,
            "pps_state": pps_state or {},
            "started_monotonic": recording_started_monotonic,
            "finished_monotonic": recording_finished_monotonic,
            "actual_duration_sec": actual_duration_sec,
            "start_error_ms": start_error_ms,
            "device": self.device
        }
