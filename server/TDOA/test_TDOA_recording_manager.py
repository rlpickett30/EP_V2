import unittest

import sys

from pathlib import Path


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
        return "2026-07-25T22:00:00Z"

    def advance(
        self,
        seconds
    ):
        self.monotonic_value += float(
            seconds
        )


class TDOARecordingManagerTests(
    unittest.TestCase
):

    def setUp(
        self
    ):

        self.clock = FakeClock()

        self.manager = TDOARecordingManager(
            config={
                "tdoa_recording_manager": {
                    "minimum_valid_recordings": 4,
                    "collection_timeout_seconds": 15.0,
                    "deadline_poll_interval_seconds": 0.25,
                    "max_closed_requests": 20
                }
            },
            monotonic_now=self.clock.monotonic,
            utc_now=self.clock.utc
        )

    def test_all_returned_closes_with_exact_valid_recordings(
        self
    ):

        node_ids = [
            "node_01",
            "node_02",
            "node_03",
            "node_05"
        ]

        self.manager.open_request(
            request=self._request(
                "request_all",
                node_ids
            ),
            candidate={
                "candidate_key": "candidate_all"
            }
        )

        update = None

        for node_id in node_ids:

            raw_update = self.manager.record_node_answer(
                self._raw_event(
                    request_id="request_all",
                    node_id=node_id,
                    status="success"
                )
            )

            self.assertEqual(
                raw_update["action"],
                "pending"
            )

            update = self.manager.record_valid_recording(
                self._valid_event(
                    request_id="request_all",
                    node_id=node_id
                )
            )

        self.assertEqual(
            update["action"],
            "complete"
        )

        payload = update[
            "payload"
        ]

        self.assertEqual(
            payload["closure_reason"],
            "all_returned"
        )

        self.assertEqual(
            payload["valid_recording_count"],
            4
        )

        self.assertEqual(
            payload["missing_node_ids"],
            []
        )

        self.assertEqual(
            [
                reference["server_wav_path"]
                for reference in payload[
                    "recording_references"
                ]
            ],
            [
                f"/server/accepted/{node_id}.wav"
                for node_id in node_ids
            ]
        )

    def test_timeout_closes_with_quorum_and_missing_nodes(
        self
    ):

        requested_node_ids = [
            "node_01",
            "node_02",
            "node_03",
            "node_04",
            "node_05",
            "node_06"
        ]

        valid_node_ids = requested_node_ids[
            :4
        ]

        self.manager.open_request(
            request=self._request(
                "request_timeout_quorum",
                requested_node_ids
            ),
            candidate={
                "candidate_key": "candidate_timeout"
            }
        )

        for node_id in valid_node_ids:

            self.manager.record_node_answer(
                self._raw_event(
                    request_id="request_timeout_quorum",
                    node_id=node_id,
                    status="success"
                )
            )

            self.manager.record_valid_recording(
                self._valid_event(
                    request_id="request_timeout_quorum",
                    node_id=node_id
                )
            )

        self.clock.advance(
            15.1
        )

        closures = (
            self.manager.close_expired_requests()
        )

        self.assertEqual(
            len(closures),
            1
        )

        closure = closures[
            0
        ]

        self.assertEqual(
            closure["action"],
            "complete"
        )

        self.assertEqual(
            closure["payload"]["closure_reason"],
            "timeout_quorum"
        )

        self.assertEqual(
            closure["payload"]["valid_node_ids"],
            valid_node_ids
        )

        self.assertEqual(
            closure["payload"]["missing_node_ids"],
            [
                "node_05",
                "node_06"
            ]
        )

    def test_all_returned_below_quorum_fails_before_timeout(
        self
    ):

        requested_node_ids = [
            "node_01",
            "node_02",
            "node_03",
            "node_05"
        ]

        self.manager.open_request(
            request=self._request(
                "request_below_quorum",
                requested_node_ids
            ),
            candidate={
                "candidate_key": "candidate_failure"
            }
        )

        for node_id in requested_node_ids[
            :3
        ]:

            self.manager.record_node_answer(
                self._raw_event(
                    request_id="request_below_quorum",
                    node_id=node_id,
                    status="success"
                )
            )

            self.manager.record_valid_recording(
                self._valid_event(
                    request_id="request_below_quorum",
                    node_id=node_id
                )
            )

        failure = self.manager.record_node_answer(
            self._raw_event(
                request_id="request_below_quorum",
                node_id="node_05",
                status="failure",
                failure_reason="recording_not_found"
            )
        )

        self.assertEqual(
            failure["action"],
            "failed"
        )

        self.assertEqual(
            failure["payload"]["closure_reason"],
            "all_returned"
        )

        self.assertEqual(
            failure["payload"]["failure_reason"],
            "below_quorum"
        )

        self.assertEqual(
            failure["payload"]["valid_recording_count"],
            3
        )

        self.assertEqual(
            failure["payload"]["failed_node_ids"],
            [
                "node_05"
            ]
        )

    def test_four_valid_and_two_failures_complete_immediately(
        self
    ):

        requested_node_ids = [
            "node_01",
            "node_02",
            "node_03",
            "node_04",
            "node_05",
            "node_06"
        ]

        self.manager.open_request(
            request=self._request(
                "request_quorum_failures",
                requested_node_ids
            ),
            candidate={
                "candidate_key": "candidate_quorum_failures"
            }
        )

        for node_id in requested_node_ids[
            :4
        ]:

            self.manager.record_node_answer(
                self._raw_event(
                    request_id="request_quorum_failures",
                    node_id=node_id,
                    status="success"
                )
            )

            self.manager.record_valid_recording(
                self._valid_event(
                    request_id="request_quorum_failures",
                    node_id=node_id
                )
            )

        update = None

        for node_id in requested_node_ids[
            4:
        ]:

            update = self.manager.record_node_answer(
                self._raw_event(
                    request_id="request_quorum_failures",
                    node_id=node_id,
                    status="failure",
                    failure_reason="recording_not_found"
                )
            )

        self.assertEqual(
            update["action"],
            "complete"
        )

        self.assertEqual(
            update["payload"]["closure_reason"],
            "all_returned"
        )

        self.assertEqual(
            update["payload"]["valid_recording_count"],
            4
        )

        self.assertEqual(
            update["payload"]["failed_node_ids"],
            [
                "node_05",
                "node_06"
            ]
        )

    def test_timeout_below_quorum_fails_without_complete_set(
        self
    ):

        requested_node_ids = [
            "node_01",
            "node_02",
            "node_03",
            "node_04",
            "node_05",
            "node_06"
        ]

        self.manager.open_request(
            request=self._request(
                "request_timeout_failure",
                requested_node_ids
            ),
            candidate={
                "candidate_key": "candidate_timeout_failure"
            }
        )

        for node_id in requested_node_ids[
            :3
        ]:

            self.manager.record_node_answer(
                self._raw_event(
                    request_id="request_timeout_failure",
                    node_id=node_id,
                    status="success"
                )
            )

            self.manager.record_valid_recording(
                self._valid_event(
                    request_id="request_timeout_failure",
                    node_id=node_id
                )
            )

        self.clock.advance(
            15.1
        )

        closures = (
            self.manager.close_expired_requests()
        )

        self.assertEqual(
            len(closures),
            1
        )

        closure = closures[
            0
        ]

        self.assertEqual(
            closure["action"],
            "failed"
        )

        self.assertEqual(
            closure["payload"]["closure_reason"],
            "timeout"
        )

        self.assertEqual(
            closure["payload"]["failure_reason"],
            "below_quorum"
        )

        self.assertEqual(
            closure["payload"]["valid_recording_count"],
            3
        )

    def _request(
        self,
        request_id,
        node_ids
    ):

        return {
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
                    "recording_id": f"recording_{node_id}"
                }
                for node_id in node_ids
            }
        }

    def _raw_event(
        self,
        request_id,
        node_id,
        status,
        failure_reason=None
    ):

        return {
            "event_type": "TDOA_RECORDING",
            "source": "microphone",
            "payload": {
                "tdoa_request_id": request_id,
                "request_id": request_id,
                "node_id": node_id,
                "recording_id": f"recording_{node_id}",
                "status": status,
                "failure_reason": failure_reason,
                "failure_detail": None
            }
        }

    def _valid_event(
        self,
        request_id,
        node_id
    ):

        return {
            "event_type": "TDOA_VALID_RECORDING",
            "source": "communication",
            "payload": {
                "tdoa_request_id": request_id,
                "request_id": request_id,
                "node_id": node_id,
                "recording_id": f"recording_{node_id}",
                "status": "success",
                "validation_status": "accepted",
                "server_wav_path": (
                    f"/server/accepted/{node_id}.wav"
                ),
                "sample_rate_hz": 48000,
                "channels": 1,
                "sample_width_bytes": 2,
                "frame_count": 768000
            }
        }


class FakeCalculationManager:

    def tdoa_estimate(
        self,
        candidate,
        recording_events=None
    ):

        return {
            "success": True,
            "candidate": candidate,
            "exact_recording_event_count": len(
                recording_events or []
            )
        }


class FakeClockAlignmentManager:
    """
    Keep the Block 4 collection integration test focused on raw closure.
    """

    def align_complete_set(
        self,
        raw_complete_set
    ):

        return {
            "success": True,
            "status": "complete",
            "failure_reason": None,
            "complete_set": raw_complete_set,
            "failure_payload": None,
            "clock_alignment": {
                "status": "BYPASSED_BY_BLOCK_4_TEST"
            }
        }


class TDOADispatcherCollectionIntegrationTests(
    unittest.TestCase
):

    def test_event_services_publish_exact_complete_set(
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

        dispatcher.manager = FakeCalculationManager()
        dispatcher.clock_alignment_manager = (
            FakeClockAlignmentManager()
        )

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

        node_ids = [
            "node_01",
            "node_02",
            "node_03",
            "node_05"
        ]

        request = {
            "tdoa_request_id": "integration_request",
            "request_id": "integration_request",
            "candidate_key": "integration_candidate",
            "target_nodes": node_ids,
            "request_items": {
                node_id: {
                    "node_id": node_id,
                    "recording_id": f"recording_{node_id}"
                }
                for node_id in node_ids
            }
        }

        dispatcher.start()

        try:

            dispatcher.recording_manager.open_request(
                request=request,
                candidate={
                    "candidate_key": "integration_candidate",
                    "node_ids": node_ids
                }
            )

            helper = TDOARecordingManagerTests()

            for node_id in node_ids:

                event_bus.publish(
                    "TDOA_RECORDING",
                    helper._raw_event(
                        request_id="integration_request",
                        node_id=node_id,
                        status="success"
                    )
                )

                event_bus.publish(
                    "TDOA_VALID_RECORDING",
                    helper._valid_event(
                        request_id="integration_request",
                        node_id=node_id
                    )
                )

        finally:
            dispatcher.stop()

        self.assertEqual(
            failed_events,
            []
        )

        self.assertEqual(
            len(complete_events),
            1
        )

        complete_payload = complete_events[
            0
        ][
            "payload"
        ]

        self.assertEqual(
            complete_payload["closure_reason"],
            "all_returned"
        )

        self.assertEqual(
            complete_payload["valid_node_ids"],
            node_ids
        )

        self.assertEqual(
            [
                reference["server_wav_path"]
                for reference in complete_payload[
                    "recording_references"
                ]
            ],
            [
                f"/server/accepted/{node_id}.wav"
                for node_id in node_ids
            ]
        )


if __name__ == "__main__":
    unittest.main()
