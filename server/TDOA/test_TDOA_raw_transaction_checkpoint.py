# ============================================================
# test_TDOA_raw_transaction_checkpoint.py
#
# EnviroPulse V2
#
# Subsystem:
#   Server TDOA / Communication
#
# Role:
#   Block 5 transaction checkpoint
#
# Purpose:
#   Prove the request-scoped raw TDOA transaction outcomes required before
#   clock synchronization work begins.
#
# Proves:
#   - Four requested and four valid recordings complete immediately
#   - Six requested and six valid recordings complete immediately
#   - Four valid recordings plus two explicit failures complete immediately
#   - Four valid recordings plus two silent nodes complete at timeout
#   - Three valid recordings fail below quorum without calculation
#   - An identical upload retry is idempotent
#   - A conflicting upload retry is rejected and logged
#
# Does NOT:
#   - Claim microphone clock synchronization
#   - Validate PPS-to-GNSS UTC labeling
#   - Validate sample-clock fitting
#   - Change production architecture
#
# ============================================================

import hashlib
import io
import json
import sys
import tempfile
import unittest
import wave

from pathlib import Path


SERVER_ROOT = Path(
    __file__
).resolve().parents[1]

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(SERVER_ROOT)
    )


from communication.communication_dispatcher import (
    CommunicationDispatcher
)
from communication.tdoa_upload_manager import (
    TDOAUploadManager
)
from server_event_bus import EventBus
from TDOA.TDOA_dispatcher import TDOADispatcher
from TDOA.TDOA_recording_manager import (
    TDOARecordingManager
)


class FakeClock:

    def __init__(
        self
    ):
        self.monotonic_value = 1000.0

    def monotonic(
        self
    ):
        return self.monotonic_value

    def utc(
        self
    ):
        return "2026-07-25T23:00:00Z"

    def advance(
        self,
        seconds
    ):
        self.monotonic_value += float(
            seconds
        )


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
        call = {
            "candidate": candidate,
            "recording_events": list(
                recording_events or []
            )
        }

        self.calls.append(
            call
        )

        return {
            "success": True,
            "candidate": candidate,
            "exact_recording_event_count": len(
                call["recording_events"]
            )
        }


class TDOARawTransactionCheckpointTests(
    unittest.TestCase
):

    def setUp(
        self
    ):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.temp_root = Path(
            self.temp_directory.name
        )

        self.clock = FakeClock()

        self.event_bus = EventBus(
            retain_history=True,
            max_history=500
        )

        self.tdoa_dispatcher = TDOADispatcher(
            event_bus=self.event_bus,
            config_path=str(
                SERVER_ROOT
                /
                "TDOA"
                /
                "TDOA_config.json"
            )
        )

        self.tdoa_dispatcher.recording_manager = (
            TDOARecordingManager(
                config={
                    "tdoa_recording_manager": {
                        "minimum_valid_recordings": 4,
                        "collection_timeout_seconds": 15.0,
                        "deadline_poll_interval_seconds": 60.0,
                        "max_closed_requests": 20
                    }
                },
                monotonic_now=self.clock.monotonic,
                utc_now=self.clock.utc
            )
        )

        self.calculation_manager = FakeCalculationManager()
        self.tdoa_dispatcher.manager = self.calculation_manager

        self.communication_dispatcher = CommunicationDispatcher(
            event_bus=self.event_bus,
            config_path=str(
                SERVER_ROOT
                /
                "communication"
                /
                "communication_config.json"
            )
        )

        self.upload_manager = TDOAUploadManager(
            config={
                "storage_dir": str(
                    self.temp_root
                    /
                    "accepted"
                ),
                "temp_dir": str(
                    self.temp_root
                    /
                    "incoming"
                ),
                "request_ttl_seconds": 60.0,
                "max_metadata_bytes": 262144,
                "max_wav_bytes": 8388608,
                "enforce_source_ip": False,
                "allowed_channels": [1],
                "allowed_sample_width_bytes": [2],
                "allowed_sample_rates_hz": [48000]
            }
        )

        self.communication_dispatcher.tdoa_upload_manager = (
            self.upload_manager
        )

        self.complete_events = []
        self.failed_events = []
        self.recording_events = []
        self.valid_recording_events = []

        self.event_bus.subscribe(
            "TDOA_COMPLETE_SET",
            self.complete_events.append
        )

        self.event_bus.subscribe(
            "TDOA_REQUEST_FAILED",
            self.failed_events.append
        )

        self.event_bus.subscribe(
            "TDOA_RECORDING",
            self.recording_events.append
        )

        self.event_bus.subscribe(
            "TDOA_VALID_RECORDING",
            self.valid_recording_events.append
        )

        self.tdoa_dispatcher.start()

    def tearDown(
        self
    ):
        self.communication_dispatcher.stop()
        self.tdoa_dispatcher.stop()
        self.temp_directory.cleanup()

    # ========================================================
    # REQUIRED BLOCK 5 SCENARIOS
    # ========================================================

    def test_four_requested_four_valid_complete_immediately(
        self
    ):
        request_id = "block5_four_valid"
        node_ids = self._node_ids(
            4
        )

        token = self._open_request(
            request_id=request_id,
            node_ids=node_ids
        )

        for node_id in node_ids:
            result = self._upload_valid_recording(
                request_id=request_id,
                node_id=node_id,
                token=token
            )

            self.assertTrue(
                result["accepted"]
            )

        self._assert_complete(
            requested_node_ids=node_ids,
            expected_closure_reason="all_returned"
        )

    def test_six_requested_six_valid_complete_immediately(
        self
    ):
        request_id = "block5_six_valid"
        node_ids = self._node_ids(
            6
        )

        token = self._open_request(
            request_id=request_id,
            node_ids=node_ids
        )

        for node_id in node_ids:
            self._upload_valid_recording(
                request_id=request_id,
                node_id=node_id,
                token=token
            )

        self._assert_complete(
            requested_node_ids=node_ids,
            expected_closure_reason="all_returned"
        )

    def test_four_valid_two_explicit_failures_complete_immediately(
        self
    ):
        request_id = "block5_explicit_failures"
        node_ids = self._node_ids(
            6
        )

        token = self._open_request(
            request_id=request_id,
            node_ids=node_ids
        )

        for node_id in node_ids[:4]:
            self._upload_valid_recording(
                request_id=request_id,
                node_id=node_id,
                token=token
            )

        for node_id in node_ids[4:]:
            self.event_bus.publish(
                "TDOA_RECORDING",
                self._failure_event(
                    request_id=request_id,
                    node_id=node_id
                )
            )

        self._assert_complete(
            requested_node_ids=node_ids,
            expected_closure_reason="all_returned",
            expected_valid_node_ids=node_ids[:4],
            expected_failed_node_ids=node_ids[4:]
        )

    def test_four_valid_two_silent_complete_at_timeout(
        self
    ):
        request_id = "block5_timeout_quorum"
        node_ids = self._node_ids(
            6
        )

        token = self._open_request(
            request_id=request_id,
            node_ids=node_ids
        )

        for node_id in node_ids[:4]:
            self._upload_valid_recording(
                request_id=request_id,
                node_id=node_id,
                token=token
            )

        self._close_at_timeout()

        self._assert_complete(
            requested_node_ids=node_ids,
            expected_closure_reason="timeout_quorum",
            expected_valid_node_ids=node_ids[:4],
            expected_missing_node_ids=node_ids[4:]
        )

    def test_three_valid_fail_at_timeout_without_calculation(
        self
    ):
        request_id = "block5_timeout_failure"
        node_ids = self._node_ids(
            6
        )

        token = self._open_request(
            request_id=request_id,
            node_ids=node_ids
        )

        for node_id in node_ids[:3]:
            self._upload_valid_recording(
                request_id=request_id,
                node_id=node_id,
                token=token
            )

        self._close_at_timeout()

        self.assertEqual(
            self.complete_events,
            []
        )

        self.assertEqual(
            len(self.failed_events),
            1
        )

        failure_payload = self.failed_events[
            0
        ][
            "payload"
        ]

        self.assertEqual(
            failure_payload["closure_reason"],
            "timeout"
        )

        self.assertEqual(
            failure_payload["failure_reason"],
            "below_quorum"
        )

        self.assertEqual(
            failure_payload["valid_recording_count"],
            3
        )

        self.assertEqual(
            self.calculation_manager.calls,
            []
        )

    def test_identical_duplicate_upload_is_idempotent(
        self
    ):
        request_id = "block5_identical_duplicate"
        node_ids = self._node_ids(
            4
        )
        node_id = node_ids[0]

        token = self._open_request(
            request_id=request_id,
            node_ids=node_ids
        )

        wav_bytes = self._wav_bytes(
            sample_value=7
        )

        first_result = self._upload_valid_recording(
            request_id=request_id,
            node_id=node_id,
            token=token,
            wav_bytes=wav_bytes
        )

        second_result = self._upload_valid_recording(
            request_id=request_id,
            node_id=node_id,
            token=token,
            wav_bytes=wav_bytes
        )

        self.assertEqual(
            first_result["http_status"],
            201
        )

        self.assertFalse(
            first_result["idempotent"]
        )

        self.assertTrue(
            first_result["publish_events"]
        )

        self.assertEqual(
            second_result["http_status"],
            200
        )

        self.assertTrue(
            second_result["idempotent"]
        )

        self.assertFalse(
            second_result["publish_events"]
        )

        self.assertEqual(
            second_result["receipt"],
            first_result["receipt"]
        )

        self.assertEqual(
            len(self.valid_recording_events),
            1
        )

    def test_conflicting_duplicate_is_rejected_and_logged(
        self
    ):
        request_id = "block5_conflicting_duplicate"
        node_ids = self._node_ids(
            4
        )
        node_id = node_ids[0]

        token = self._open_request(
            request_id=request_id,
            node_ids=node_ids
        )

        first_result = self._upload_valid_recording(
            request_id=request_id,
            node_id=node_id,
            token=token,
            wav_bytes=self._wav_bytes(
                sample_value=11
            )
        )

        with self.assertLogs(
            level="WARNING"
        ) as captured_logs:
            conflict_result = self._upload_valid_recording(
                request_id=request_id,
                node_id=node_id,
                token=token,
                wav_bytes=self._wav_bytes(
                    sample_value=19
                )
            )

        self.assertTrue(
            first_result["accepted"]
        )

        self.assertFalse(
            conflict_result["accepted"]
        )

        self.assertEqual(
            conflict_result["http_status"],
            409
        )

        self.assertEqual(
            conflict_result["receipt"]["failure_reason"],
            "upload_conflicting_retry"
        )

        self.assertTrue(
            any(
                "TDOA upload rejected"
                in message
                and "upload_conflicting_retry"
                in message
                for message in captured_logs.output
            )
        )

        self.assertEqual(
            len(self.valid_recording_events),
            1
        )

    # ========================================================
    # CHECKPOINT HELPERS
    # ========================================================

    def _open_request(
        self,
        request_id,
        node_ids
    ):
        request = self._request(
            request_id=request_id,
            node_ids=node_ids
        )

        self.tdoa_dispatcher.recording_manager.open_request(
            request=request,
            candidate={
                "candidate_key": (
                    "candidate_"
                    +
                    request_id
                ),
                "node_ids": list(
                    node_ids
                )
            }
        )

        registration = (
            self.upload_manager.register_expected_request(
                request_id=request_id,
                target_nodes=node_ids,
                request_items=request["request_items"]
            )
        )

        return registration[
            "token"
        ]

    def _upload_valid_recording(
        self,
        request_id,
        node_id,
        token,
        wav_bytes=None
    ):
        if wav_bytes is None:
            wav_bytes = self._wav_bytes(
                sample_value=int(
                    node_id.split("_")[-1]
                )
            )

        metadata = self._recording_metadata(
            request_id=request_id,
            node_id=node_id,
            wav_bytes=wav_bytes
        )

        return (
            self.communication_dispatcher.handle_tdoa_http_upload(
                {
                    "metadata_bytes": json.dumps(
                        metadata,
                        sort_keys=True
                    ).encode(
                        "utf-8"
                    ),
                    "wav_bytes": wav_bytes,
                    "wav_filename": (
                        f"recording_{node_id}.wav"
                    ),
                    "token": token,
                    "source_ip": "127.0.0.1"
                }
            )
        )

    def _close_at_timeout(
        self
    ):
        self.clock.advance(
            15.1
        )

        closures = (
            self.tdoa_dispatcher
            .recording_manager
            .close_expired_requests()
        )

        self.assertEqual(
            len(closures),
            1
        )

        for closure in closures:
            self.tdoa_dispatcher._handle_collection_update(
                closure
            )

    def _assert_complete(
        self,
        requested_node_ids,
        expected_closure_reason,
        expected_valid_node_ids=None,
        expected_failed_node_ids=None,
        expected_missing_node_ids=None
    ):
        if expected_valid_node_ids is None:
            expected_valid_node_ids = requested_node_ids

        if expected_failed_node_ids is None:
            expected_failed_node_ids = []

        if expected_missing_node_ids is None:
            expected_missing_node_ids = []

        self.assertEqual(
            self.failed_events,
            []
        )

        self.assertEqual(
            len(self.complete_events),
            1
        )

        complete_payload = self.complete_events[
            0
        ][
            "payload"
        ]

        self.assertEqual(
            complete_payload["closure_reason"],
            expected_closure_reason
        )

        self.assertEqual(
            complete_payload["requested_node_ids"],
            requested_node_ids
        )

        self.assertEqual(
            complete_payload["valid_node_ids"],
            expected_valid_node_ids
        )

        self.assertEqual(
            complete_payload["failed_node_ids"],
            expected_failed_node_ids
        )

        self.assertEqual(
            complete_payload["missing_node_ids"],
            expected_missing_node_ids
        )

        self.assertEqual(
            len(
                complete_payload["recording_references"]
            ),
            len(
                expected_valid_node_ids
            )
        )

        self.assertEqual(
            len(self.calculation_manager.calls),
            1
        )

        calculation_call = self.calculation_manager.calls[
            0
        ]

        self.assertEqual(
            len(
                calculation_call["recording_events"]
            ),
            len(
                expected_valid_node_ids
            )
        )

    @staticmethod
    def _node_ids(
        count
    ):
        return [
            f"node_{index:02d}"
            for index in range(
                1,
                count + 1
            )
        ]

    @staticmethod
    def _request(
        request_id,
        node_ids
    ):
        return {
            "event_type": "TDOA_REQUEST",
            "tdoa_request_id": request_id,
            "request_id": request_id,
            "candidate_key": (
                "candidate_"
                +
                request_id
            ),
            "target_nodes": list(
                node_ids
            ),
            "request_items": {
                node_id: {
                    "node_id": node_id,
                    "recording_id": (
                        f"recording_{node_id}"
                    )
                }
                for node_id in node_ids
            }
        }

    @staticmethod
    def _failure_event(
        request_id,
        node_id
    ):
        return {
            "event_type": "TDOA_RECORDING",
            "source": "microphone",
            "target": "tdoa",
            "payload": {
                "tdoa_request_id": request_id,
                "request_id": request_id,
                "node_id": node_id,
                "recording_id": (
                    f"recording_{node_id}"
                ),
                "status": "failure",
                "failure_reason": "recording_not_found",
                "failure_detail": (
                    "Block 5 explicit failure."
                )
            }
        }

    @staticmethod
    def _wav_bytes(
        sample_value
    ):
        frame_count = 480

        sample = int(
            sample_value
        ).to_bytes(
            2,
            byteorder="little",
            signed=True
        )

        buffer = io.BytesIO()

        with wave.open(
            buffer,
            "wb"
        ) as wav_file:
            wav_file.setnchannels(
                1
            )
            wav_file.setsampwidth(
                2
            )
            wav_file.setframerate(
                48000
            )
            wav_file.writeframes(
                sample
                *
                frame_count
            )

        return buffer.getvalue()

    @staticmethod
    def _recording_metadata(
        request_id,
        node_id,
        wav_bytes
    ):
        frame_count = 480
        filename = f"recording_{node_id}.wav"
        recording_id = f"recording_{node_id}"
        wav_sha256 = hashlib.sha256(
            wav_bytes
        ).hexdigest()

        upload_manifest = {
            "schema_version": 1,
            "transport": "http_multipart",
            "field_name": "wav",
            "content_type": "audio/wav",
            "tdoa_request_id": request_id,
            "node_id": node_id,
            "recording_id": recording_id,
            "filename": filename,
            "byte_count": len(
                wav_bytes
            ),
            "sha256": wav_sha256
        }

        payload = {
            "tdoa_request_id": request_id,
            "request_id": request_id,
            "node_id": node_id,
            "recording_id": recording_id,
            "requested_recording_id": recording_id,
            "status": "success",
            "recording_engine": "continuous_pps",
            "continuous_stream": True,
            "timing_state": "raw",
            "boundary_utc": "2026-07-25T23:00:00Z",
            "boundary_epoch": 1785020400.0,
            "boundary_sample": 0,
            "guarded_stream_start_sample": 0,
            "guarded_stream_end_sample_exclusive": frame_count,
            "raw_timing_quality": "RAW",
            "timing_issues": [],
            "channels": 1,
            "sample_width_bytes": 2,
            "sample_rate": 48000,
            "frame_count": frame_count,
            "guarded_frame_count": frame_count,
            "upload_manifest": upload_manifest
        }

        return {
            "event_type": "TDOA_RECORDING",
            "source": "microphone",
            "target": "server",
            "status": "success",
            "tdoa_request_id": request_id,
            "request_id": request_id,
            "node_id": node_id,
            "recording_id": recording_id,
            "upload_manifest": upload_manifest,
            "payload": payload
        }


if __name__ == "__main__":
    unittest.main()
