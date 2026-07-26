# ============================================================
# test_TDOA_calculation_handoff.py
#
# EnviroPulse V2
#
# Subsystem:
#   Server TDOA
#
# Role:
#   Block 9 calculation-handoff checkpoint
#
# Purpose:
#   Prove TDOA calculation consumes only exact UTC-aligned recordings and
#   publishes one canonical TDOA_CALC result.
#
# Proves:
#   - Generic and node-local WAV paths cannot replace aligned_wav_path
#   - Aligned checksum and common-grid metadata are enforced
#   - Global recording-history fallback is disabled
#   - The calculation result is JSON-safe and omits audio arrays
#   - Invalid localization remains a canonical completed calculation result
#
# Does NOT:
#   - Improve solver geometry
#   - Refine solver residuals
#   - Promote TDOA_CALC to SERVER_TDOA_CALC
#   - Deliver results to the GUI
#
# ============================================================

import copy
import hashlib
import json
import sys
import tempfile
import unittest
import wave

from pathlib import Path

import numpy as np


SERVER_ROOT = Path(
    __file__
).resolve().parents[1]

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(SERVER_ROOT)
    )


from server_event_bus import EventBus
from TDOA.TDOA_dispatcher import TDOADispatcher
from TDOA.TDOA_manager import TDOAManager


class FakeCalculationManager:

    def __init__(
        self,
        success=True,
        localization_valid=False
    ):

        self.success = success
        self.localization_valid = localization_valid
        self.calls = []

    def tdoa_estimate(
        self,
        candidate,
        recording_events=None
    ):

        self.calls.append({
            "candidate": copy.deepcopy(
                candidate
            ),
            "recording_events": copy.deepcopy(
                recording_events
                or
                []
            )
        })

        return {
            "schema_version": 1,
            "success": self.success,
            "status": (
                "complete"
                if self.success
                else
                "failed"
            ),
            "calculation": "TDOA_CALC",
            "calculation_input": {
                "tdoa_request_id": "block9_dispatcher"
            },
            "solver_attempt_count": 1,
            "localization_valid": self.localization_valid,
            "errors": (
                []
                if self.success
                else
                ["synthetic_failure"]
            )
        }


class TDOACalculationHandoffTests(
    unittest.TestCase
):

    SAMPLE_RATE_HZ = 8000
    DURATION_SECONDS = 3.0
    FRAME_COUNT = int(
        SAMPLE_RATE_HZ
        *
        DURATION_SECONDS
    )
    START_UTC = "2026-07-26T19:00:00Z"

    def setUp(
        self
    ):

        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )

        self.root = Path(
            self.temporary_directory.name
        )

        self.manager = TDOAManager(
            config=self._config()
        )

        self.events = [
            self._aligned_event(
                node_index=index,
                onset_delay_samples=(
                    index
                    -
                    1
                )
                *
                5
            )
            for index in range(
                1,
                5
            )
        ]

        self.candidate = {
            "candidate_valid": True,
            "candidate_key": "block9_candidate",
            "avis_lite_id": "wooscj",
            "node_ids": [
                f"node_{index:02d}"
                for index in range(
                    1,
                    5
                )
            ]
        }

    def tearDown(
        self
    ):

        self.temporary_directory.cleanup()

    # ========================================================
    # EXACT HANDOFF
    # ========================================================

    def test_manager_uses_only_exact_aligned_paths(
        self
    ):

        for event in self.events:
            event[
                "payload"
            ][
                "wav_path"
            ] = (
                "/node/local/path/that/must/not/be/used.wav"
            )

            event[
                "payload"
            ][
                "recording_path"
            ] = (
                "/another/nonserver/path.wav"
            )

        result = self.manager.tdoa_estimate(
            candidate=self.candidate,
            recording_events=self.events
        )

        self.assertTrue(
            result[
                "success"
            ],
            result.get(
                "errors"
            )
        )

        self.assertEqual(
            result[
                "status"
            ],
            "complete"
        )

        self.assertEqual(
            result[
                "calculation_input"
            ][
                "recording_count"
            ],
            4
        )

        self.assertTrue(
            result[
                "calculation_attempted"
            ]
        )

        self.assertGreaterEqual(
            result[
                "solver_attempt_count"
            ],
            1
        )

        self.assertEqual(
            set(
                result[
                    "channel_event_counts"
                ].keys()
            ),
            {
                "node_01",
                "node_02",
                "node_03",
                "node_04"
            }
        )

        exact_paths = {
            recording[
                "aligned_wav_path"
            ]
            for recording in result[
                "calculation_input"
            ][
                "recordings"
            ]
        }

        expected_paths = {
            str(
                Path(
                    event[
                        "payload"
                    ][
                        "aligned_wav_path"
                    ]
                ).resolve()
            )
            for event in self.events
        }

        self.assertEqual(
            exact_paths,
            expected_paths
        )

        encoded = json.dumps(
            result,
            sort_keys=True
        )

        self.assertNotIn(
            "event_window",
            encoded
        )

        self.assertNotIn(
            "/node/local/path",
            encoded
        )

    def test_missing_aligned_path_does_not_fall_back(
        self
    ):

        events = copy.deepcopy(
            self.events
        )

        valid_generic_path = events[
            0
        ][
            "payload"
        ][
            "aligned_wav_path"
        ]

        events[
            0
        ][
            "payload"
        ].pop(
            "aligned_wav_path"
        )

        events[
            0
        ][
            "payload"
        ][
            "wav_path"
        ] = valid_generic_path

        with self.assertLogs(
            level="ERROR"
        ):
            result = self.manager.tdoa_estimate(
                candidate=self.candidate,
                recording_events=events
            )

        self.assertFalse(
            result[
                "success"
            ]
        )

        self.assertIn(
            "aligned_wav_path",
            result[
                "errors"
            ][
                0
            ]
        )

    def test_checksum_mismatch_rejects_calculation_input(
        self
    ):

        events = copy.deepcopy(
            self.events
        )

        events[
            0
        ][
            "payload"
        ][
            "aligned_wav_sha256"
        ] = "0" * 64

        with self.assertLogs(
            level="ERROR"
        ):
            result = self.manager.tdoa_estimate(
                candidate=self.candidate,
                recording_events=events
            )

        self.assertFalse(
            result[
                "success"
            ]
        )

        self.assertIn(
            "checksum mismatch",
            result[
                "errors"
            ][
                0
            ]
        )

    def test_mixed_utc_grid_rejects_calculation_input(
        self
    ):

        events = copy.deepcopy(
            self.events
        )

        events[
            -1
        ][
            "payload"
        ][
            "scheduled_start_utc"
        ] = "2026-07-26T19:00:15Z"

        with self.assertLogs(
            level="ERROR"
        ):
            result = self.manager.tdoa_estimate(
                candidate=self.candidate,
                recording_events=events
            )

        self.assertFalse(
            result[
                "success"
            ]
        )

        self.assertIn(
            "do not share scheduled_start_utc",
            result[
                "errors"
            ][
                0
            ]
        )

    def test_recording_history_fallback_is_disabled(
        self
    ):

        self.assertFalse(
            hasattr(
                self.manager,
                "recording_store"
            )
        )

        with self.assertLogs(
            level="ERROR"
        ):
            result = self.manager.tdoa_estimate(
                candidate=self.candidate,
                recording_events=None
            )

        self.assertFalse(
            result[
                "success"
            ]
        )

        self.assertIn(
            "Global recording-history fallback is disabled",
            result[
                "errors"
            ][
                0
            ]
        )

    # ========================================================
    # CANONICAL EVENT
    # ========================================================

    def test_dispatcher_publishes_canonical_tdoa_calc(
        self
    ):

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

        manager = FakeCalculationManager(
            success=True,
            localization_valid=False
        )

        dispatcher.manager = manager

        canonical_events = []
        legacy_events = []
        failed_events = []

        event_bus.subscribe(
            "TDOA_CALC",
            canonical_events.append
        )

        event_bus.subscribe(
            "TDOA_CALC_COMPLETE",
            legacy_events.append
        )

        event_bus.subscribe(
            "TDOA_CALC_FAILED",
            failed_events.append
        )

        dispatcher._handle_tdoa_complete_set(
            self._dispatcher_complete_set()
        )

        self.assertEqual(
            len(
                canonical_events
            ),
            1
        )

        self.assertEqual(
            legacy_events,
            []
        )

        self.assertEqual(
            failed_events,
            []
        )

        payload = canonical_events[
            0
        ][
            "payload"
        ]

        self.assertFalse(
            payload[
                "localization_valid"
            ]
        )

        self.assertEqual(
            payload[
                "status"
            ],
            "complete"
        )

        self.assertEqual(
            len(
                manager.calls
            ),
            1
        )

    def test_dispatcher_separates_execution_failure(
        self
    ):

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

        dispatcher.manager = FakeCalculationManager(
            success=False
        )

        canonical_events = []
        failed_events = []

        event_bus.subscribe(
            "TDOA_CALC",
            canonical_events.append
        )

        event_bus.subscribe(
            "TDOA_CALC_FAILED",
            failed_events.append
        )

        dispatcher._handle_tdoa_complete_set(
            self._dispatcher_complete_set()
        )

        self.assertEqual(
            canonical_events,
            []
        )

        self.assertEqual(
            len(
                failed_events
            ),
            1
        )

    # ========================================================
    # FIXTURES
    # ========================================================

    def _aligned_event(
        self,
        node_index,
        onset_delay_samples
    ):

        node_id = f"node_{node_index:02d}"
        wav_path = (
            self.root
            /
            f"{node_id}_aligned.wav"
        )

        signal = np.empty(
            self.FRAME_COUNT,
            dtype=np.int16
        )

        signal[
            0::2
        ] = 20

        signal[
            1::2
        ] = -20

        onset_sample = (
            self.SAMPLE_RATE_HZ
            +
            onset_delay_samples
        )

        pulse_samples = int(
            0.015
            *
            self.SAMPLE_RATE_HZ
        )

        signal[
            onset_sample:
            onset_sample
            +
            pulse_samples
        ] = 5000

        with wave.open(
            str(
                wav_path
            ),
            "wb"
        ) as wav_file:

            wav_file.setnchannels(
                1
            )

            wav_file.setsampwidth(
                2
            )

            wav_file.setframerate(
                self.SAMPLE_RATE_HZ
            )

            wav_file.writeframes(
                signal.astype(
                    "<i2"
                ).tobytes()
            )

        sha256 = hashlib.sha256(
            wav_path.read_bytes()
        ).hexdigest()

        payload = {
            "tdoa_request_id": "block9_request",
            "request_id": "block9_request",
            "node_id": node_id,
            "recording_id": (
                f"recording_{self.START_UTC}"
            ),
            "avis_lite_id": "wooscj",
            "status": "success",
            "alignment_status": "PASS",
            "timing_state": "utc_grid_aligned",
            "corrected_tdoa_eligible": True,
            "scheduled_start_utc": self.START_UTC,
            "aligned_wav_path": str(
                wav_path
            ),
            "aligned_wav_sha256": sha256,
            "aligned_metadata_path": str(
                wav_path.with_suffix(
                    ".alignment.json"
                )
            ),
            "wav_path": str(
                wav_path
            ),
            "recording_path": str(
                wav_path
            ),
            "sample_rate_hz": self.SAMPLE_RATE_HZ,
            "channels": 1,
            "sample_width_bytes": 2,
            "frame_count": self.FRAME_COUNT,
            "duration_seconds": self.DURATION_SECONDS
        }

        return {
            "event_type": "TDOA_VALID_RECORDING",
            "source": node_id,
            "status": "success",
            "payload": payload
        }

    def _dispatcher_complete_set(
        self
    ):

        return {
            "schema_version": 2,
            "success": True,
            "status": "complete",
            "tdoa_request_id": "block9_dispatcher",
            "candidate": copy.deepcopy(
                self.candidate
            ),
            "closure_reason": "all_returned",
            "valid_node_ids": [
                f"node_{index:02d}"
                for index in range(
                    1,
                    5
                )
            ],
            "aligned_node_ids": [
                f"node_{index:02d}"
                for index in range(
                    1,
                    5
                )
            ],
            "aligned_recording_count": 4,
            "alignment_rejected_node_ids": [],
            "recording_events": copy.deepcopy(
                self.events
            ),
            "clock_alignment": {
                "target_grid": {
                    "start_utc": self.START_UTC,
                    "sample_rate_hz": self.SAMPLE_RATE_HZ,
                    "frame_count": self.FRAME_COUNT
                }
            }
        }

    def _config(
        self
    ):

        return {
            "tdoa_clock_alignment": {
                "target_sample_rate_hz": self.SAMPLE_RATE_HZ,
                "target_duration_seconds": self.DURATION_SECONDS
            },
            "tdoa_manager": {
                "default_sample_rate_hz": self.SAMPLE_RATE_HZ,
                "minimum_solver_nodes": 4
            },
            "TDOA_event_detection": {
                "onset_method": "energy_threshold_onset",
                "offset_method": "energy_threshold_offset",
                "include_event_window": True,
                "minimum_event_duration_seconds": 0.0,
                "maximum_event_duration_seconds": None
            },
            "energy_threshold_onset": {
                "noise_window_seconds": 0.5,
                "onset_multiplier": 6.0,
                "min_active_seconds": 0.01,
                "minimum_detection_spacing_seconds": 0.025
            },
            "energy_threshold_offset": {
                "noise_window_seconds": 0.5,
                "offset_multiplier": 4.0,
                "min_quiet_seconds": 0.01,
                "minimum_detection_spacing_seconds": 0.025
            },
            "general_features": {
                "extract_peak_amplitude": True,
                "use_absolute_peak": True,
                "return_peak_time": True
            },
            "TDOA_event_analysis": {
                "minimum_channels_required": 4,
                "use_valid_consensus_only": True
            },
            "event_matching": {
                "alignment_feature": "onset_sample",
                "match_tolerance_samples": 200,
                "reference_channel_mode": "first",
                "minimum_channels_required": 4
            },
            "matching_consensus": {
                "alignment_feature": "onset_sample",
                "max_spread_samples": 200,
                "max_std_deviation_samples": 75,
                "minimum_channels_required": 4
            },
            "TDOA_event_solver": {
                "sample_rate_hz": self.SAMPLE_RATE_HZ,
                "speed_of_sound_mps": 340.0,
                "minimum_channels_required": 4,
                "solver_method": "least_squares",
                "max_residual_error": 100.0
            },
            "solver_consensus": {
                "minimum_solutions_required": 1,
                "max_residual_error": 100.0,
                "prefer_lowest_residual": True,
                "max_position_spread_meters": 100.0
            },
            "microphone_positions": {
                "CH1": [0.0, 0.0, 0.0],
                "CH2": [1.0, 0.0, 0.0],
                "CH3": [0.0, 1.0, 0.0],
                "CH4": [0.0, 0.0, 1.0]
            }
        }


if __name__ == "__main__":
    unittest.main()
