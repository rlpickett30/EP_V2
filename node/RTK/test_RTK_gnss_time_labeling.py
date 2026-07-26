# ============================================================
# test_RTK_gnss_time_labeling.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   RTK
#
# Role:
#   Test
#
# Purpose:
#   Verify Block 6 RMC date/time parsing, PPS-to-GNSS pairing evidence,
#   rejection behavior, and the labeled PPS_EDGE contract.
#
# ============================================================

from __future__ import annotations

import sys
import types
import unittest

from datetime import datetime
from datetime import timezone
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(
    __file__
).resolve().parents[2]

NODE_ROOT = REPOSITORY_ROOT / "node"

if str(NODE_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(NODE_ROOT),
    )

if "serial" not in sys.modules:
    serial_stub = types.ModuleType(
        "serial"
    )
    serial_stub.Serial = object
    sys.modules["serial"] = serial_stub

from RTK.FP9_driver import FP9Driver
from RTK.PPS_manager import PPSManager
from RTK.RTK_dispatcher import RTKDispatcher


class GPSManagerStub:

    def __init__(
        self,
        observations
    ):
        self.observations = observations

    def get_rmc_observations(
        self
    ):
        return self.observations


class RTKEventServicesStub:

    def __init__(
        self
    ):
        self.events = []

    def publish_pps_edge(
        self,
        event
    ):
        self.events.append(
            event
        )


class RTKGNSSTimeLabelingTests(
    unittest.TestCase
):

    def make_pps_snapshot(
        self,
        edge_monotonic_ns=1_000_000_000,
        kernel_realtime_ns=123_456_789,
        sequence=42,
    ):

        return {
            "pps_valid": True,
            "pps_seq": sequence,
            "pps_edge_monotonic_ns": (
                edge_monotonic_ns
            ),
            "pps_kernel_realtime_ns": (
                kernel_realtime_ns
            ),
            "last_pps_kernel_time": (
                kernel_realtime_ns
                /
                1_000_000_000.0
            ),
            "last_pps_kernel_time_sec": (
                kernel_realtime_ns
                //
                1_000_000_000
            ),
            "last_pps_kernel_time_nsec": (
                kernel_realtime_ns
                %
                1_000_000_000
            ),
            "pps_age_sec": 0.01,
        }

    def make_observation(
        self,
        utc_ns,
        arrival_monotonic_ns=1_120_000_000,
        valid=True,
        status="A",
    ):

        return {
            "schema_version": 1,
            "source": "gnss_rmc",
            "rmc_status": status,
            "rmc_valid": valid,
            "rmc_utc_ns": utc_ns,
            "rmc_utc": (
                "2026-07-24T23:18:00Z"
            ),
            "arrival_monotonic_ns": (
                arrival_monotonic_ns
            ),
            "arrival_realtime_ns": 0,
            "raw_sentence": "$GNRMC,...",
        }

    def test_rmc_parser_preserves_full_utc_and_arrival(
        self
    ):

        driver = FP9Driver(
            debug=False
        )

        with (
            patch(
                "RTK.FP9_driver.time.monotonic_ns",
                return_value=11_120_000_000,
            ),
            patch(
                "RTK.FP9_driver.time.time_ns",
                return_value=22_120_000_000,
            ),
        ):
            driver.parse_rmc(
                (
                    "$GNRMC,231800.25,A,"
                    "3723.2475,N,12158.3416,W,"
                    "0.13,309.62,240726,,,A*00"
                )
            )

        observations = (
            driver.get_rmc_observations()
        )

        self.assertEqual(
            len(observations),
            1,
        )

        observation = observations[0]

        expected_utc_ns = (
            int(
            datetime(
                2026,
                7,
                24,
                23,
                18,
                0,
                tzinfo=timezone.utc,
            ).timestamp()
            )
            *
            1_000_000_000
            +
            250_000_000
        )

        self.assertEqual(
            observation[
                "rmc_utc_ns"
            ],
            expected_utc_ns,
        )
        self.assertEqual(
            observation[
                "arrival_monotonic_ns"
            ],
            11_120_000_000,
        )
        self.assertEqual(
            observation["source"],
            "gnss_rmc",
        )
        self.assertTrue(
            observation["rmc_valid"]
        )

    def test_mixed_rtcm_prefix_is_removed_from_rmc_sentence(
        self
    ):

        driver = FP9Driver(
            debug=False
        )

        rmc_sentence = (
            b"$GNRMC,012206.00,A,3714.75318,N,"
            b"10743.02071,W,0.000,,260726,,,D,V*0F"
        )

        mixed_stream = (
            b"\xd3\x00\x13\x24J\x01v~@\x0e4}>"
            b"\x00\x04L\x00"
            +
            rmc_sentence
            +
            b"\r\n"
        )

        parsed_count = driver.process_nmea_bytes(
            mixed_stream
        )

        observations = (
            driver.get_rmc_observations()
        )

        self.assertEqual(
            parsed_count,
            1,
        )
        self.assertEqual(
            len(observations),
            1,
        )
        self.assertEqual(
            observations[0]["raw_sentence"],
            rmc_sentence.decode("ascii"),
        )
        self.assertTrue(
            observations[0]["rmc_valid"]
        )

    def test_mixed_rmc_sentence_survives_chunk_boundary(
        self
    ):

        driver = FP9Driver(
            debug=False
        )

        first_count = driver.process_nmea_bytes(
            (
                b"\xd3\x00\x07\x00\xff$noise\x00"
                b"$GNRMC,0122"
            )
        )

        second_count = driver.process_nmea_bytes(
            (
                b"41.00,A,3714.75318,N,"
                b"10743.02071,W,0.000,,"
                b"260726,,,D,V*0C\r\n"
            )
        )

        observations = (
            driver.get_rmc_observations()
        )

        self.assertEqual(
            first_count,
            0,
        )
        self.assertEqual(
            second_count,
            1,
        )
        self.assertEqual(
            len(observations),
            1,
        )
        self.assertEqual(
            observations[0]["rmc_utc"],
            "2026-07-26T01:22:41.000000Z",
        )

    def test_pps_pairs_by_monotonic_arrival_not_system_clock(
        self
    ):

        manager = PPSManager(
            debug=False
        )

        gnss_utc_ns = int(
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

        pairing = (
            manager.pair_snapshot_with_rmc(
                pps_snapshot=(
                    self.make_pps_snapshot(
                        kernel_realtime_ns=(
                            999_999_999
                        )
                    )
                ),
                rmc_observations=[
                    self.make_observation(
                        gnss_utc_ns
                    )
                ],
                now_monotonic_ns=(
                    1_200_000_000
                ),
            )
        )

        self.assertTrue(
            pairing["utc_label_valid"]
        )
        self.assertEqual(
            pairing["utc_source"],
            "gnss_rmc_paired_to_pps",
        )
        self.assertEqual(
            pairing["gnss_utc_ns"],
            gnss_utc_ns,
        )
        self.assertAlmostEqual(
            pairing[
                "rmc_arrival_delay_ms"
            ],
            120.0,
            places=6,
        )
        self.assertEqual(
            pairing["quality_reasons"],
            [],
        )

    def test_pairing_waits_then_rejects_missing_rmc(
        self
    ):

        manager = PPSManager(
            debug=False
        )
        snapshot = self.make_pps_snapshot()

        pending = (
            manager.pair_snapshot_with_rmc(
                pps_snapshot=snapshot,
                rmc_observations=[],
                now_monotonic_ns=(
                    1_200_000_000
                ),
            )
        )

        self.assertFalse(
            pending["terminal"]
        )
        self.assertEqual(
            pending["pairing_state"],
            "pending",
        )

        rejected = (
            manager.pair_snapshot_with_rmc(
                pps_snapshot=snapshot,
                rmc_observations=[],
                now_monotonic_ns=(
                    1_800_000_000
                ),
            )
        )

        self.assertTrue(
            rejected["terminal"]
        )
        self.assertFalse(
            rejected["utc_label_valid"]
        )
        self.assertIn(
            "matching_rmc_timeout",
            rejected[
                "quality_reasons"
            ],
        )

    def test_invalid_rmc_status_is_rejected_with_evidence(
        self
    ):

        manager = PPSManager(
            debug=False
        )

        pairing = (
            manager.pair_snapshot_with_rmc(
                pps_snapshot=(
                    self.make_pps_snapshot()
                ),
                rmc_observations=[
                    self.make_observation(
                        utc_ns=1_000_000_000,
                        valid=False,
                        status="V",
                    )
                ],
                now_monotonic_ns=(
                    1_200_000_000
                ),
            )
        )

        self.assertFalse(
            pairing["utc_label_valid"]
        )
        self.assertIn(
            "rmc_observation_not_valid",
            pairing[
                "quality_reasons"
            ],
        )
        self.assertEqual(
            pairing[
                "rmc_observation"
            ][
                "rmc_status"
            ],
            "V",
        )

    def test_late_rmc_preserves_delay_and_rejection_reason(
        self
    ):

        manager = PPSManager(
            debug=False
        )

        pairing = (
            manager.pair_snapshot_with_rmc(
                pps_snapshot=(
                    self.make_pps_snapshot()
                ),
                rmc_observations=[
                    self.make_observation(
                        utc_ns=1_000_000_000,
                        arrival_monotonic_ns=(
                            1_820_000_000
                        ),
                    )
                ],
                now_monotonic_ns=(
                    1_850_000_000
                ),
            )
        )

        self.assertFalse(
            pairing["utc_label_valid"]
        )
        self.assertEqual(
            pairing[
                "quality_reasons"
            ],
            [
                "rmc_arrival_delay_exceeded"
            ],
        )
        self.assertAlmostEqual(
            pairing[
                "rmc_arrival_delay_ms"
            ],
            820.0,
            places=6,
        )
        self.assertEqual(
            pairing[
                "rmc_observation"
            ][
                "source"
            ],
            "gnss_rmc",
        )

    def test_pps_edge_contains_gnss_label_and_pairing_evidence(
        self
    ):

        dispatcher = RTKDispatcher.__new__(
            RTKDispatcher
        )
        dispatcher.node_id = "node_01"
        dispatcher.node_name = (
            "EnviroPulse Node 01"
        )

        pairing = {
            "utc_label_valid": True,
            "utc_label_state": (
                "gnss_rmc_paired"
            ),
            "utc_source": (
                "gnss_rmc_paired_to_pps"
            ),
            "quality_reasons": [],
            "gnss_utc_ns": (
                1_785_000_000_000_000_000
            ),
            "gnss_utc": (
                "2026-07-24T23:18:00Z"
            ),
            "gnss_utc_epoch": (
                1_785_000_000.0
            ),
            "rmc_arrival_delay_ms": 120.0,
        }

        event = dispatcher.build_pps_edge_event(
            pps_snapshot=(
                self.make_pps_snapshot()
            ),
            previous_pps_seq=41,
            utc_pairing=pairing,
        )

        payload = event["payload"]

        self.assertTrue(
            payload["utc_label_valid"]
        )
        self.assertEqual(
            payload["gnss_utc_ns"],
            pairing["gnss_utc_ns"],
        )
        self.assertEqual(
            payload["rmc_arrival_delay_ms"],
            120.0,
        )
        self.assertEqual(
            event["target"],
            "microphone",
        )

    def test_dispatcher_publishes_resolved_edge_once(
        self
    ):

        dispatcher = RTKDispatcher.__new__(
            RTKDispatcher
        )
        dispatcher.node_id = "node_01"
        dispatcher.node_name = (
            "EnviroPulse Node 01"
        )
        dispatcher.debug = False
        dispatcher.pps_manager = PPSManager(
            debug=False
        )
        dispatcher.pps_rmc_pairing_window_sec = (
            0.75
        )
        dispatcher.event_services = (
            RTKEventServicesStub()
        )

        gnss_utc_ns = int(
            datetime(
                2026,
                7,
                24,
                23,
                18,
                tzinfo=timezone.utc,
            ).timestamp()
        ) * 1_000_000_000

        dispatcher.gps_manager = (
            GPSManagerStub(
                [
                    self.make_observation(
                        utc_ns=gnss_utc_ns
                    )
                ]
            )
        )

        dispatcher.pending_pps_edges = {
            42: {
                "pps_snapshot": (
                    self.make_pps_snapshot()
                ),
                "previous_pps_seq": 41,
            }
        }

        dispatcher.resolve_pending_pps_edges()
        dispatcher.resolve_pending_pps_edges()

        self.assertEqual(
            len(
                dispatcher
                .event_services
                .events
            ),
            1,
        )
        self.assertEqual(
            dispatcher.pending_pps_edges,
            {},
        )
        self.assertTrue(
            dispatcher
            .event_services
            .events[0][
                "payload"
            ][
                "utc_label_valid"
            ]
        )


if __name__ == "__main__":
    unittest.main()
