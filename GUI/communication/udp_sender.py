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
#   - Send UDP packets
#   - Report send success or failure
#   - Allow destination updates
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
import socket
import logging


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
        message: dict
    ) -> bool:

        try:

            payload = json.dumps(
                message
            ).encode(
                "utf-8"
            )

            self.socket.sendto(
                payload,
                (
                    self.host,
                    self.port
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