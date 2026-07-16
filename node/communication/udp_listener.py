# ============================================================
# udp_listener.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Node Communication
#
# Role:
#   Helper Script
#
# Purpose:
#   Listen for raw UDP packets and forward packet dictionaries to
#   ListenerManager.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["udp"]
#
# Does:
#   - Open a UDP socket
#   - Bind to the configured host and port
#   - Receive raw UDP packets
#   - Attach receive timestamp metadata
#   - Attach source IP metadata
#   - Attach source port metadata
#   - Forward raw packet dictionaries to ListenerManager
#   - Stop and close the UDP listener socket
#
# Does NOT:
#   - Decode JSON messages
#   - Route events
#   - Publish events
#   - Send messages
#   - Store messages
#   - Store Communication state
#   - Make Communication workflow decisions
#
# Owner:
#   listener_manager.py
#
# ============================================================

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import socket
import logging

from datetime import datetime


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class UDPListener:

    def __init__(
        self,
        host: str,
        port: int,
        listener_manager
    ):

        self.host = host
        self.port = port
        self.listener_manager = listener_manager

        self.running = False
        self.socket = None

    # ========================================================
    # START
    # ========================================================

    def start(
        self
    ):

        self.socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        self.socket.bind(
            (
                self.host,
                self.port
            )
        )

        self.running = True

        logging.info(
            f"[Communication] UDP Listener started on "
            f"{self.host}:{self.port}"
        )

        while self.running:

            try:

                data, address = self.socket.recvfrom(
                    65535
                )

                packet = {

                    "timestamp": datetime.utcnow().isoformat(),

                    "source_ip": address[
                        0
                    ],

                    "source_port": address[
                        1
                    ],

                    "payload": data

                }

                self.listener_manager.handle_packet(
                    packet
                )

            except OSError:

                if self.running:

                    logging.exception(
                        "[Communication] UDP listener socket error."
                    )

            except Exception as error:

                logging.exception(
                    f"[Communication] UDP listener error: "
                    f"{error}"
                )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):

        self.running = False

        if self.socket:

            self.socket.close()

        logging.info(
            "[Communication] UDP Listener stopped"
        )
