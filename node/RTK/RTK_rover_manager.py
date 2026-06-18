"""
RTK_rover_manager.py

Temporary-to-platform RTK rover manager.

Responsibilities:
- Listen for RTCM3 correction packets over UDP.
- Write received RTCM bytes into the local ZED-F9P using the shared FP9Driver.

Does NOT:
- Own EventBus logic.
- Own node identity.
- Open the serial port separately from GPSManager.
"""

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
        self.packets_received = 0
        self.bytes_received = 0
        self.bytes_written = 0

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
