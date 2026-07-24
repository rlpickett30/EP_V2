# ============================================================
# udp_sender.py
#
# EnviroPulse V2
#
# Subsystem:
#   Communication
#
# Role:
#   Helper Script
#
# Purpose:
#   Serialize outbound messages and send them as UDP packets.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["udp"]
#
# Does:
#   - Serialize outbound messages as JSON
#   - Send UDP packets to the configured default destination
#   - Send a packet to a call-specific destination
#   - Report send success or failure
#   - Preserve the configured default during call-specific sends
#   - Allow deliberate default-destination updates
#   - Close the UDP socket
#
# Does NOT:
#   - Retry messages
#   - Queue messages
#   - Store messages
#   - Decide when messages should be sent
#   - Publish events
#   - Manage communication state
#
# Owner:
#   sender_manager.py
#
# ============================================================

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json
import logging
import socket

from typing import Optional


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class UDPSender:

    def __init__(
        self,
        host: str,
        port: int
    ):

        self.host = host
        self.port = port

        self.socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

    # ========================================================
    # SEND
    # ========================================================

    def send(
        self,
        message: dict,
        destination: Optional[dict] = None
    ) -> bool:

        try:

            send_host, send_port = self._resolve_destination(
                destination
            )

            payload = json.dumps(
                message
            ).encode(
                "utf-8"
            )

            self.socket.sendto(
                payload,
                (
                    send_host,
                    send_port
                )
            )

            return True

        except Exception as error:

            logging.exception(
                f"[Communication] UDP Send Error: "
                f"{error}"
            )

            return False

    # ========================================================
    # RESOLVE DESTINATION
    # ========================================================

    def _resolve_destination(
        self,
        destination: Optional[dict]
    ) -> tuple[str, int]:

        if destination is None:

            return (
                self.host,
                self.port
            )

        if not isinstance(
            destination,
            dict
        ):

            raise TypeError(
                "UDP destination must be a dictionary."
            )

        host = destination.get(
            "host"
        )

        port = destination.get(
            "port"
        )

        if not host:

            raise ValueError(
                "UDP destination is missing host."
            )

        if port is None:

            raise ValueError(
                "UDP destination is missing port."
            )

        normalized_port = int(
            port
        )

        if not 1 <= normalized_port <= 65535:

            raise ValueError(
                f"Invalid UDP destination port: {port}"
            )

        return (
            str(host),
            normalized_port
        )

    # ========================================================
    # SET DESTINATION
    # ========================================================

    def set_destination(
        self,
        host: str,
        port: int
    ):

        self.host = host
        self.port = port

    # ========================================================
    # GET DESTINATION
    # ========================================================

    def get_destination(
        self
    ) -> dict:

        return {

            "host": self.host,
            "port": self.port

        }

    # ========================================================
    # CLOSE
    # ========================================================

    def close(
        self
    ):

        try:

            self.socket.close()

        except Exception:

            pass
