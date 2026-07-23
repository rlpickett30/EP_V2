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
        self.window_pre_roll_seconds = float(
            self.continuous_capture_config.get(
                "window_pre_roll_seconds",
                0.5
            )
        )

        self.window_post_roll_seconds = float(
            self.continuous_capture_config.get(
                "window_post_roll_seconds",
                0.5
            )
        )

        self.write_guarded_raw_window = bool(
            self.continuous_capture_config.get(
                "write_guarded_raw_window",
                True
            )
        )
        self._stream = None
        self._stream_condition = threading.Condition()
        self._stream_blocks = deque()
        self._stream_sample_counter = 0
        self._stream_callback_count = 0
        self._stream_status_count = 0
        self._stream_started_monotonic_ns = None
        self._stream_started_realtime_ns = None
        self._stream_instance_id = None
        self._stream_timing_segment_id = 0

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
            self._stream_instance_id = uuid.uuid4().hex
            self._stream_timing_segment_id = 0

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
    
    def snapshot_stream_position(self):

        if not self.continuous_stream_active():
            raise RuntimeError(
                "Continuous microphone stream is not active"
            )

        snapshot_monotonic_ns = time.monotonic_ns()
        snapshot_realtime_ns = time.time_ns()

        with self._stream_condition:

            latest_block = (
                self._stream_blocks[-1]
                if self._stream_blocks
                else None
            )

            oldest_block = (
                self._stream_blocks[0]
                if self._stream_blocks
                else None
            )

            return {
                "stream_instance_id": (
                    self._stream_instance_id
                ),
                "timing_segment_id": int(
                    self._stream_timing_segment_id
                ),
                "sample_index": int(
                    self._stream_sample_counter
                ),
                "callback_count": int(
                    self._stream_callback_count
                ),
                "status_count": int(
                    self._stream_status_count
                ),
                "snapshot_monotonic_ns": (
                    snapshot_monotonic_ns
                ),
                "snapshot_realtime_ns": (
                    snapshot_realtime_ns
                ),
                "oldest_retained_sample": (
                    int(
                        oldest_block[
                            "first_sample"
                        ]
                    )
                    if oldest_block
                    else None
                ),
                "latest_block_callback_index": (
                    int(
                        latest_block[
                            "callback_index"
                        ]
                    )
                    if latest_block
                    else None
                ),
                "latest_block_timing_segment_id": (
                    int(
                        latest_block[
                            "timing_segment_id"
                        ]
                    )
                    if latest_block
                    else None
                ),
                "latest_block_first_sample": (
                    int(
                        latest_block[
                            "first_sample"
                        ]
                    )
                    if latest_block
                    else None
                ),
                "latest_block_end_sample_exclusive": (
                    int(
                        latest_block[
                            "end_sample_exclusive"
                        ]
                    )
                    if latest_block
                    else None
                ),
                "latest_block_adc_monotonic_ns": (
                    int(
                        latest_block[
                            "estimated_adc_monotonic_ns"
                        ]
                    )
                    if latest_block
                    else None
                ),
                "latest_block_status": (
                    latest_block.get(
                        "status",
                        ""
                    )
                    if latest_block
                    else ""
                )
            }
        
    def wait_for_callback_after_index(
        self,
        callback_index,
        timeout_seconds
    ):
        """
        Wait until the continuous stream delivers a callback newer than
        callback_index, the stream stops, or the timeout expires.

        This is a low-level condition wait only. It does not inspect PPS
        events, resolve anchors, or make synchronization decisions.
        """

        try:
            callback_index = int(callback_index)

        except (TypeError, ValueError):
            raise ValueError(
                "callback_index must be an integer"
            )

        timeout_seconds = float(
            timeout_seconds
        )

        if timeout_seconds < 0:
            raise ValueError(
                "timeout_seconds must not be negative"
            )

        deadline = time.monotonic() + timeout_seconds

        with self._stream_condition:

            while (
                self._stream_callback_count
                <=
                callback_index
            ):

                stream = self._stream

                if stream is None or not stream.active:
                    return False

                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    return False

                self._stream_condition.wait(
                    timeout=remaining
                )

            return True

    def lookup_sample_position_at_monotonic_ns(
        self,
        target_monotonic_ns,
        max_extrapolation_blocks=1.5,
        minimum_rate_ratio=0.90,
        maximum_rate_ratio=1.10
    ):
        """
        Map one monotonic timestamp to the continuous sample timeline.

        This is a read-only lookup. It does not fit a clock model, alter
        recording boundaries, or declare the microphone synchronized.
        """

        try:
            target_ns = int(target_monotonic_ns)

        except (TypeError, ValueError):
            return {
                "accepted": False,
                "lookup_method": "rejected",
                "quality_reasons": [
                    "invalid_target_monotonic_ns"
                ],
                "target_monotonic_ns": None,
                "reference_blocks": {}
            }

        if target_ns <= 0:
            return {
                "accepted": False,
                "lookup_method": "rejected",
                "quality_reasons": [
                    "invalid_target_monotonic_ns"
                ],
                "target_monotonic_ns": target_ns,
                "reference_blocks": {}
            }

        max_extrapolation_blocks = float(
            max_extrapolation_blocks
        )

        minimum_rate_ratio = float(
            minimum_rate_ratio
        )

        maximum_rate_ratio = float(
            maximum_rate_ratio
        )

        if max_extrapolation_blocks <= 0:
            raise ValueError(
                "max_extrapolation_blocks must be positive"
            )

        if not (
            0
            <
            minimum_rate_ratio
            <
            maximum_rate_ratio
        ):
            raise ValueError(
                "Rate-ratio limits must be positive and ordered"
            )

        lookup_monotonic_ns = time.monotonic_ns()
        lookup_realtime_ns = time.time_ns()

        with self._stream_condition:

            stream_active = bool(
                self._stream is not None
                and
                self._stream.active
            )

            blocks = tuple(
                self._stream_blocks
            )

            stream_instance_id = (
                self._stream_instance_id
            )

            callback_count = int(
                self._stream_callback_count
            )

            sample_counter = int(
                self._stream_sample_counter
            )

            status_count = int(
                self._stream_status_count
            )

        def evidence(block):

            if block is None:
                return None

            keys = (
                "stream_instance_id",
                "callback_index",
                "timing_segment_id",
                "first_sample",
                "end_sample_exclusive",
                "frame_count",
                "input_buffer_adc_time",
                "current_time",
                "callback_monotonic_ns",
                "callback_realtime_ns",
                "estimated_adc_monotonic_ns",
                "status"
            )

            return {
                key: block.get(key)
                for key in keys
            }

        base = {
            "accepted": False,
            "lookup_method": "rejected",
            "quality_reasons": [],
            "target_monotonic_ns": target_ns,
            "lookup_monotonic_ns": (
                lookup_monotonic_ns
            ),
            "lookup_realtime_ns": (
                lookup_realtime_ns
            ),
            "stream_active_at_lookup": (
                stream_active
            ),
            "stream_instance_id": (
                stream_instance_id
            ),
            "timing_segment_id": None,
            "stream_callback_count_at_lookup": (
                callback_count
            ),
            "stream_sample_counter_at_lookup": (
                sample_counter
            ),
            "stream_status_count_at_lookup": (
                status_count
            ),
            "retained_callback_count": len(
                blocks
            ),
            "nominal_sample_rate_hz": float(
                self.sample_rate
            ),
            "sample_position_fractional": None,
            "sample_position_rounded": None,
            "rounding_delta_samples": None,
            "local_rate_hz": None,
            "interpolation_fraction": None,
            "extrapolation_distance_ns": None,
            "extrapolation_limit_ns": None,
            "reference_time_span_ns": None,
            "reference_sample_span": None,
            "reference_blocks": {}
        }

        def reject(
            reasons,
            left=None,
            right=None,
            **extra
        ):

            if isinstance(reasons, str):
                reasons = [reasons]

            result = dict(base)

            result["quality_reasons"] = list(
                dict.fromkeys(reasons)
            )

            if (
                left is not None
                or
                right is not None
            ):
                result["reference_blocks"] = {
                    "left": evidence(left),
                    "right": evidence(right)
                }

            result.update(extra)

            return result

        if not stream_active:
            return reject(
                "continuous_stream_inactive"
            )

        if len(blocks) < 2:
            return reject(
                "insufficient_callback_history"
            )

        left = None
        right = None
        method = None

        for index in range(
            len(blocks) - 1
        ):

            candidate_left = blocks[index]

            candidate_right = blocks[
                index + 1
            ]

            try:
                left_ns = int(
                    candidate_left[
                        "estimated_adc_monotonic_ns"
                    ]
                )

                right_ns = int(
                    candidate_right[
                        "estimated_adc_monotonic_ns"
                    ]
                )

            except (
                KeyError,
                TypeError,
                ValueError
            ):
                continue

            if (
                left_ns
                <=
                target_ns
                <=
                right_ns
            ):
                left = candidate_left
                right = candidate_right

                method = (
                    "callback_pair_interpolation"
                )

                break

        if left is None:

            try:
                oldest_ns = int(
                    blocks[0][
                        "estimated_adc_monotonic_ns"
                    ]
                )

                latest_ns = int(
                    blocks[-1][
                        "estimated_adc_monotonic_ns"
                    ]
                )

            except (
                KeyError,
                TypeError,
                ValueError
            ):
                return reject(
                    "retained_callback_times_missing"
                )

            if target_ns < oldest_ns:
                return reject(
                    (
                        "target_precedes_retained_"
                        "callback_history"
                    ),
                    blocks[0],
                    blocks[1]
                )

            if target_ns > latest_ns:

                left = blocks[-2]
                right = blocks[-1]

                method = (
                    "callback_pair_extrapolation"
                )

            else:
                return reject(
                    "no_bracketing_callback_pair"
                )

        reasons = []

        if not (
            left.get("stream_instance_id")
            ==
            right.get("stream_instance_id")
            ==
            stream_instance_id
        ):
            reasons.append(
                "reference_stream_instance_mismatch"
            )

        try:

            if (
                int(
                    right["callback_index"]
                )
                !=
                int(
                    left["callback_index"]
                )
                +
                1
            ):
                reasons.append(
                    (
                        "reference_callbacks_"
                        "not_consecutive"
                    )
                )

        except (
            KeyError,
            TypeError,
            ValueError
        ):
            reasons.append(
                "reference_callback_index_missing"
            )

        try:

            if (
                int(
                    left[
                        "end_sample_exclusive"
                    ]
                )
                !=
                int(
                    right["first_sample"]
                )
            ):
                reasons.append(
                    (
                        "reference_sample_ranges_"
                        "not_contiguous"
                    )
                )

        except (
            KeyError,
            TypeError,
            ValueError
        ):
            reasons.append(
                "reference_sample_range_missing"
            )

        left_segment = left.get(
            "timing_segment_id"
        )

        right_segment = right.get(
            "timing_segment_id"
        )

        if (
            left_segment is None
            or
            left_segment != right_segment
        ):
            reasons.append(
                (
                    "reference_timing_segment_"
                    "mismatch"
                )
            )

        left_status = str(
            left.get("status", "")
        ).strip()

        right_status = str(
            right.get("status", "")
        ).strip()

        if left_status or right_status:
            reasons.append(
                "reference_block_contains_status"
            )

        try:
            left_ns = int(
                left[
                    "estimated_adc_monotonic_ns"
                ]
            )

            right_ns = int(
                right[
                    "estimated_adc_monotonic_ns"
                ]
            )

            left_sample = int(
                left["first_sample"]
            )

            right_sample = int(
                right["first_sample"]
            )

        except (
            KeyError,
            TypeError,
            ValueError
        ):
            return reject(
                reasons
                +
                [
                    (
                        "reference_timing_"
                        "evidence_missing"
                    )
                ],
                left,
                right
            )

        time_span_ns = (
            right_ns
            -
            left_ns
        )

        sample_span = (
            right_sample
            -
            left_sample
        )

        if time_span_ns <= 0:
            reasons.append(
                (
                    "reference_adc_time_"
                    "not_increasing"
                )
            )

        if sample_span <= 0:
            reasons.append(
                (
                    "reference_sample_position_"
                    "not_increasing"
                )
            )

        local_rate_hz = None

        if (
            time_span_ns > 0
            and
            sample_span > 0
        ):
            local_rate_hz = (
                sample_span
                *
                1e9
                /
                time_span_ns
            )

            minimum_rate_hz = (
                self.sample_rate
                *
                minimum_rate_ratio
            )

            maximum_rate_hz = (
                self.sample_rate
                *
                maximum_rate_ratio
            )

            if not (
                minimum_rate_hz
                <=
                local_rate_hz
                <=
                maximum_rate_hz
            ):
                reasons.append(
                    (
                        "local_rate_outside_"
                        "sanity_range"
                    )
                )

        extrapolation_distance_ns = 0

        extrapolation_limit_ns = int(
            round(
                max_extrapolation_blocks
                *
                max(
                    time_span_ns,
                    0
                )
            )
        )

        if (
            method
            ==
            "callback_pair_extrapolation"
        ):
            extrapolation_distance_ns = (
                target_ns
                -
                right_ns
            )

            if extrapolation_distance_ns < 0:
                reasons.append(
                    "invalid_extrapolation_direction"
                )

            if (
                extrapolation_distance_ns
                >
                extrapolation_limit_ns
            ):
                reasons.append(
                    (
                        "extrapolation_distance_"
                        "exceeded"
                    )
                )

        if reasons:
            return reject(
                reasons,
                left,
                right,
                timing_segment_id=left_segment,
                local_rate_hz=local_rate_hz,
                extrapolation_distance_ns=(
                    extrapolation_distance_ns
                ),
                extrapolation_limit_ns=(
                    extrapolation_limit_ns
                ),
                reference_time_span_ns=(
                    time_span_ns
                ),
                reference_sample_span=(
                    sample_span
                )
            )

        fraction = (
            target_ns
            -
            left_ns
        ) / time_span_ns

        fractional_sample = (
            left_sample
            +
            fraction
            *
            sample_span
        )

        rounded_sample = int(
            round(
                fractional_sample
            )
        )

        result = dict(base)

        result.update(
            {
                "accepted": True,
                "lookup_method": method,
                "quality_reasons": [],
                "stream_instance_id": (
                    left.get(
                        "stream_instance_id"
                    )
                ),
                "timing_segment_id": (
                    left_segment
                ),
                "sample_position_fractional": (
                    fractional_sample
                ),
                "sample_position_rounded": (
                    rounded_sample
                ),
                "rounding_delta_samples": (
                    rounded_sample
                    -
                    fractional_sample
                ),
                "local_rate_hz": (
                    local_rate_hz
                ),
                "interpolation_fraction": (
                    fraction
                ),
                "extrapolation_distance_ns": (
                    extrapolation_distance_ns
                ),
                "extrapolation_limit_ns": (
                    extrapolation_limit_ns
                ),
                "reference_time_span_ns": (
                    time_span_ns
                ),
                "reference_sample_span": (
                    sample_span
                ),
                "reference_blocks": {
                    "left": evidence(left),
                    "right": evidence(right)
                }
            }
        )

        return result   
    def read_guarded_window_from_boundary(
        self,
        boundary_snapshot,
        core_duration_sec
    ):

        if not isinstance(boundary_snapshot, dict):
            raise TypeError(
                "boundary_snapshot must be a dictionary"
            )

        boundary_sample = int(
            boundary_snapshot["sample_index"]
        )

        core_duration_sec = float(
            core_duration_sec
        )

        if core_duration_sec <= 0:
            raise ValueError(
                "core_duration_sec must be positive"
            )

        pre_roll_frames = int(
            round(
                self.window_pre_roll_seconds
                *
                self.sample_rate
            )
        )

        core_frames = int(
            round(
                core_duration_sec
                *
                self.sample_rate
            )
        )

        post_roll_frames = int(
            round(
                self.window_post_roll_seconds
                *
                self.sample_rate
            )
        )

        core_start_sample = (
            boundary_sample
            -
            core_frames
        )

        core_end_sample_exclusive = (
            boundary_sample
        )

        guarded_start_sample = (
            core_start_sample
            -
            pre_roll_frames
        )

        guarded_end_sample_exclusive = (
            core_end_sample_exclusive
            +
            post_roll_frames
        )

        if guarded_start_sample < 0:
            raise RuntimeError(
                (
                    "The continuous stream does not yet "
                    "contain enough history for the "
                    "requested guarded window"
                )
            )

        available = self._wait_for_continuous_samples(
            end_sample_exclusive=(
                guarded_end_sample_exclusive
            ),
            timeout_seconds=(
                self.window_post_roll_seconds
                +
                5.0
            )
        )

        if not available:
            raise RuntimeError(
                (
                    "Timed out waiting for guarded "
                    "window post-roll samples"
                )
            )

        guarded_audio, status_events = (
            self._read_continuous_samples(
                start_sample=guarded_start_sample,
                end_sample_exclusive=(
                    guarded_end_sample_exclusive
                )
            )
        )

        core_offset_start = pre_roll_frames

        core_offset_stop = (
            core_offset_start
            +
            core_frames
        )

        core_audio = guarded_audio[
            core_offset_start:
            core_offset_stop
        ]

        return {
            "boundary_snapshot": dict(
                boundary_snapshot
            ),

            "boundary_sample": boundary_sample,

            "guarded_start_sample": (
                guarded_start_sample
            ),
            "guarded_end_sample_exclusive": (
                guarded_end_sample_exclusive
            ),
            "guarded_frame_count": int(
                len(guarded_audio)
            ),
            "guarded_duration_sec": (
                len(guarded_audio)
                /
                self.sample_rate
            ),

            "core_start_sample": (
                core_start_sample
            ),
            "core_end_sample_exclusive": (
                core_end_sample_exclusive
            ),
            "core_frame_count": int(
                len(core_audio)
            ),
            "core_duration_sec": (
                len(core_audio)
                /
                self.sample_rate
            ),

            "pre_roll_frames": pre_roll_frames,
            "post_roll_frames": post_roll_frames,

            "pre_roll_seconds": (
                self.window_pre_roll_seconds
            ),
            "post_roll_seconds": (
                self.window_post_roll_seconds
            ),

            "guarded_audio": guarded_audio,
            "core_audio": core_audio,

            "stream_status_events": status_events,
            "stream_status_event_count": len(
                status_events
            )
        }
    
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
        normalized_status = status_text.strip().lower()

        timing_discontinuity = bool(
            "overflow" in normalized_status
            or
            "underflow" in normalized_status
        )

        with self._stream_condition:

            first_sample = self._stream_sample_counter
            callback_index = self._stream_callback_count + 1

            if timing_discontinuity:
                self._stream_timing_segment_id += 1

            timing_segment_id = (
                self._stream_timing_segment_id
            )

            self._stream_sample_counter += int(
                frames
            )

            self._stream_callback_count = callback_index

            if status:
                self._stream_status_count += 1

            self._stream_blocks.append(
                {
                    "stream_instance_id": (
                        self._stream_instance_id
                    ),
                    "callback_index": callback_index,
                    "timing_segment_id": (
                        timing_segment_id
                    ),
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

        guarded_wav_path = (
            recording_dir
            /
            f"{recording_id}_guarded_raw.wav"
        )

        metadata_path = recording_dir / f"{recording_id}.json"
        spectrogram_path = recording_dir / f"{recording_id}.png"

        return {
            "recording_id": recording_id,
            "wav_path": wav_path,
            "guarded_wav_path": guarded_wav_path,
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
            
    def write_boundary_window_files(
        self,
        paths,
        window
    ):

        if not isinstance(paths, dict):
            raise TypeError(
                "paths must be a dictionary"
            )

        if not isinstance(window, dict):
            raise TypeError(
                "window must be a dictionary"
            )

        core_audio = window.get(
            "core_audio"
        )

        guarded_audio = window.get(
            "guarded_audio"
        )

        if core_audio is None:
            raise ValueError(
                "window does not contain core_audio"
            )

        if guarded_audio is None:
            raise ValueError(
                "window does not contain guarded_audio"
            )

        core_wav_path = paths["wav_path"]

        self.write_wav(
            core_wav_path,
            core_audio
        )

        guarded_wav_path = None

        if self.write_guarded_raw_window:

            guarded_wav_path = paths[
                "guarded_wav_path"
            ]

            self.write_wav(
                guarded_wav_path,
                guarded_audio
            )

        return {
            "wav_path": core_wav_path,
            "guarded_wav_path": guarded_wav_path,
            "core_frame_count": int(
                len(core_audio)
            ),
            "guarded_frame_count": int(
                len(guarded_audio)
            ),
            "core_duration_sec": (
                len(core_audio)
                /
                self.sample_rate
            ),
            "guarded_duration_sec": (
                len(guarded_audio)
                /
                self.sample_rate
            )
        }
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