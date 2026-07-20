# ============================================================
# microphone_loop.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Microphone
#
# Role:
#   Manager
#
# Purpose:
#   Perform low-level microphone recording work. Detect audio input
#   availability, create recording paths, record audio, save WAV files, and
#   return recording information to MicrophoneDispatcher.
#
# Expected config source:
#   microphone_config.json
#
# Expected config section:
#   config["recordings_root"], config["sample_rate"],
#   config["channels"], config["device"], config["spectrogram"]
#
# Does:
#   - Detect available audio input devices
#   - Create recording directories
#   - Build recording paths
#   - Record audio from the configured microphone device
#   - Save WAV files
#   - Optionally write file-based spectrogram PNGs
#   - Return recording metadata needed by MicrophoneDispatcher
#   - Report actual recording duration and start timing error
#
# Does NOT:
#   - Publish events
#   - Subscribe to the event bus
#   - Own microphone workflow decisions
#   - Track PPS state
#   - Track GPS state
#   - Decide TDOA request targeting
#   - Run BirdNET analysis
#   - Manage recycling policies
#
# Owner:
#   microphone_dispatcher.py
#
# ============================================================

from __future__ import annotations

import time
import uuid
import wave
import threading


from pathlib import Path
from datetime import datetime
from datetime import timezone
from collections import deque

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
        recording_engine="scheduled_start_stop",
        continuous_capture_config=None,
        debug=True
    ):

        self.recordings_root = Path(recordings_root)
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.device = device
        self.recording_engine = str(
            recording_engine or "scheduled_start_stop"
        ).strip().lower()

        self.continuous_capture_config = (
            continuous_capture_config
            if isinstance(continuous_capture_config, dict)
            else {}
        )

        self.block_frames = int(
            self.continuous_capture_config.get(
                "block_frames",
                1024
            )
        )

        self.stream_latency = self.continuous_capture_config.get(
            "latency",
            "high"
        )

        self.buffer_seconds = float(
            self.continuous_capture_config.get(
                "buffer_seconds",
                120.0
            )
        )

        self.buffer_frames = max(
            self.block_frames,
            int(round(self.buffer_seconds * self.sample_rate))
        )

        self._stream = None
        self._stream_condition = threading.Condition()
        self._stream_blocks = deque()
        self._stream_sample_counter = 0
        self._stream_callback_count = 0
        self._stream_status_count = 0
        self._stream_started_monotonic_ns = None
        self._stream_started_realtime_ns = None

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
    # Continuous Stream
    # --------------------------------------------------

    def start_continuous(self):

        if self.recording_engine != "continuous_pps":
            return False

        if self._stream is not None:
            return True

        device_info = sd.query_devices(
            self.device,
            "input"
        )

        self.log(
            (
                "Opening continuous microphone stream: "
                f"device={device_info['name']} "
                f"sample_rate={self.sample_rate} "
                f"channels={self.channels} "
                f"block_frames={self.block_frames} "
                f"latency={self.stream_latency}"
            )
        )

        with self._stream_condition:

            self._stream_blocks.clear()
            self._stream_sample_counter = 0
            self._stream_callback_count = 0
            self._stream_status_count = 0

        self._stream = sd.InputStream(
            device=self.device,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.block_frames,
            latency=self.stream_latency,
            callback=self._continuous_audio_callback
        )

        self._stream.start()

        self._stream_started_monotonic_ns = time.monotonic_ns()
        self._stream_started_realtime_ns = time.time_ns()

        self.log(
            "Continuous microphone stream started"
        )

        return True

    def stop_continuous(self):

        stream = self._stream
        self._stream = None

        if stream is None:
            return

        self.log(
            "Stopping continuous microphone stream"
        )

        try:
            stream.stop()

        finally:
            stream.close()

        with self._stream_condition:
            self._stream_condition.notify_all()

        self.log(
            "Continuous microphone stream stopped"
        )

    def continuous_stream_active(self):

        return bool(
            self._stream is not None
            and self._stream.active
        )

    def _continuous_audio_callback(
        self,
        indata,
        frames,
        time_info,
        status
    ):

        callback_monotonic_ns = time.monotonic_ns()
        callback_realtime_ns = time.time_ns()

        input_buffer_adc_time = float(
            time_info.inputBufferAdcTime
        )

        current_time = float(
            time_info.currentTime
        )

        estimated_adc_monotonic_ns = int(
            round(
                callback_monotonic_ns
                +
                (
                    input_buffer_adc_time
                    -
                    current_time
                )
                *
                1e9
            )
        )

        status_text = str(status) if status else ""

        with self._stream_condition:

            first_sample = self._stream_sample_counter

            self._stream_sample_counter += int(
                frames
            )

            self._stream_callback_count += 1

            if status:
                self._stream_status_count += 1

            self._stream_blocks.append(
                {
                    "first_sample": first_sample,
                    "end_sample_exclusive": (
                        first_sample
                        +
                        int(frames)
                    ),
                    "frame_count": int(frames),
                    "data": indata.copy(),
                    "input_buffer_adc_time": (
                        input_buffer_adc_time
                    ),
                    "current_time": current_time,
                    "callback_monotonic_ns": (
                        callback_monotonic_ns
                    ),
                    "callback_realtime_ns": (
                        callback_realtime_ns
                    ),
                    "estimated_adc_monotonic_ns": (
                        estimated_adc_monotonic_ns
                    ),
                    "status": status_text
                }
            )

            minimum_retained_sample = max(
                0,
                self._stream_sample_counter
                -
                self.buffer_frames
            )

            while self._stream_blocks:

                oldest = self._stream_blocks[0]

                if (
                    oldest["end_sample_exclusive"]
                    >
                    minimum_retained_sample
                ):
                    break

                self._stream_blocks.popleft()

            self._stream_condition.notify_all()

    def _wait_for_continuous_samples(
        self,
        end_sample_exclusive,
        timeout_seconds
    ):

        deadline = time.monotonic() + float(
            timeout_seconds
        )

        with self._stream_condition:

            while (
                self._stream_sample_counter
                <
                end_sample_exclusive
            ):

                if not self.continuous_stream_active():
                    return False

                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    return False

                self._stream_condition.wait(
                    timeout=min(remaining, 0.25)
                )

        return True

    def _read_continuous_samples(
        self,
        start_sample,
        end_sample_exclusive
    ):

        frame_count = int(
            end_sample_exclusive
            -
            start_sample
        )

        if frame_count <= 0:
            raise ValueError(
                "Continuous sample range must be positive"
            )

        output = np.zeros(
            (
                frame_count,
                self.channels
            ),
            dtype=np.int16
        )

        covered = np.zeros(
            frame_count,
            dtype=bool
        )

        status_events = []

        with self._stream_condition:

            blocks = list(
                self._stream_blocks
            )

        for block in blocks:

            block_start = int(
                block["first_sample"]
            )

            block_stop = int(
                block["end_sample_exclusive"]
            )

            overlap_start = max(
                start_sample,
                block_start
            )

            overlap_stop = min(
                end_sample_exclusive,
                block_stop
            )

            if overlap_stop <= overlap_start:
                continue

            source_start = (
                overlap_start
                -
                block_start
            )

            source_stop = (
                overlap_stop
                -
                block_start
            )

            destination_start = (
                overlap_start
                -
                start_sample
            )

            destination_stop = (
                overlap_stop
                -
                start_sample
            )

            output[
                destination_start:
                destination_stop
            ] = block["data"][
                source_start:
                source_stop
            ]

            covered[
                destination_start:
                destination_stop
            ] = True

            if block.get("status"):
                status_events.append(
                    {
                        "first_sample": block_start,
                        "status": block["status"]
                    }
                )

        if not np.all(covered):

            missing_frames = int(
                np.count_nonzero(
                    ~covered
                )
            )

            raise RuntimeError(
                (
                    "Continuous buffer does not contain "
                    f"{missing_frames} requested frames"
                )
            )

        return output, status_events

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

    def record_from_continuous_stream(
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

        if not self.continuous_stream_active():
            raise RuntimeError(
                "Continuous microphone stream is not active"
            )

        duration_sec = float(
            duration_sec
        )

        frame_count = int(
            round(
                duration_sec
                *
                self.sample_rate
            )
        )

        if (
            scheduled_start_epoch is not None
            and scheduled_start_utc is None
        ):
            scheduled_start_utc = (
                self.epoch_to_utc_timestamp(
                    scheduled_start_epoch
                )
            )

        paths = self.build_recording_path(
            recording_type=recording_type,
            scheduled_start_epoch=scheduled_start_epoch,
            scheduled_start_utc=scheduled_start_utc
        )

        recording_started_monotonic = time.monotonic()
        recording_epoch = time.time()
        recording_utc = self.get_utc_timestamp()

        with self._stream_condition:

            start_sample = int(
                self._stream_sample_counter
            )

        end_sample_exclusive = (
            start_sample
            +
            frame_count
        )

        self.log(
            (
                f"Extracting {duration_sec:.3f}s from "
                f"continuous stream: "
                f"samples={start_sample}:"
                f"{end_sample_exclusive}"
            )
        )

        available = self._wait_for_continuous_samples(
            end_sample_exclusive=end_sample_exclusive,
            timeout_seconds=duration_sec + 5.0
        )

        if not available:
            raise RuntimeError(
                "Timed out waiting for continuous audio samples"
            )

        audio, status_events = (
            self._read_continuous_samples(
                start_sample=start_sample,
                end_sample_exclusive=(
                    end_sample_exclusive
                )
            )
        )

        recording_finished_monotonic = time.monotonic()

        self.write_wav(
            paths["wav_path"],
            audio
        )

        spectrogram_path = None

        if self.write_file_spectrogram:

            spectrogram_path = self.generate_spectrogram(
                wav_path=paths["wav_path"],
                spectrogram_path=paths[
                    "spectrogram_path"
                ],
                audio=audio
            )

        actual_duration_sec = (
            recording_finished_monotonic
            -
            recording_started_monotonic
        )

        start_error_ms = None

        if scheduled_start_epoch is not None:

            try:

                start_error_ms = (
                    recording_epoch
                    -
                    float(
                        scheduled_start_epoch
                    )
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
            "started_monotonic": (
                recording_started_monotonic
            ),
            "finished_monotonic": (
                recording_finished_monotonic
            ),
            "actual_duration_sec": (
                actual_duration_sec
            ),
            "start_error_ms": start_error_ms,
            "device": self.device,

            "recording_engine": (
                "continuous_pps"
            ),
            "continuous_stream": True,
            "stream_start_sample": start_sample,
            "stream_end_sample_exclusive": (
                end_sample_exclusive
            ),
            "stream_status_events": status_events,
            "stream_status_event_count": len(
                status_events
            ),
            "stream_callback_count": (
                self._stream_callback_count
            ),
            "stream_sample_counter": (
                self._stream_sample_counter
            ),
            "stream_started_monotonic_ns": (
                self._stream_started_monotonic_ns
            ),
            "stream_started_realtime_ns": (
                self._stream_started_realtime_ns
            )
        }

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
        
        if self.recording_engine == "continuous_pps":

            return self.record_from_continuous_stream(
                duration_sec=duration_sec,
                recording_type=recording_type,
                request_id=request_id,
                pps_state=pps_state,
                sync_source=sync_source,
                scheduled_start_epoch=(
                    scheduled_start_epoch
                ),
                scheduled_start_utc=(
                    scheduled_start_utc
                ),
                window_second=window_second
            )
        
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
