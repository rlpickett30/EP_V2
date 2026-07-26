# ============================================================
# test_microphone_sample_clock_model.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Microphone
#
# Role:
#   Test
#
# Purpose:
#   Verify Block 7 clock fitting, quality grading, discontinuity resets,
#   recording association, residual preservation, and raw-WAV immutability.
#
# ============================================================

from __future__ import annotations

import hashlib
import math
import sys
import tempfile
import threading
import types
import unittest

from datetime import datetime
from datetime import timezone
from pathlib import Path


MICROPHONE_ROOT = Path(
    __file__
).resolve().parent

if str(MICROPHONE_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(MICROPHONE_ROOT),
    )

if "sounddevice" not in sys.modules:
    sounddevice_stub = types.ModuleType(
        "sounddevice"
    )
    sounddevice_stub.InputStream = object
    sys.modules[
        "sounddevice"
    ] = sounddevice_stub

from microphone_clock_model import (
    MicrophoneClockModelManager
)
from microphone_dispatcher import (
    MicrophoneDispatcher
)
from microphone_manager import MicrophoneManager


class AnchorJournalStub:

    def __init__(
        self
    ):
        self.records = []

    def enqueue(
        self,
        record
    ):
        self.records.append(
            record
        )
        return True


class EventServicesStub:

    def __init__(
        self
    ):
        self.events = []

    def publish_microphone_synced(
        self,
        event
    ):
        self.events.append(
            event
        )


class LoopStub:

    def continuous_stream_active(
        self
    ):
        return True


class MicrophoneSampleClockModelTests(
    unittest.TestCase
):

    nominal_rate_hz = 48000.0
    effective_rate_hz = 48014.5
    base_utc_ns = int(
        datetime(
            2026,
            7,
            24,
            23,
            18,
            tzinfo=timezone.utc,
        ).timestamp()
        *
        1_000_000_000
    )

    def make_manager(
        self,
        root,
        warning_residual_us=1000.0,
        failure_residual_us=5000.0,
    ):

        return MicrophoneClockModelManager(
            recordings_root=root,
            node_id="node_01",
            nominal_sample_rate_hz=(
                self.nominal_rate_hz
            ),
            anchor_evidence_path=(
                Path(root)
                /
                "timing"
                /
                "raw_anchors.ndjson"
            ),
            minimum_anchor_count=5,
            minimum_coverage_seconds=15.0,
            warning_residual_us=(
                warning_residual_us
            ),
            failure_residual_us=(
                failure_residual_us
            ),
            debug=False,
        )

    def make_anchor(
        self,
        index,
        stream_instance_id="stream-a",
        timing_segment_id=1,
        sample_offset=0.0,
        utc_offset_seconds=0,
    ):

        utc_index = (
            index
            +
            utc_offset_seconds
        )

        sample_position = (
            index
            *
            self.effective_rate_hz
            +
            sample_offset
        )

        return {
            "anchor_accepted": True,
            "pps_seq": (
                1000
                +
                utc_index
            ),
            "utc_label_valid": True,
            "utc_source": (
                "gnss_rmc_paired_to_pps"
            ),
            "gnss_utc_ns": (
                self.base_utc_ns
                +
                utc_index
                *
                1_000_000_000
            ),
            "gnss_utc": (
                "2026-07-24T23:18:00Z"
            ),
            "rmc_arrival_delay_ms": 120.0,
            "resolver_state": (
                "resolved_interpolation"
            ),
            "sample_lookup": {
                "accepted": True,
                "lookup_method": (
                    "callback_pair_interpolation"
                ),
                "sample_position_fractional": (
                    sample_position
                ),
                "sample_position_rounded": int(
                    round(
                        sample_position
                    )
                ),
                "stream_instance_id": (
                    stream_instance_id
                ),
                "timing_segment_id": (
                    timing_segment_id
                ),
                "local_rate_hz": (
                    self.effective_rate_hz
                ),
            },
        }

    def feed_model(
        self,
        manager,
        count=21,
        jitter_seconds=0.0,
        stream_instance_id="stream-a",
        timing_segment_id=1,
        utc_offset_seconds=0,
        base_sample_offset=0.0,
    ):

        for index in range(
            count
        ):
            jitter_samples = (
                math.sin(
                    index
                    *
                    0.73
                )
                *
                jitter_seconds
                *
                self.effective_rate_hz
                +
                base_sample_offset
            )

            manager.observe_anchor(
                self.make_anchor(
                    index=index,
                    stream_instance_id=(
                        stream_instance_id
                    ),
                    timing_segment_id=(
                        timing_segment_id
                    ),
                    sample_offset=(
                        jitter_samples
                    ),
                    utc_offset_seconds=(
                        utc_offset_seconds
                    ),
                )
            )

        return manager.get_latest_model()

    def test_proven_clock_fit_produces_pass_and_residuals(
        self
    ):

        with tempfile.TemporaryDirectory() as root:
            manager = self.make_manager(
                root
            )
            model = self.feed_model(
                manager
            )

        self.assertEqual(
            model["quality"]["status"],
            "PASS",
        )
        self.assertTrue(
            model["quality"]["model_valid"]
        )
        self.assertAlmostEqual(
            model[
                "effective_sample_rate_hz"
            ],
            self.effective_rate_hz,
            places=3,
        )
        self.assertAlmostEqual(
            model[
                "sample_rate_error_ppm"
            ],
            (
                self.effective_rate_hz
                /
                self.nominal_rate_hz
                -
                1.0
            )
            *
            1_000_000.0,
            places=3,
        )
        self.assertEqual(
            len(
                model["fit_residuals"]
            ),
            21,
        )
        self.assertTrue(
            all(
                "fit_residual_us"
                in
                item
                for item in model[
                    "fit_residuals"
                ]
            )
        )

    def test_quality_grades_warn_and_fail(
        self
    ):

        with tempfile.TemporaryDirectory() as root:
            warn_manager = self.make_manager(
                Path(root) / "warn"
            )
            warn_model = self.feed_model(
                warn_manager,
                jitter_seconds=0.002,
            )

            fail_manager = self.make_manager(
                Path(root) / "fail"
            )
            fail_model = self.feed_model(
                fail_manager,
                jitter_seconds=0.008,
            )

        self.assertEqual(
            warn_model["quality"]["status"],
            "WARN",
        )
        self.assertFalse(
            warn_model["quality"]["model_valid"]
        )
        self.assertEqual(
            fail_model["quality"]["status"],
            "FAIL",
        )
        self.assertFalse(
            fail_model["quality"]["model_valid"]
        )

    def test_stream_discontinuity_resets_clock_fit(
        self
    ):

        with tempfile.TemporaryDirectory() as root:
            manager = self.make_manager(
                root
            )
            first_model = self.feed_model(
                manager
            )

            manager.observe_anchor(
                self.make_anchor(
                    index=0,
                    stream_instance_id="stream-b",
                    timing_segment_id=2,
                    sample_offset=1_000_000.0,
                    utc_offset_seconds=100,
                )
            )

            after_reset = (
                manager.get_latest_model()
            )

            second_model = self.feed_model(
                manager,
                count=21,
                stream_instance_id="stream-b",
                timing_segment_id=2,
                utc_offset_seconds=100,
                base_sample_offset=(
                    1_000_000.0
                ),
            )

        self.assertEqual(
            first_model["quality"]["status"],
            "PASS",
        )
        self.assertIsNone(
            after_reset
        )
        self.assertEqual(
            second_model["quality"]["status"],
            "PASS",
        )
        self.assertEqual(
            second_model["reset_count"],
            1,
        )

    def test_recording_receives_model_and_raw_wav_is_unchanged(
        self
    ):

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(
                root
            )
            manager = self.make_manager(
                root_path
            )
            model = self.feed_model(
                manager
            )

            raw_wav = (
                root_path
                /
                "guarded_raw.wav"
            )
            raw_wav.write_bytes(
                b"RIFF"
                +
                bytes(
                    range(
                        64
                    )
                )
            )

            before_hash = hashlib.sha256(
                raw_wav.read_bytes()
            ).hexdigest()

            recording = {
                "recording_id": (
                    "recording_test"
                ),
                "guarded_wav_path": str(
                    raw_wav
                ),
                "boundary_snapshot": {
                    "stream_instance_id": (
                        "stream-a"
                    ),
                    "timing_segment_id": 1,
                },
                (
                    "guarded_stream_"
                    "start_sample"
                ): (
                    2
                    *
                    self.effective_rate_hz
                ),
                (
                    "guarded_stream_end_"
                    "sample_exclusive"
                ): (
                    19
                    *
                    self.effective_rate_hz
                ),
            }

            associated = (
                manager.associate_recording(
                    recording
                )
            )

            after_hash = hashlib.sha256(
                raw_wav.read_bytes()
            ).hexdigest()

            persisted_model = (
                manager.output_path
            )
            persisted_model_exists = (
                persisted_model.is_file()
            )

        self.assertEqual(
            before_hash,
            after_hash,
        )
        self.assertEqual(
            associated["clock_model_id"],
            model["model_id"],
        )
        self.assertEqual(
            associated[
                "clock_model_quality"
            ],
            "PASS",
        )
        self.assertTrue(
            associated[
                "clock_model_association"
            ][
                "model_valid"
            ]
        )
        self.assertGreaterEqual(
            len(
                associated[
                    "nearby_pps_anchors"
                ]
            ),
            2,
        )
        self.assertTrue(
            all(
                "fit_residual_us"
                in
                anchor
                for anchor in associated[
                    "nearby_pps_anchors"
                ]
            )
        )
        self.assertEqual(
            associated["timing_state"],
            "pps_clock_modeled_raw",
        )
        self.assertTrue(
            persisted_model_exists
        )

    def test_invalid_utc_anchor_never_enters_fit(
        self
    ):

        with tempfile.TemporaryDirectory() as root:
            manager = self.make_manager(
                root
            )
            invalid_anchor = self.make_anchor(
                0
            )
            invalid_anchor[
                "utc_label_valid"
            ] = False

            result = manager.observe_anchor(
                invalid_anchor
            )

        self.assertFalse(
            result["accepted"]
        )
        self.assertEqual(
            result["reason"],
            "gnss_utc_label_invalid",
        )
        self.assertIsNone(
            result["model"]
        )

    def test_microphone_event_preserves_clock_evidence_and_raw_state(
        self
    ):

        manager = MicrophoneManager(
            node_id="node_01",
            node_name="EnviroPulse Node 01",
            debug=False,
        )

        recording = {
            "recording_id": "recording_test",
            "recording_utc": (
                "2026-07-24T23:18:00Z"
            ),
            "recording_epoch": 1.0,
            "wav_path": "core.wav",
            "guarded_wav_path": (
                "guarded_raw.wav"
            ),
            "metadata_path": "metadata.json",
            "sample_rate": 48000,
            "channels": 1,
            "duration_sec": 15.0,
            "frame_count": 720000,
            "guarded_duration_sec": 16.0,
            "guarded_frame_count": 768000,
            "recording_type": "recording",
            "recording_engine": (
                "continuous_pps"
            ),
            "continuous_stream": True,
            "timing_state": (
                "pps_clock_modeled_raw"
            ),
            "clock_model_id": "model-1",
            "clock_model_quality": "PASS",
            "clock_model": {
                "model_id": "model-1"
            },
            "nearby_pps_anchors": [
                {
                    "pps_seq": 1
                },
                {
                    "pps_seq": 2
                },
            ],
            "clock_model_association": {
                "model_valid": True
            },
        }

        event = (
            manager
            .build_recording_available_event(
                recording=recording,
                pps_state={
                    "pps_locked": True
                },
                sync_source=(
                    "pps_quarter_minute_window"
                ),
            )
        )

        payload = event["payload"]

        self.assertEqual(
            payload["clock_model_id"],
            "model-1",
        )
        self.assertEqual(
            len(
                payload[
                    "nearby_pps_anchors"
                ]
            ),
            2,
        )
        self.assertTrue(
            payload["raw_wav_immutable"]
        )
        self.assertEqual(
            payload[
                "audio_correction_state"
            ],
            "raw_unmodified",
        )

    def test_dispatcher_finalizes_only_gnss_labeled_anchor(
        self
    ):

        with tempfile.TemporaryDirectory() as root:
            dispatcher = (
                MicrophoneDispatcher.__new__(
                    MicrophoneDispatcher
                )
            )
            dispatcher.node_id = "node_01"
            dispatcher.node_name = (
                "EnviroPulse Node 01"
            )
            dispatcher._pps_anchor_lock = (
                threading.Lock()
            )
            dispatcher.pps_anchor_attempt_count = 0
            dispatcher.pps_anchor_accepted_count = 0
            dispatcher.pps_anchor_rejected_count = 0
            dispatcher.latest_pps_sample_anchor = None
            dispatcher.pps_anchor_journal = (
                AnchorJournalStub()
            )
            dispatcher.clock_model_manager = (
                self.make_manager(
                    root
                )
            )
            dispatcher.debug = False

            pending = {
                "enqueued_monotonic_ns": 1,
                "pps_seq": 1,
                "pps_kernel_realtime_ns": 2,
                "pps_edge_monotonic_ns": 3,
                "sequence_gap": 1,
                "missed_edge_count": 0,
                "sequence_reset": False,
                "utc_label_valid": True,
                "utc_label_state": (
                    "gnss_rmc_paired"
                ),
                "utc_source": (
                    "gnss_rmc_paired_to_pps"
                ),
                "gnss_utc_ns": (
                    self.base_utc_ns
                ),
                "gnss_utc": (
                    "2026-07-24T23:18:00Z"
                ),
                "gnss_utc_epoch": (
                    self.base_utc_ns
                    /
                    1_000_000_000.0
                ),
                "rmc_arrival_delay_ms": 120.0,
                "utc_label_rejection_reasons": [],
                "utc_pairing": {
                    "pairing_state": "accepted"
                },
                "raw_pps_event": {
                    "event_type": "PPS_EDGE"
                },
                "stream_snapshot_at_enqueue": {},
            }

            lookup = {
                "accepted": True,
                "lookup_method": (
                    "callback_pair_interpolation"
                ),
                "quality_reasons": [],
                "sample_position_fractional": 10.0,
                "sample_position_rounded": 10,
                "stream_instance_id": "stream-a",
                "timing_segment_id": 1,
            }

            accepted = (
                dispatcher
                ._finalize_pps_anchor(
                    pending=pending,
                    lookup_result=lookup,
                    resolver_state=(
                        "resolved_interpolation"
                    ),
                    resolution_attempts=[
                        lookup
                    ],
                )
            )

            rejected_pending = dict(
                pending
            )
            rejected_pending[
                "pps_seq"
            ] = 2
            rejected_pending[
                "utc_label_valid"
            ] = False
            rejected_pending[
                "utc_label_rejection_reasons"
            ] = [
                "matching_rmc_timeout"
            ]

            rejected = (
                dispatcher
                ._finalize_pps_anchor(
                    pending=rejected_pending,
                    lookup_result=lookup,
                    resolver_state=(
                        "resolved_interpolation"
                    ),
                    resolution_attempts=[
                        lookup
                    ],
                )
            )

        self.assertTrue(
            accepted["anchor_accepted"]
        )
        self.assertEqual(
            accepted["utc_source"],
            "gnss_rmc_paired_to_pps",
        )
        self.assertFalse(
            rejected["anchor_accepted"]
        )
        self.assertIn(
            "matching_rmc_timeout",
            rejected["quality_reasons"],
        )
        self.assertEqual(
            len(
                dispatcher
                .pps_anchor_journal
                .records
            ),
            2,
        )

    def test_microphone_synced_requires_pass_model(
        self
    ):

        dispatcher = (
            MicrophoneDispatcher.__new__(
                MicrophoneDispatcher
            )
        )
        dispatcher.pps_locked = True
        dispatcher.gps_locked = True
        dispatcher.consecutive_synced_windows = 0
        dispatcher.loop = LoopStub()
        dispatcher.event_services = (
            EventServicesStub()
        )
        dispatcher.manager = MicrophoneManager(
            node_id="node_01",
            node_name="EnviroPulse Node 01",
            debug=False,
        )
        dispatcher.clock_model_manager = (
            types.SimpleNamespace(
                warning_residual_us=1000.0
            )
        )
        dispatcher.debug = False

        recording = {
            "recording_id": "recording_test",
            "recording_utc": (
                "2026-07-24T23:18:00Z"
            ),
            "recording_epoch": 1.0,
            "wav_path": "core.wav",
            "guarded_wav_path": (
                "guarded_raw.wav"
            ),
            "metadata_path": "metadata.json",
            "sample_rate": 48000,
            "channels": 1,
            "duration_sec": 15.0,
            "frame_count": 720000,
            "recording_type": "recording",
            "recording_engine": (
                "continuous_pps"
            ),
            "raw_timing_quality": "CLEAN",
            "corrected_tdoa_eligible": True,
            "clock_model_id": "model-1",
            "clock_model_quality": "PASS",
            "clock_model": {
                "fit_residuals": [
                    {
                        "pps_seq": 1,
                        "fit_residual_us": 0.8,
                    }
                ],
                "quality": {
                    "status": "PASS",
                    "model_valid": True,
                    "residual_p95_us": 0.8,
                    (
                        "unresolved_"
                        "discontinuity"
                    ): False,
                }
            },
        }

        event = (
            dispatcher
            .maybe_publish_microphone_synced(
                recording=recording,
                pps_state={
                    "pps_locked": True
                },
                sync_source=(
                    "pps_quarter_minute_window"
                ),
                scheduled_start_epoch=1.0,
                scheduled_start_utc=(
                    "2026-07-24T23:18:00Z"
                ),
            )
        )

        self.assertIsNotNone(
            event
        )
        self.assertEqual(
            len(
                dispatcher
                .event_services
                .events
            ),
            1,
        )
        self.assertEqual(
            event["payload"][
                "clock_model_quality"
            ],
            "PASS",
        )
        self.assertNotIn(
            "fit_residuals",
            event["payload"][
                "clock_model"
            ],
        )
        self.assertEqual(
            event["payload"][
                "clock_model"
            ][
                "fit_residual_count"
            ],
            1,
        )

        warning_recording = dict(
            recording
        )
        warning_recording[
            "clock_model"
        ] = {
            "quality": {
                "status": "WARN",
                "model_valid": False,
                "residual_p95_us": 2000.0,
                (
                    "unresolved_"
                    "discontinuity"
                ): False,
            }
        }
        warning_recording[
            "clock_model_quality"
        ] = "WARN"
        warning_recording[
            "corrected_tdoa_eligible"
        ] = False

        withheld = (
            dispatcher
            .maybe_publish_microphone_synced(
                recording=(
                    warning_recording
                ),
                pps_state={
                    "pps_locked": True
                },
                sync_source=(
                    "pps_quarter_minute_window"
                ),
                scheduled_start_epoch=1.0,
                scheduled_start_utc=(
                    "2026-07-24T23:18:00Z"
                ),
            )
        )

        self.assertIsNone(
            withheld
        )
        self.assertEqual(
            len(
                dispatcher
                .event_services
                .events
            ),
            1,
        )

    def test_degraded_audio_is_never_clock_correction_eligible(
        self
    ):

        dispatcher = (
            MicrophoneDispatcher.__new__(
                MicrophoneDispatcher
            )
        )
        dispatcher.debug = False

        recording = {
            "recording_id": "recording_test",
            "recording_engine": (
                "continuous_pps"
            ),
            "stream_status_events": [
                {
                    "status": (
                        "input overflow"
                    )
                }
            ],
            "clock_model_quality": "PASS",
            "clock_model_association": {
                "model_valid": True
            },
        }

        result = (
            dispatcher
            .attach_timing_quality(
                recording
            )
        )

        self.assertEqual(
            result["raw_timing_quality"],
            "DEGRADED",
        )
        self.assertIn(
            "input_overflow",
            result["timing_issues"],
        )
        self.assertFalse(
            result["clock_fit_eligible"]
        )
        self.assertFalse(
            result[
                "corrected_tdoa_eligible"
            ]
        )


if __name__ == "__main__":
    unittest.main()
