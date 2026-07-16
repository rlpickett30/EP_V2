# ============================================================
# RTK_rover_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   RTK
#
# Role:
#   Manager
#
# Purpose:
#   Manage RTK rover correction transport by receiving RTCM3 packets over UDP
#   and writing them to the local ZED-F9P through the shared F9P driver.
#
# Expected config source:
#   RTK_config.json
#
# Expected config section:
#   config["rtk"]["rover"]
#
# Does:
#   - Listen for RTCM3 correction packets over UDP
#   - Write received RTCM bytes into the local ZED-F9P
#   - Use the shared FP9Driver owned by GPSManager
#   - Track RTCM receive and write counters
#   - Return role-aware RTK rover transport status snapshots
#
# Does NOT:
#   - Own EventBus logic
#   - Publish events
#   - Own node identity
#   - Open the serial port separately from GPSManager
#   - Interpret GPS fix quality directly
#   - Decide whether the node is TDOA capable
#
# Owner:
#   RTK_dispatcher.py
#
# ============================================================

from __future__ import annotations

import select
import socket
import time
from typing import Any, Dict


class RTKRoverManager:

    def __init__(
        self,
        driver,
        config: Dict[str, Any],
        debug: bool = True,
    ):
        self.driver = driver
        self.config = config
        self.debug = debug

        self.enabled = bool(
            self.config.get(
                "enabled",
                True,
            )
        )

        self.bind_host = str(
            self.config.get(
                "bind_host",
                "0.0.0.0",
            )
        )

        self.udp_port = int(
            self.config.get(
                "udp_port",
                5010,
            )
        )

        self.report_interval_sec = float(
            self.config.get(
                "report_interval_sec",
                5,
            )
        )

        self.socket = None
        self.started = False

        self.last_report_time = time.time()

        # Report-window counters. These are reset by maybe_report().
        self.packets_received = 0
        self.bytes_received = 0
        self.bytes_written = 0

        # Lifetime counters. These are never reset while the manager runs.
        self.total_packets_received = 0
        self.total_bytes_received = 0
        self.total_bytes_written = 0

        # Activity timestamps.
        self.started_epoch = None
        self.last_packet_received_epoch = None

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(
        self,
        message: str,
    ) -> None:

        if self.debug:
            print(
                f"[RTKRoverManager] {message}"
            )

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def start(
        self
    ) -> None:

        if not self.enabled:
            self.log(
                "Rover manager disabled"
            )
            return

        if self.started:
            return

        self.socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        self.socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1,
        )

        self.socket.bind(
            (
                self.bind_host,
                self.udp_port,
            )
        )

        self.socket.setblocking(
            False
        )

        self.started = True
        self.started_epoch = time.time()

        self.log(
            f"Listening for RTCM on {self.bind_host}:{self.udp_port}"
        )

    def close(
        self
    ) -> None:

        try:
            if self.socket is not None:
                self.socket.close()

        except Exception as error:
            self.log(
                f"Socket close failed: {error}"
            )

    # --------------------------------------------------
    # Runtime
    # --------------------------------------------------

    def process(
        self
    ) -> None:

        if not self.enabled:
            return

        if not self.started:
            self.start()

        if self.socket is None:
            return

        while True:
            readable, _, _ = select.select(
                [
                    self.socket,
                ],
                [],
                [],
                0,
            )

            if self.socket not in readable:
                break

            data, _address = self.socket.recvfrom(
                4096
            )

            if not data:
                continue

            written = self.driver.write_bytes(
                data
            )

            self.packets_received += 1
            self.bytes_received += len(
                data
            )
            self.bytes_written += written

            self.total_packets_received += 1
            self.total_bytes_received += len(
                data
            )
            self.total_bytes_written += written
            self.last_packet_received_epoch = time.time()

        self.maybe_report()

    def maybe_report(
        self
    ) -> None:

        now = time.time()

        if now - self.last_report_time < self.report_interval_sec:
            return

        self.log(
            f"RTCM received: packets={self.packets_received} bytes={self.bytes_received} written={self.bytes_written}"
        )

        self.packets_received = 0
        self.bytes_received = 0
        self.bytes_written = 0
        self.last_report_time = now


    # --------------------------------------------------
    # Status Snapshot
    # --------------------------------------------------

    def get_status_snapshot(
        self
    ) -> Dict[str, Any]:
        """
        Return rover RTCM receive status for dispatcher payload enrichment.
        """

        now = time.time()

        rtcm_rx_age_sec = self.seconds_since(
            now=now,
            epoch=self.last_packet_received_epoch
        )

        recent_window_sec = max(
            self.report_interval_sec * 3.0,
            10.0
        )

        rtcm_rx_online = bool(
            self.enabled
            and self.started
            and self.last_packet_received_epoch is not None
            and rtcm_rx_age_sec is not None
            and rtcm_rx_age_sec <= recent_window_sec
        )

        return {
            "rtk_role": "rover",
            "rover_enabled": self.enabled,
            "rover_started": self.started,
            "rtcm_rx_online": rtcm_rx_online,
            "bind_host": self.bind_host,
            "udp_port": self.udp_port,
            "packets_received_window": self.packets_received,
            "bytes_received_window": self.bytes_received,
            "bytes_written_window": self.bytes_written,
            "packets_received_total": self.total_packets_received,
            "bytes_received_total": self.total_bytes_received,
            "bytes_written_total": self.total_bytes_written,
            "last_packet_received_epoch": self.last_packet_received_epoch,
            "rtcm_rx_age_sec": rtcm_rx_age_sec,
            "recent_window_sec": recent_window_sec,
        }

    def seconds_since(
        self,
        now: float,
        epoch
    ):
        if epoch is None:
            return None

        try:
            return max(
                0.0,
                float(now) - float(epoch)
            )

        except Exception:
            return None
