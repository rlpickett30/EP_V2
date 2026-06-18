"""
RTK_base_manager.py

Temporary-to-platform RTK base manager.

Responsibilities:
- Use the shared FP9Driver owned by GPSManager.
- Optionally configure the local ZED-F9P as a Survey-In base.
- Consume RTCM3 packets extracted from the local F9P stream.
- Broadcast or unicast RTCM packets to rover nodes over UDP.

Does NOT:
- Own EventBus logic.
- Own node identity.
- Open the serial port separately from GPSManager.
"""

from __future__ import annotations

import socket
import time
from typing import Any, Dict, List, Tuple


class RTKBaseManager:

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

        self.configure_on_start = bool(
            self.config.get(
                "configure_on_start",
                True,
            )
        )

        self.broadcast_enabled = bool(
            self.config.get(
                "broadcast_enabled",
                False,
            )
        )

        self.broadcast_address = str(
            self.config.get(
                "broadcast_address",
                "255.255.255.255",
            )
        )

        self.targets = self.build_targets(
            self.config.get(
                "udp_targets",
                [],
            )
        )

        self.socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        if self.broadcast_enabled:
            self.socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_BROADCAST,
                1,
            )

        self.started = False
        self.last_report_time = time.time()
        self.packets_sent = 0
        self.bytes_sent = 0

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(
        self,
        message: str,
    ) -> None:

        if self.debug:
            print(
                f"[RTKBaseManager] {message}"
            )

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def start(
        self
    ) -> None:

        if not self.enabled:
            self.log(
                "Base manager disabled"
            )
            return

        if self.started:
            return

        self.log(
            "Starting RTK base manager"
        )

        if self.configure_on_start:
            survey_config = self.config.get(
                "survey_in",
                {},
            )

            duration_sec = int(
                survey_config.get(
                    "duration_sec",
                    120,
                )
            )

            accuracy_limit_mm = int(
                survey_config.get(
                    "accuracy_limit_mm",
                    5000,
                )
            )

            rtcm_messages = self.config.get(
                "rtcm_messages",
                [
                    "1005",
                    "1077",
                    "1087",
                    "1097",
                    "1127",
                    "1230",
                ],
            )

            configured = self.driver.configure_survey_in_base(
                duration_sec=duration_sec,
                accuracy_limit_mm=accuracy_limit_mm,
                rtcm_messages=rtcm_messages,
            )

            self.log(
                f"Survey-In base configuration sent: {configured}"
            )

        if not self.targets and not self.broadcast_enabled:
            self.log(
                "No UDP rover targets configured. RTCM will be consumed but not sent."
            )

        self.started = True

    def close(
        self
    ) -> None:

        try:
            self.socket.close()

        except Exception as error:
            self.log(
                f"Socket close failed: {error}"
            )

    # --------------------------------------------------
    # Target Handling
    # --------------------------------------------------

    def build_targets(
        self,
        raw_targets,
    ) -> List[Tuple[str, int]]:

        targets: List[Tuple[str, int]] = []

        if not isinstance(
            raw_targets,
            list,
        ):
            return targets

        for item in raw_targets:
            host = None
            port = self.udp_port

            if isinstance(
                item,
                str,
            ):
                if not item.strip():
                    continue

                if ":" in item:
                    host_part, port_part = item.rsplit(
                        ":",
                        1,
                    )
                    host = host_part.strip()
                    port = int(
                        port_part
                    )
                else:
                    host = item.strip()

            elif isinstance(
                item,
                dict,
            ):
                host = item.get(
                    "host"
                ) or item.get(
                    "ip"
                )
                port = int(
                    item.get(
                        "port",
                        self.udp_port,
                    )
                )

            if host:
                targets.append(
                    (
                        host,
                        port,
                    )
                )

        return targets

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

        packets = self.driver.consume_rtcm_packets()

        for packet in packets:
            self.send_packet(
                packet
            )

        self.maybe_report()

    def send_packet(
        self,
        packet: bytes,
    ) -> None:

        addresses = list(
            self.targets
        )

        if self.broadcast_enabled:
            addresses.append(
                (
                    self.broadcast_address,
                    self.udp_port,
                )
            )

        for address in addresses:
            try:
                self.socket.sendto(
                    packet,
                    address,
                )
                self.packets_sent += 1
                self.bytes_sent += len(
                    packet
                )

            except Exception as error:
                self.log(
                    f"RTCM send failed to {address}: {error}"
                )

    def maybe_report(
        self
    ) -> None:

        now = time.time()

        if now - self.last_report_time < self.report_interval_sec:
            return

        self.log(
            f"RTCM sent: packets={self.packets_sent} bytes={self.bytes_sent} targets={self.targets} broadcast={self.broadcast_enabled}"
        )

        self.packets_sent = 0
        self.bytes_sent = 0
        self.last_report_time = now
