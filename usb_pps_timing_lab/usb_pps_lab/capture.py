from __future__ import annotations

import json
import queue
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import sounddevice as sd
import soundfile as sf

from .common import atomic_json_write, append_ndjson, system_identity, utc_now_iso
from .pps import PpsGnssMonitor


@dataclass
class AudioBlock:
    first_sample: int
    frame_count: int
    data: np.ndarray
    input_buffer_adc_time: float
    current_time: float
    callback_monotonic_ns: int
    callback_realtime_ns: int
    estimated_adc_monotonic_ns: int
    status: str


class ContinuousCapture:
    def __init__(self, config: dict[str, Any], config_path: Path, logger: Callable[[str], None] = print) -> None:
        self.config = config
        self.config_path = config_path
        self.logger = logger

        self.node_id = str(config["node_id"])
        audio = config["audio"]
        session = config["session"]
        self.device = audio["device"]
        self.sample_rate = int(audio["sample_rate_hz"])
        self.channels = int(audio["channels"])
        self.dtype = str(audio["dtype"])
        self.block_frames = int(audio["block_frames"])
        self.chunk_frames = max(self.block_frames, int(round(float(audio["chunk_seconds"]) * self.sample_rate)))
        self.latency = audio.get("latency", "low")
        self.queue_blocks = int(audio.get("queue_blocks", 512))

        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        root_directory = Path(session["root_directory"])
        if not root_directory.is_absolute():
            root_directory = self.config_path.parent / root_directory
        self.session_directory = (root_directory / f"{self.node_id}_{timestamp}").resolve()
        self.audio_directory = self.session_directory / "audio"
        self.audio_directory.mkdir(parents=True, exist_ok=False)

        self.blocks_path = self.session_directory / "audio_blocks.ndjson"
        self.chunks_path = self.session_directory / "audio_chunks.ndjson"
        self.continuity_path = self.session_directory / "continuity_events.ndjson"
        self.session_path = self.session_directory / "session.json"

        self._queue: queue.Queue[AudioBlock | None] = queue.Queue(maxsize=self.queue_blocks)
        self._stop = threading.Event()
        self._writer_thread = threading.Thread(target=self._writer_loop, name="audio-writer", daemon=True)
        self._sample_counter = 0
        self._callback_count = 0
        self._callback_queue_drops = 0
        self._status_count = 0
        self._stream: sd.InputStream | None = None
        self._telemetry_thread: threading.Thread | None = None
        self._stream_started_monotonic_ns: int | None = None
        self._stream_stopped_monotonic_ns: int | None = None

        pps_cfg = config["pps"]
        gnss_cfg = config["gnss"]
        self.pps_monitor = PpsGnssMonitor(
            assert_path=Path(pps_cfg["assert_path"]),
            poll_interval_ms=float(pps_cfg["poll_interval_ms"]),
            output_directory=self.session_directory,
            gnss_enabled=bool(gnss_cfg.get("enabled", True)),
            serial_device=str(gnss_cfg.get("serial_device", "/dev/ttyACM0")),
            baud=int(gnss_cfg.get("baud", 38400)),
            pairing_window_ms=float(gnss_cfg.get("pairing_window_ms", 750.0)),
            allow_system_time_fallback=bool(gnss_cfg.get("allow_system_time_fallback", True)),
            logger=logger,
        )

    def run(self, duration_seconds: float | None = None) -> Path:
        self._write_initial_session()
        self._writer_thread.start()
        self.pps_monitor.start()
        telemetry_cfg = self.config.get("telemetry", {})
        if bool(telemetry_cfg.get("enabled", True)):
            self._telemetry_thread = threading.Thread(target=self._telemetry_loop, name="telemetry", daemon=True)
            self._telemetry_thread.start()

        previous_sigint = signal.getsignal(signal.SIGINT)
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def request_stop(signum: int, frame: Any) -> None:
            self.logger(f"\n[CAPTURE] Signal {signum} received; stopping cleanly.")
            self._stop.set()

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)

        try:
            device_info = sd.query_devices(self.device, "input")
            self._update_session_device_info(device_info)
            self.logger(f"[AUDIO] Device: {device_info['name']}")
            self.logger(f"[AUDIO] {self.sample_rate} Hz, {self.channels} channel(s), {self.dtype}, block={self.block_frames}")
            self.logger(f"[SESSION] {self.session_directory}")

            self._stream = sd.InputStream(
                device=self.device,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                blocksize=self.block_frames,
                latency=self.latency,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._stream_started_monotonic_ns = time.monotonic_ns()
            start_wait = time.monotonic()

            while not self._stop.is_set():
                if duration_seconds is not None and time.monotonic() - start_wait >= duration_seconds:
                    self._stop.set()
                    break
                time.sleep(0.2)
        finally:
            if self._stream is not None:
                try:
                    self._stream.stop()
                finally:
                    self._stream.close()
            self._stream_stopped_monotonic_ns = time.monotonic_ns()
            self.pps_monitor.stop()
            if self._telemetry_thread is not None:
                self._telemetry_thread.join(timeout=3.0)
            self._queue.put(None)
            self._writer_thread.join(timeout=10.0)
            self._write_final_session()
            signal.signal(signal.SIGINT, previous_sigint)
            signal.signal(signal.SIGTERM, previous_sigterm)

        self.logger("[CAPTURE] Session complete.")
        return self.session_directory

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
        callback_monotonic_ns = time.monotonic_ns()
        callback_realtime_ns = time.time_ns()
        first_sample = self._sample_counter
        self._sample_counter += int(frames)
        self._callback_count += 1

        status_text = str(status) if status else ""
        if status:
            self._status_count += 1

        input_adc = float(time_info.inputBufferAdcTime)
        current_time = float(time_info.currentTime)
        estimated_adc_monotonic_ns = int(round(callback_monotonic_ns + (input_adc - current_time) * 1e9))

        block = AudioBlock(
            first_sample=first_sample,
            frame_count=int(frames),
            data=indata.copy(),
            input_buffer_adc_time=input_adc,
            current_time=current_time,
            callback_monotonic_ns=callback_monotonic_ns,
            callback_realtime_ns=callback_realtime_ns,
            estimated_adc_monotonic_ns=estimated_adc_monotonic_ns,
            status=status_text,
        )
        try:
            self._queue.put_nowait(block)
        except queue.Full:
            self._callback_queue_drops += 1

    def _writer_loop(self) -> None:
        chunk_index = 0
        chunk_file: sf.SoundFile | None = None
        chunk_path: Path | None = None
        chunk_start_sample: int | None = None
        chunk_frames_written = 0
        expected_sample: int | None = None

        def close_chunk() -> None:
            nonlocal chunk_file, chunk_path, chunk_start_sample, chunk_frames_written
            if chunk_file is None or chunk_path is None or chunk_start_sample is None:
                return
            chunk_file.flush()
            chunk_file.close()
            append_ndjson(
                self.chunks_path,
                {
                    "chunk_index": chunk_index - 1,
                    "path": str(chunk_path.relative_to(self.session_directory)),
                    "start_sample": chunk_start_sample,
                    "frame_count": chunk_frames_written,
                    "end_sample_exclusive": chunk_start_sample + chunk_frames_written,
                },
            )
            chunk_file = None
            chunk_path = None
            chunk_start_sample = None
            chunk_frames_written = 0

        while True:
            item = self._queue.get()
            if item is None:
                break
            block = item
            if expected_sample is None:
                expected_sample = block.first_sample

            gap_frames = block.first_sample - expected_sample
            if gap_frames < 0:
                append_ndjson(self.continuity_path, {"type": "overlap_or_reorder", "expected_sample": expected_sample, "received_first_sample": block.first_sample, "difference_frames": gap_frames})
                continue

            pending_parts: list[np.ndarray] = []
            if gap_frames > 0:
                pending_parts.append(np.zeros((gap_frames, self.channels), dtype=np.dtype(self.dtype)))
                append_ndjson(self.continuity_path, {"type": "inserted_silence_for_missing_callback_data", "start_sample": expected_sample, "frame_count": gap_frames})
            pending_parts.append(block.data)
            combined = np.concatenate(pending_parts, axis=0) if len(pending_parts) > 1 else pending_parts[0]

            write_offset = 0
            combined_start_sample = block.first_sample - gap_frames
            while write_offset < len(combined):
                if chunk_file is None:
                    chunk_path = self.audio_directory / f"chunk_{chunk_index:06d}.wav"
                    chunk_start_sample = combined_start_sample + write_offset
                    chunk_file = sf.SoundFile(
                        str(chunk_path),
                        mode="w",
                        samplerate=self.sample_rate,
                        channels=self.channels,
                        subtype="PCM_16" if self.dtype == "int16" else "FLOAT",
                        format="WAV",
                    )
                    chunk_index += 1

                capacity = self.chunk_frames - chunk_frames_written
                take = min(capacity, len(combined) - write_offset)
                chunk_file.write(combined[write_offset:write_offset + take])
                chunk_frames_written += take
                write_offset += take
                if chunk_frames_written >= self.chunk_frames:
                    close_chunk()

            append_ndjson(
                self.blocks_path,
                {
                    "first_sample": block.first_sample,
                    "frame_count": block.frame_count,
                    "input_buffer_adc_time": block.input_buffer_adc_time,
                    "current_time": block.current_time,
                    "callback_monotonic_ns": block.callback_monotonic_ns,
                    "callback_realtime_ns": block.callback_realtime_ns,
                    "estimated_adc_monotonic_ns": block.estimated_adc_monotonic_ns,
                    "status": block.status,
                },
            )
            expected_sample = block.first_sample + block.frame_count

        close_chunk()


    def _telemetry_loop(self) -> None:
        telemetry_cfg = self.config.get("telemetry", {})
        interval = max(0.2, float(telemetry_cfg.get("interval_seconds", 1.0)))
        temperature_path = Path(telemetry_cfg.get("cpu_temperature_path", "/sys/class/thermal/thermal_zone0/temp"))
        while not self._stop.is_set():
            record = {
                "realtime_ns": time.time_ns(),
                "monotonic_ns": time.monotonic_ns(),
                "cpu_temperature_c": None,
            }
            try:
                raw = temperature_path.read_text(encoding="utf-8").strip()
                value = float(raw)
                record["cpu_temperature_c"] = value / 1000.0 if abs(value) > 500.0 else value
            except Exception as error:
                record["temperature_error"] = repr(error)
            append_ndjson(self.session_directory / "telemetry.ndjson", record)
            self._stop.wait(interval)

    def _update_session_device_info(self, device_info: Any) -> None:
        try:
            existing = json.loads(self.session_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        existing["audio_device"] = {
            "requested_device": self.device,
            "name": device_info["name"],
            "hostapi": int(device_info["hostapi"]),
            "max_input_channels": int(device_info["max_input_channels"]),
            "default_sample_rate": float(device_info["default_samplerate"]),
            "default_low_input_latency": float(device_info["default_low_input_latency"]),
            "default_high_input_latency": float(device_info["default_high_input_latency"]),
        }
        atomic_json_write(self.session_path, existing)

    def _write_initial_session(self) -> None:
        atomic_json_write(
            self.session_path,
            {
                "schema": "usb_pps_timing_session_v1",
                "state": "recording",
                "created_utc": utc_now_iso(),
                "node_id": self.node_id,
                "system": system_identity(),
                "config_path": str(self.config_path.resolve()),
                "config": self.config,
                "process_start_realtime_ns": time.time_ns(),
                "process_start_monotonic_ns": time.monotonic_ns(),
                "timing_notice": "PortAudio ADC timestamps and LinuxPPS timestamps are being related in software. The resulting absolute ADC-to-PPS offset must be validated experimentally.",
            },
        )

    def _write_final_session(self) -> None:
        try:
            existing = json.loads(self.session_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        observations = self.pps_monitor.snapshot()
        existing.update(
            {
                "state": "complete",
                "completed_utc": utc_now_iso(),
                "stream_started_monotonic_ns": self._stream_started_monotonic_ns,
                "stream_stopped_monotonic_ns": self._stream_stopped_monotonic_ns,
                "total_stream_samples": self._sample_counter,
                "total_callbacks": self._callback_count,
                "callback_status_count": self._status_count,
                "callback_queue_drops": self._callback_queue_drops,
                "pps_observation_count": len(observations),
                "pps_paired_count": sum(item.utc_ns is not None for item in observations),
                "nominal_duration_seconds": self._sample_counter / self.sample_rate if self.sample_rate > 0 else None,
            }
        )
        atomic_json_write(self.session_path, existing)
