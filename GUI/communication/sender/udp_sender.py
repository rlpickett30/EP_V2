# ============================================================
# udp_sender.py
#
# EnviroPulse V2
#
# UDP Message Sender
#
# Responsibilities:
#   - Serialize message
#   - Send UDP packet
#   - Report success/failure
#
# Does NOT:
#   - Retry messages
#   - Queue messages
#   - Store messages
#   - Make decisions
#   - Publish events
#   - Manage state
#
# ============================================================

import json
import socket
import logging


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
                f"UDP Send Error: {error}"
            )

            return False

    # ========================================================
    # DESTINATION
    # ========================================================

    def set_destination(
        self,
        host: str,
        port: int
    ):

        self.host = host
        self.port = port

    def get_destination(
        self
    ) -> dict:

        return {

            "host": self.host,
            "port": self.port
        }

    # ========================================================
    # SHUTDOWN
    # ========================================================

    def close(self):

        try:

            self.socket.close()

        except Exception:

            pass