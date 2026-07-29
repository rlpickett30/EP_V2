# ============================================================
# test_TDOA_retry_workflow.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Role:
#   Test
#
# Purpose:
#   Verify one active TDOA attempt, one attempt per recording
#   frame, and immediate rearming after terminal outcomes.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Verifies multiple recording frames remain discoverable
#   - Verifies an active attempt blocks additional requests
#   - Verifies terminal failure launches the next buffered frame
#   - Verifies a late fifth-node detection cannot repeat a frame
#
# Does NOT:
#   - Exercise real HTTP recording transfer
#   - Exercise real clock alignment
#   - Exercise the numerical TDOA solver
#
# Owner:
#   TDOA_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import sys
import unittest

from pathlib import Path


SERVER_ROOT = Path(
    __file__
).resolve().parents[1]

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(SERVER_ROOT)
    )


# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from TDOA.candidate_filter import CandidateFilter
from TDOA.TDOA_dispatcher import TDOADispatcher


# ============================================================
# TEST SUPPORT
# ============================================================

class FakeEventBus:

    def subscribe(
        self,
        event_name,
        callback
    ):
        return None

    def publish(
        self,
        event_name,
        payload
    ):
        return None


class FakeStateManager:

    NODE_IDS = [
        "node_01",
        "node_02",
        "node_03",
        "node_04",
        "node_05"
    ]

    def get_state_snapshot(
        self
    ):
        return {
            "candidate_filter_allowed": True,
            "tdoa_capable_node_ids": list(
                self.NODE_IDS
            )
        }


class FakeRecordingManager:

    def __init__(
        self
    ):
        self.opened_requests = []

    def open_request(
        self,
        request,
        candidate=None
    ):
        self.opened_requests.append(
            request
        )

        return {
            "collection_deadline_at_utc": (
                "2026-07-29T23:59:59Z"
            )
        }


class FakeEventServices:

    def __init__(
        self
    ):
        self.candidates = []
        self.requests = []
        self.request_failures = []
        self.complete_sets = []
        self.calc_started = []
        self.calc_requested = []
        self.calc_results = []
        self.calc_failures = []

    def publish_tdoa_candidate_ready(
        self,
        payload
    ):
        self.candidates.append(
            payload
        )

    def publish_tdoa_request(
        self,
        payload
    ):
        self.requests.append(
            payload
        )

    def publish_tdoa_request_failed(
        self,
        payload
    ):
        self.request_failures.append(
            payload
        )

    def publish_tdoa_complete_set(
        self,
        payload
    ):
        self.complete_sets.append(
            payload
        )

    def publish_tdoa_calc_started(
        self,
        payload
    ):
        self.calc_started.append(
            payload
        )

    def publish_tdoa_calc_requested(
        self,
        payload
    ):
        self.calc_requested.append(
            payload
        )

    def publish_tdoa_calc(
        self,
        payload
    ):
        self.calc_results.append(
            payload
        )

    def publish_tdoa_calc_failed(
        self,
        payload
    ):
        self.calc_failures.append(
            payload
        )


class FakeRejectedClockAlignmentManager:

    def align_complete_set(
        self,
        raw_complete_set
    ):
        request_id = raw_complete_set.get(
            "tdoa_request_id"
        )

        return {
            "success": False,
            "failure_payload": {
                "tdoa_request_id": request_id,
                "failure_reason": "below_aligned_quorum"
            },
            "clock_alignment": {
                "aligned_recording_count": 3,
                "required_aligned_recordings": 4,
                "rejected_node_ids": [
                    "node_05"
                ]
            }
        }


class FakeCalculationManager:

    def __init__(
        self,
        success
    ):
        self.success = success

    def tdoa_estimate(
        self,
        candidate,
        recording_events=None
    ):
        return {
            "success": self.success,
            "status": (
                "complete"
                if self.success
                else
                "failed"
            ),
            "candidate": candidate,
            "errors": (
                []
                if self.success
                else
                ["synthetic_calculation_failure"]
            )
        }


def build_frame_events(
    recording_id,
    base_time,
    node_count
):
    """
    Build one synthetic AVIS_LITE recording frame.
    """

    return [
        {
            "node_id": node_id,
            "avis_lite_id": "bcch",
            "node_time": base_time + index * 0.001,
            "recording_id": recording_id,
            "recording_utc": (
                "2026-07-29T22:00:00Z"
            ),
            "payload": {
                "node_id": node_id,
                "species_code": "bcch",
                "recording_id": recording_id
            }
        }
        for index, node_id in enumerate(
            FakeStateManager.NODE_IDS[
                :node_count
            ]
        )
    ]


# ============================================================
# TESTS
# ============================================================

class CandidateFilterRetryTests(
    unittest.TestCase
):

    def setUp(
        self
    ):
        self.candidate_filter = CandidateFilter(
            config={
                "candidate_filter": {
                    "avis_lite_match_window_seconds": 0.050,
                    "min_matching_nodes": 4
                }
            }
        )

        self.capability = {
            "candidate_filter_allowed": True,
            "tdoa_capable_node_ids": list(
                FakeStateManager.NODE_IDS
            )
        }

    def test_returns_multiple_frames_for_same_species(
        self
    ):
        events = (
            build_frame_events(
                recording_id="recording_frame_a",
                base_time=1000.0,
                node_count=4
            )
            +
            build_frame_events(
                recording_id="recording_frame_b",
                base_time=1030.0,
                node_count=4
            )
        )

        candidates = self.candidate_filter.find_candidates(
            capability_event=self.capability,
            recent_avis_lite_events=events
        )

        self.assertEqual(
            len(candidates),
            2
        )

        self.assertEqual(
            {
                candidate["frame_key"]
                for candidate in candidates
            },
            {
                "recording_id:recording_frame_a",
                "recording_id:recording_frame_b"
            }
        )

    def test_one_frame_uses_all_available_unique_nodes(
        self
    ):
        candidates = self.candidate_filter.find_candidates(
            capability_event=self.capability,
            recent_avis_lite_events=build_frame_events(
                recording_id="recording_five_nodes",
                base_time=2000.0,
                node_count=5
            )
        )

        self.assertEqual(
            len(candidates),
            1
        )

        self.assertEqual(
            candidates[0]["node_count"],
            5
        )


class DispatcherRetryTests(
    unittest.TestCase
):

    def setUp(
        self
    ):
        self.candidate_filter = CandidateFilter(
            config={
                "candidate_filter": {
                    "avis_lite_match_window_seconds": 0.050,
                    "min_matching_nodes": 4
                }
            }
        )

        self.capability = {
            "candidate_filter_allowed": True,
            "tdoa_capable_node_ids": list(
                FakeStateManager.NODE_IDS
            )
        }

        self.dispatcher = TDOADispatcher(
            event_bus=FakeEventBus(),
            config_path=str(
                SERVER_ROOT
                /
                "TDOA"
                /
                "TDOA_config.json"
            )
        )

        self.dispatcher.state_manager = FakeStateManager()
        self.dispatcher.candidate_filter = self.candidate_filter
        self.dispatcher.recording_manager = FakeRecordingManager()
        self.dispatcher.event_services = FakeEventServices()
        self.dispatcher.running = True

    def test_failure_rearms_and_launches_next_buffered_frame(
        self
    ):
        frame_a_first_four = build_frame_events(
            recording_id="recording_frame_a",
            base_time=3000.0,
            node_count=4
        )

        self.dispatcher.recent_avis_lite_events.extend(
            frame_a_first_four
        )

        self.dispatcher._run_candidate_filter_if_allowed()

        self.assertEqual(
            len(self.dispatcher.event_services.requests),
            1
        )

        first_request = (
            self.dispatcher.event_services.requests[0]
        )

        self.assertFalse(
            self.dispatcher.candidate_attempt_armed
        )

        late_fifth_node = build_frame_events(
            recording_id="recording_frame_a",
            base_time=3000.0,
            node_count=5
        )[-1]

        frame_b = build_frame_events(
            recording_id="recording_frame_b",
            base_time=3030.0,
            node_count=4
        )

        self.dispatcher.recent_avis_lite_events.append(
            late_fifth_node
        )

        self.dispatcher.recent_avis_lite_events.extend(
            frame_b
        )

        self.dispatcher._run_candidate_filter_if_allowed()

        self.assertEqual(
            len(self.dispatcher.event_services.requests),
            1
        )

        self.dispatcher._handle_collection_update(
            {
                "action": "failed",
                "tdoa_request_id": first_request[
                    "tdoa_request_id"
                ],
                "payload": {
                    "tdoa_request_id": first_request[
                        "tdoa_request_id"
                    ],
                    "closure_reason": "timeout",
                    "valid_recording_count": 3,
                    "required_valid_recordings": 4,
                    "missing_node_ids": [
                        "node_05"
                    ]
                }
            }
        )

        self.assertEqual(
            len(self.dispatcher.event_services.requests),
            2
        )

        second_request = (
            self.dispatcher.event_services.requests[1]
        )

        self.assertEqual(
            first_request["candidate_key"],
            "recording_id:recording_frame_a"
        )

        self.assertEqual(
            second_request["candidate_key"],
            "recording_id:recording_frame_b"
        )

        self.assertNotEqual(
            first_request["tdoa_request_id"],
            second_request["tdoa_request_id"]
        )

        self.assertFalse(
            self.dispatcher.candidate_attempt_armed
        )

        self.assertEqual(
            self.dispatcher.active_tdoa_request_id,
            second_request["tdoa_request_id"]
        )

    def test_late_fifth_node_does_not_repeat_consumed_frame(
        self
    ):
        first_four = build_frame_events(
            recording_id="recording_single_frame",
            base_time=4000.0,
            node_count=4
        )

        all_five = build_frame_events(
            recording_id="recording_single_frame",
            base_time=4000.0,
            node_count=5
        )

        four_node_candidate = (
            self.candidate_filter.find_candidates(
                capability_event=self.capability,
                recent_avis_lite_events=first_four
            )[0]
        )

        five_node_candidate = (
            self.candidate_filter.find_candidates(
                capability_event=self.capability,
                recent_avis_lite_events=all_five
            )[0]
        )

        self.assertEqual(
            self.dispatcher._build_candidate_key(
                four_node_candidate
            ),
            self.dispatcher._build_candidate_key(
                five_node_candidate
            )
        )

    def test_clock_alignment_rejection_rearms_attempt(
        self
    ):
        request_id = "request_clock_rejected"

        self.dispatcher._disarm_candidate_attempt(
            request_id=request_id,
            candidate_key="recording_id:clock_frame"
        )

        self.dispatcher.clock_alignment_manager = (
            FakeRejectedClockAlignmentManager()
        )

        self.dispatcher._handle_collection_update(
            {
                "action": "complete",
                "tdoa_request_id": request_id,
                "payload": {
                    "tdoa_request_id": request_id
                }
            }
        )

        self.assertTrue(
            self.dispatcher.candidate_attempt_armed
        )

        self.assertIsNone(
            self.dispatcher.active_tdoa_request_id
        )

        self.assertEqual(
            len(
                self.dispatcher.event_services.request_failures
            ),
            1
        )

    def test_calculation_success_and_failure_rearm_attempt(
        self
    ):
        for success in (
            True,
            False
        ):

            with self.subTest(
                success=success
            ):
                request_id = (
                    "request_calc_success"
                    if success
                    else
                    "request_calc_failure"
                )

                self.dispatcher._disarm_candidate_attempt(
                    request_id=request_id,
                    candidate_key=(
                        f"recording_id:{request_id}"
                    )
                )

                self.dispatcher.manager = (
                    FakeCalculationManager(
                        success=success
                    )
                )

                self.dispatcher._handle_tdoa_complete_set(
                    {
                        "tdoa_request_id": request_id,
                        "candidate": {
                            "frame_key": (
                                f"recording_id:{request_id}"
                            )
                        },
                        "valid_node_ids": [
                            "node_01",
                            "node_02",
                            "node_03",
                            "node_04"
                        ],
                        "recording_events": []
                    }
                )

                self.assertTrue(
                    self.dispatcher.candidate_attempt_armed
                )

                self.assertIsNone(
                    self.dispatcher.active_tdoa_request_id
                )

        self.assertEqual(
            len(self.dispatcher.event_services.calc_results),
            1
        )

        self.assertEqual(
            len(self.dispatcher.event_services.calc_failures),
            1
        )


if __name__ == "__main__":
    unittest.main()
