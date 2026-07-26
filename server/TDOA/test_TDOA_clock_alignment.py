# ============================================================
# test_TDOA_clock_alignment.py
#
# EnviroPulse V2
#
# Subsystem:
#   Server TDOA
#
# Role:
#   Block 8 clock-alignment checkpoint
#
# Purpose:
#   Prove guarded WAV files are mapped onto one exact UTC sample grid.
#
# Proves:
#   - scheduled_start_utc is the alignment authority
#   - recording_id remains opaque lineage
#   - Independent sample rates and start offsets align to one grid
#   - Immutable raw WAV hashes survive correction
#   - Every derived output has identical 15-second grid properties
#   - Invalid timing evidence is rejected before calculation
#   - Four aligned recordings may survive one rejected member
#
# Does NOT:
#   - Validate physical ADC-to-PPS offset on hardware
#   - Perform TDOA localization
#   - Change node recording behavior
#
# ============================================================

import copy
import hashlib
import json
import sys
import tempfile
import unittest
import wave

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np


SERVER_ROOT = Path(
    __file__
).resolve().parents[
    1
]

if str(
    SERVER_ROOT
) not in sys.path:
    sys.path.insert(
        0,
        str(
            SERVER_ROOT
        )
    )


from server_event_bus import EventBus
from TDOA.TDOA_clock_alignment_manager import (
    TDOAClockAlignmentManager
)
from TDOA.TDOA_dispatcher import TDOADispatcher


class FakeCalculationManager:

    def __init__(
        self
    ):

        self.calls = []

    def tdoa_estimate(
        self,
        candidate,
        recording_events=None
    ):

        self.calls.append(
            {
                "candidate": candidate,
                "recording_events": copy.deepcopy(
                    recording_events
                    or
                    []
                )
            }
        )

        return {
            "success": True,
            "candidate": candidate
        }


class TDOAClockAlignmentTests(
    unittest.TestCase
):

    SAMPLE_RATE_HZ = 8000
    TARGET_DURATION_SECONDS = 15.0
    GUARDED_DURATION_SECONDS = 16.0
    START_UTC = "2026-07-26T18:00:00Z"

    def setUp(
        self
    ):

        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )

        self.root = Path(
            self.temporary_directory.name
        )

        self.manager = TDOAClockAlignmentManager(
            config={
                "tdoa_subsystem": {
                    "minimum_tdoa_nodes": 4,
                    "default_sample_rate_hz": (
                        self.SAMPLE_RATE_HZ
                    )
                },
                "tdoa_clock_alignment": {
                    "target_sample_rate_hz": (
                        self.SAMPLE_RATE_HZ
                    ),
                    "target_duration_seconds": (
                        self.TARGET_DURATION_SECONDS
                    ),
                    "minimum_aligned_recordings": 4,
                    "maximum_model_residual_p95_us": (
                        1000.0
                    ),
                    "scheduled_time_tolerance_us": 10.0
                }
            }
        )

        self.start_datetime = datetime.fromisoformat(
            self.START_UTC.replace(
                "Z",
                "+00:00"
            )
        ).astimezone(
            timezone.utc
        )

        self.start_epoch = self.start_datetime.timestamp()

        self.start_utc_ns = int(
            round(
                self.start_epoch
                *
                1_000_000_000.0
            )
        )

    def tearDown(
        self
    ):

        self.temporary_directory.cleanup()

    # ========================================================
    # EXACT UTC GRID
    # ========================================================

    def test_independent_clocks_map_to_one_exact_utc_grid(
        self
    ):

        rates = [
            8002.4,
            7998.1,
            8000.8,
            7999.2,
        ]

        events = [
            self._recording_event(
                node_id=f"node_{index:02d}",
                effective_rate_hz=rate,
                recording_id=(
                    f"opaque-recording-{index}"
                )
            )
            for index, rate in enumerate(
                rates,
                start=1
            )
        ]

        raw_hashes = {
            event[
                "payload"
            ][
                "node_id"
            ]: self._sha256(
                Path(
                    event[
                        "payload"
                    ][
                        "server_wav_path"
                    ]
                )
            )
            for event in events
        }

        result = self.manager.align_complete_set(
            self._complete_set(
                events
            )
        )

        self.assertTrue(
            result[
                "success"
            ]
        )

        complete_set = result[
            "complete_set"
        ]

        self.assertEqual(
            complete_set[
                "schema_version"
            ],
            2
        )

        self.assertEqual(
            complete_set[
                "aligned_recording_count"
            ],
            4
        )

        self.assertEqual(
            complete_set[
                "clock_alignment"
            ][
                "target_grid"
            ][
                "target_frame_count"
            ],
            (
                self.SAMPLE_RATE_HZ
                *
                15
            )
        )

        peak_samples = []

        for aligned_event in complete_set[
            "recording_events"
        ]:

            payload = aligned_event[
                "payload"
            ]

            aligned_path = Path(
                payload[
                    "aligned_wav_path"
                ]
            )

            metadata_path = Path(
                payload[
                    "aligned_metadata_path"
                ]
            )

            self.assertTrue(
                aligned_path.is_file()
            )

            self.assertTrue(
                metadata_path.is_file()
            )

            with metadata_path.open(
                "r",
                encoding="utf-8"
            ) as metadata_file:

                alignment_metadata = json.load(
                    metadata_file
                )

            self.assertEqual(
                len(
                    alignment_metadata[
                        "nearby_pps_anchors"
                    ]
                ),
                2
            )

            self.assertIn(
                "sample_to_utc",
                alignment_metadata[
                    "clock_model"
                ]
            )

            with wave.open(
                str(
                    aligned_path
                ),
                "rb"
            ) as wav_file:

                self.assertEqual(
                    wav_file.getframerate(),
                    self.SAMPLE_RATE_HZ
                )

                self.assertEqual(
                    wav_file.getnchannels(),
                    1
                )

                self.assertEqual(
                    wav_file.getnframes(),
                    self.SAMPLE_RATE_HZ
                    *
                    15
                )

                aligned_audio = np.frombuffer(
                    wav_file.readframes(
                        wav_file.getnframes()
                    ),
                    dtype="<i2"
                )

            peak_samples.append(
                int(
                    np.argmax(
                        aligned_audio
                    )
                )
            )

            node_id = payload[
                "node_id"
            ]

            raw_path = Path(
                payload[
                    "raw_server_wav_path"
                ]
            )

            self.assertEqual(
                self._sha256(
                    raw_path
                ),
                raw_hashes[
                    node_id
                ]
            )

            self.assertEqual(
                payload[
                    "raw_wav_sha256"
                ],
                raw_hashes[
                    node_id
                ]
            )

            self.assertEqual(
                payload[
                    "alignment_evidence"
                ][
                    "target_grid"
                ][
                    "start_utc"
                ],
                "2026-07-26T18:00:00.000000Z"
            )

            self.assertEqual(
                payload[
                    "audio_correction_state"
                ],
                "utc_grid_aligned"
            )

        expected_peak_sample = int(
            round(
                6.25
                *
                self.SAMPLE_RATE_HZ
            )
        )

        self.assertTrue(
            all(
                abs(
                    peak_sample
                    -
                    expected_peak_sample
                )
                <=
                1
                for peak_sample in peak_samples
            )
        )

        self.assertLessEqual(
            max(
                peak_samples
            )
            -
            min(
                peak_samples
            ),
            1
        )

        self.assertEqual(
            [
                event[
                    "payload"
                ][
                    "recording_id"
                ]
                for event in complete_set[
                    "recording_events"
                ]
            ],
            [
                f"opaque-recording-{index}"
                for index in range(
                    1,
                    5
                )
            ]
        )

    # ========================================================
    # PARTIAL SET
    # ========================================================

    def test_five_raw_recordings_can_yield_four_aligned_recordings(
        self
    ):

        events = [
            self._recording_event(
                node_id=f"node_{index:02d}",
                effective_rate_hz=(
                    8000.0
                    +
                    index
                )
            )
            for index in range(
                1,
                6
            )
        ]

        events[
            -1
        ][
            "payload"
        ][
            "clock_model_quality"
        ] = "WARN"

        events[
            -1
        ][
            "payload"
        ][
            "clock_model"
        ][
            "quality"
        ][
            "status"
        ] = "WARN"

        events[
            -1
        ][
            "payload"
        ][
            "clock_model"
        ][
            "quality"
        ][
            "model_valid"
        ] = False

        result = self.manager.align_complete_set(
            self._complete_set(
                events
            )
        )

        self.assertTrue(
            result[
                "success"
            ]
        )

        complete_set = result[
            "complete_set"
        ]

        self.assertEqual(
            complete_set[
                "aligned_node_ids"
            ],
            [
                "node_01",
                "node_02",
                "node_03",
                "node_04",
            ]
        )

        self.assertEqual(
            complete_set[
                "alignment_rejected_node_ids"
            ],
            [
                "node_05"
            ]
        )

        rejected_result = result[
            "clock_alignment"
        ][
            "recording_results"
        ][
            -1
        ]

        self.assertEqual(
            rejected_result[
                "failure_reason"
            ],
            "clock_model_not_pass"
        )

    def test_channel_outlier_is_not_admitted_to_complete_set(
        self
    ):

        events = [
            self._recording_event(
                node_id=f"node_{index:02d}",
                effective_rate_hz=8000.0,
                channels=(
                    2
                    if index == 5
                    else
                    1
                )
            )
            for index in range(
                1,
                6
            )
        ]

        result = self.manager.align_complete_set(
            self._complete_set(
                events
            )
        )

        self.assertTrue(
            result[
                "success"
            ]
        )

        self.assertEqual(
            result[
                "complete_set"
            ][
                "aligned_node_ids"
            ],
            [
                "node_01",
                "node_02",
                "node_03",
                "node_04",
            ]
        )

        self.assertEqual(
            result[
                "clock_alignment"
            ][
                "recording_results"
            ][
                -1
            ][
                "failure_reason"
            ],
            "aligned_channel_count_mismatch"
        )

    def test_higher_rate_source_uses_bandlimited_resampling(
        self
    ):

        events = [
            self._recording_event(
                node_id=f"node_{index:02d}",
                effective_rate_hz=(
                    16000.0
                    +
                    index
                ),
                source_sample_rate_hz=16000
            )
            for index in range(
                1,
                5
            )
        ]

        result = self.manager.align_complete_set(
            self._complete_set(
                events
            )
        )

        self.assertTrue(
            result[
                "success"
            ]
        )

        self.assertTrue(
            all(
                recording_result[
                    "alignment_evidence"
                ][
                    "resampling"
                ][
                    "method"
                ]
                ==
                (
                    "zero_phase_lowpass_then_"
                    "linear_interpolation"
                )
                for recording_result in result[
                    "clock_alignment"
                ][
                    "recording_results"
                ]
            )
        )

    # ========================================================
    # GRID CONSENSUS
    # ========================================================

    def test_common_scheduled_start_wins_over_one_outlier(
        self
    ):

        events = [
            self._recording_event(
                node_id=f"node_{index:02d}",
                effective_rate_hz=8000.0
            )
            for index in range(
                1,
                6
            )
        ]

        outlier_payload = events[
            -1
        ][
            "payload"
        ]

        shifted_start = (
            self.start_datetime
            +
            timedelta(
                seconds=15
            )
        )

        outlier_payload[
            "scheduled_start_utc"
        ] = self._utc(
            shifted_start
        )

        outlier_payload[
            "scheduled_start_epoch"
        ] = shifted_start.timestamp()

        outlier_payload[
            "recording_utc"
        ] = self._utc(
            shifted_start
        )

        outlier_payload[
            "window_utc"
        ] = self._utc(
            shifted_start
        )

        outlier_payload[
            "boundary_utc"
        ] = self._utc(
            shifted_start
            +
            timedelta(
                seconds=15
            )
        )

        result = self.manager.align_complete_set(
            self._complete_set(
                events
            )
        )

        self.assertTrue(
            result[
                "success"
            ]
        )

        self.assertEqual(
            result[
                "complete_set"
            ][
                "aligned_node_ids"
            ],
            [
                "node_01",
                "node_02",
                "node_03",
                "node_04",
            ]
        )

        self.assertEqual(
            result[
                "clock_alignment"
            ][
                "recording_results"
            ][
                -1
            ][
                "failure_reason"
            ],
            "scheduled_start_mismatch"
        )

    def test_missing_scheduled_start_returns_structured_failure(
        self
    ):

        events = [
            self._recording_event(
                node_id=f"node_{index:02d}",
                effective_rate_hz=8000.0
            )
            for index in range(
                1,
                5
            )
        ]

        for event in events:
            event[
                "payload"
            ].pop(
                "scheduled_start_utc"
            )

        result = self.manager.align_complete_set(
            self._complete_set(
                events
            )
        )

        self.assertFalse(
            result[
                "success"
            ]
        )

        self.assertEqual(
            result[
                "failure_payload"
            ][
                "closure_reason"
            ],
            "clock_alignment_rejected"
        )

        self.assertEqual(
            result[
                "clock_alignment"
            ][
                "target_grid"
            ],
            None
        )

        self.assertTrue(
            all(
                recording_result[
                    "failure_reason"
                ]
                ==
                "scheduled_start_missing"
                for recording_result in result[
                    "clock_alignment"
                ][
                    "recording_results"
                ]
            )
        )

    # ========================================================
    # DISPATCHER FAILURE GATE
    # ========================================================

    def test_below_aligned_quorum_never_publishes_or_calculates(
        self
    ):

        events = [
            self._recording_event(
                node_id=f"node_{index:02d}",
                effective_rate_hz=8000.0
            )
            for index in range(
                1,
                5
            )
        ]

        events[
            -1
        ][
            "payload"
        ][
            "corrected_tdoa_eligible"
        ] = False

        event_bus = EventBus(
            retain_history=True
        )

        dispatcher = TDOADispatcher(
            event_bus=event_bus,
            config_path=str(
                SERVER_ROOT
                /
                "TDOA"
                /
                "TDOA_config.json"
            )
        )

        dispatcher.clock_alignment_manager = (
            self.manager
        )

        calculation_manager = (
            FakeCalculationManager()
        )

        dispatcher.manager = calculation_manager

        complete_events = []
        failed_events = []

        event_bus.subscribe(
            "TDOA_COMPLETE_SET",
            complete_events.append
        )

        event_bus.subscribe(
            "TDOA_REQUEST_FAILED",
            failed_events.append
        )

        dispatcher._handle_collection_update(
            {
                "action": "complete",
                "tdoa_request_id": "block8_failure",
                "payload": self._complete_set(
                    events,
                    request_id="block8_failure"
                )
            }
        )

        self.assertEqual(
            complete_events,
            []
        )

        self.assertEqual(
            calculation_manager.calls,
            []
        )

        self.assertEqual(
            len(
                failed_events
            ),
            1
        )

        failure_payload = failed_events[
            0
        ][
            "payload"
        ]

        self.assertEqual(
            failure_payload[
                "closure_reason"
            ],
            "clock_alignment_rejected"
        )

        self.assertEqual(
            failure_payload[
                "failure_reason"
            ],
            "clock_alignment_below_quorum"
        )

        self.assertEqual(
            failure_payload[
                "aligned_recording_count"
            ],
            3
        )

    # ========================================================
    # FIXTURE BUILDERS
    # ========================================================

    def _recording_event(
        self,
        node_id,
        effective_rate_hz,
        recording_id=None,
        channels=1,
        source_sample_rate_hz=None
    ):

        if source_sample_rate_hz is None:
            source_sample_rate_hz = (
                self.SAMPLE_RATE_HZ
            )

        if recording_id is None:
            recording_id = (
                "recording_"
                +
                node_id
            )

        node_directory = (
            self.root
            /
            node_id
        )

        node_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        raw_path = (
            node_directory
            /
            (
                recording_id
                +
                ".wav"
            )
        )

        node_number = int(
            node_id.split(
                "_"
            )[
                -1
            ]
        )

        origin_sample = (
            1_000_000.25
            +
            node_number
            *
            100_000.0
        )

        guarded_start_sample = int(
            math_floor(
                origin_sample
                -
                0.5
                *
                effective_rate_hz
            )
        )

        frame_count = int(
            round(
                self.GUARDED_DURATION_SECONDS
                *
                source_sample_rate_hz
            )
        )

        absolute_samples = (
            guarded_start_sample
            +
            np.arange(
                frame_count,
                dtype=np.float64
            )
        )

        relative_seconds = (
            (
                absolute_samples
                -
                origin_sample
            )
            /
            effective_rate_hz
        )

        pulse = (
            24000.0
            *
            np.exp(
                -0.5
                *
                (
                    (
                        relative_seconds
                        -
                        6.25
                    )
                    /
                    0.002
                )
                **
                2
            )
        )

        mono_audio = np.rint(
            pulse
        ).astype(
            "<i2"
        )

        audio = np.repeat(
            mono_audio[
                :,
                np.newaxis
            ],
            channels,
            axis=1
        )

        with wave.open(
            str(
                raw_path
            ),
            "wb"
        ) as wav_file:

            wav_file.setnchannels(
                channels
            )

            wav_file.setsampwidth(
                2
            )

            wav_file.setframerate(
                source_sample_rate_hz
            )

            wav_file.writeframes(
                audio.tobytes()
            )

        raw_sha256 = self._sha256(
            raw_path
        )

        ns_per_sample = (
            1_000_000_000.0
            /
            effective_rate_hz
        )

        model_id = (
            f"{node_id}:stream-a:1:1-120"
        )

        model = {
            "schema": (
                "enviro_pulse_sample_clock_model_v1"
            ),
            "model_id": model_id,
            "node_id": node_id,
            "stream_instance_id": "stream-a",
            "timing_segment_id": 1,
            "nominal_sample_rate_hz": (
                source_sample_rate_hz
            ),
            "effective_sample_rate_hz": (
                effective_rate_hz
            ),
            "sample_rate_error_ppm": (
                (
                    effective_rate_hz
                    /
                    source_sample_rate_hz
                )
                -
                1.0
            )
            *
            1_000_000.0,
            "sample_to_utc": {
                "origin_sample": origin_sample,
                "origin_utc_ns": self.start_utc_ns,
                "origin_utc": self.START_UTC,
                "ns_per_sample": ns_per_sample
            },
            "quality": {
                "status": "PASS",
                "model_valid": True,
                "quality_reasons": [],
                "residual_p95_us": 150.0,
                "residual_max_us": 250.0,
                "unresolved_discontinuity": False,
                "prior_discontinuity_isolated": False
            },
            "coverage": {
                "first_sample": (
                    guarded_start_sample
                    -
                    self.SAMPLE_RATE_HZ
                ),
                "last_sample": (
                    guarded_start_sample
                    +
                    frame_count
                    +
                    self.SAMPLE_RATE_HZ
                ),
                "first_utc_ns": (
                    self.start_utc_ns
                    -
                    1_500_000_000
                ),
                "last_utc_ns": (
                    self.start_utc_ns
                    +
                    16_500_000_000
                ),
                "duration_seconds": 18.0,
                "fit_window_policy": (
                    "rolling_recent_utc"
                ),
                "maximum_fit_horizon_seconds": 120.0
            }
        }

        boundary_datetime = (
            self.start_datetime
            +
            timedelta(
                seconds=(
                    self.TARGET_DURATION_SECONDS
                )
            )
        )

        payload = {
            "tdoa_request_id": "block8_request",
            "request_id": "block8_request",
            "node_id": node_id,
            "recording_id": recording_id,
            "status": "success",
            "validation_status": "accepted",
            "recording_path": str(
                raw_path
            ),
            "wav_path": str(
                raw_path
            ),
            "guarded_wav_path": str(
                raw_path
            ),
            "server_wav_path": str(
                raw_path
            ),
            "sample_rate": source_sample_rate_hz,
            "sample_rate_hz": source_sample_rate_hz,
            "channels": channels,
            "sample_width_bytes": 2,
            "frame_count": frame_count,
            "guarded_frame_count": frame_count,
            "guarded_duration_sec": (
                self.GUARDED_DURATION_SECONDS
            ),
            "recording_engine": "continuous_pps",
            "continuous_stream": True,
            "timing_state": "pps_clock_modeled_raw",
            "raw_timing_quality": "CLEAN",
            "timing_issues": [],
            "corrected_tdoa_eligible": True,
            "clock_fit_eligible": True,
            "raw_wav_immutable": True,
            "audio_correction_state": "raw_unmodified",
            "scheduled_start_utc": self.START_UTC,
            "scheduled_start_epoch": self.start_epoch,
            "recording_utc": self.START_UTC,
            "recording_epoch": self.start_epoch,
            "window_utc": self.START_UTC,
            "window_epoch": self.start_epoch,
            "boundary_utc": self._utc(
                boundary_datetime
            ),
            "boundary_epoch": (
                boundary_datetime.timestamp()
            ),
            "guarded_stream_start_sample": (
                guarded_start_sample
            ),
            "guarded_stream_end_sample_exclusive": (
                guarded_start_sample
                +
                frame_count
            ),
            "clock_model_id": model_id,
            "clock_model_quality": "PASS",
            "clock_model": model,
            "nearby_pps_anchors": [
                {
                    "pps_seq": 1,
                    "gnss_utc_ns": (
                        self.start_utc_ns
                    ),
                    "sample_position": (
                        origin_sample
                    ),
                    "fit_residual_us": 100.0
                },
                {
                    "pps_seq": 2,
                    "gnss_utc_ns": (
                        self.start_utc_ns
                        +
                        1_000_000_000
                    ),
                    "sample_position": (
                        origin_sample
                        +
                        effective_rate_hz
                    ),
                    "fit_residual_us": -100.0
                },
            ],
            "clock_model_association": {
                "schema_version": 1,
                "model_available": True,
                "model_valid": True,
                "quality_status": "PASS",
                "quality_reasons": [],
                "same_stream_instance": True,
                "same_timing_segment": True,
                "guarded_range_valid": True,
                (
                    "guarded_range_within_"
                    "extrapolation_limit"
                ): True,
                "nearby_anchor_count": 2,
                "maximum_extrapolation_seconds": 2.0
            },
            "server_validation": {
                "schema_version": 1,
                "sha256": raw_sha256,
                "timing_schema_present": True
            }
        }

        return {
            "event_type": "TDOA_VALID_RECORDING",
            "source": "communication",
            "target": "tdoa",
            "node_id": node_id,
            "recording_id": recording_id,
            "payload": payload
        }

    def _complete_set(
        self,
        events,
        request_id="block8_request"
    ):

        copied_events = copy.deepcopy(
            events
        )

        for event in copied_events:
            event[
                "payload"
            ][
                "tdoa_request_id"
            ] = request_id

            event[
                "payload"
            ][
                "request_id"
            ] = request_id

        node_ids = [
            event[
                "payload"
            ][
                "node_id"
            ]
            for event in copied_events
        ]

        return {
            "schema_version": 1,
            "tdoa_request_id": request_id,
            "request_id": request_id,
            "candidate_key": (
                "candidate_"
                +
                request_id
            ),
            "candidate": {
                "candidate_key": (
                    "candidate_"
                    +
                    request_id
                ),
                "node_ids": copy.deepcopy(
                    node_ids
                )
            },
            "request": {
                "tdoa_request_id": request_id,
                "target_nodes": copy.deepcopy(
                    node_ids
                )
            },
            "requested_node_ids": copy.deepcopy(
                node_ids
            ),
            "answered_node_ids": copy.deepcopy(
                node_ids
            ),
            "terminal_node_ids": copy.deepcopy(
                node_ids
            ),
            "valid_node_ids": copy.deepcopy(
                node_ids
            ),
            "failed_node_ids": [],
            "missing_node_ids": [],
            "requested_node_count": len(
                node_ids
            ),
            "answered_node_count": len(
                node_ids
            ),
            "valid_recording_count": len(
                node_ids
            ),
            "explicit_failure_count": 0,
            "required_valid_recordings": 4,
            "explicit_failures": {},
            "closure_reason": "all_returned",
            "success": True,
            "status": "complete",
            "recording_references": [
                {
                    "tdoa_request_id": request_id,
                    "node_id": event[
                        "payload"
                    ][
                        "node_id"
                    ],
                    "recording_id": event[
                        "payload"
                    ][
                        "recording_id"
                    ],
                    "server_wav_path": event[
                        "payload"
                    ][
                        "server_wav_path"
                    ]
                }
                for event in copied_events
            ],
            "recording_events": copied_events
        }

    @staticmethod
    def _utc(
        value
    ):

        return (
            value.astimezone(
                timezone.utc
            )
            .isoformat(
                timespec="seconds"
            )
            .replace(
                "+00:00",
                "Z"
            )
        )

    @staticmethod
    def _sha256(
        path
    ):

        return hashlib.sha256(
            path.read_bytes()
        ).hexdigest()


def math_floor(
    value
):
    """
    Keep fixture arithmetic explicit without adding production dependencies.
    """

    return int(
        np.floor(
            value
        )
    )


if __name__ == "__main__":
    unittest.main()
