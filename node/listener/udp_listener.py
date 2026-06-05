# ============================================================
# udp_listener.py
#
# EnviroPulse V2
#
# UDP packet receiver
#
# Responsibilities:
#   - Open UDP socket
#   - Listen for incoming packets
#   - Forward packets to listener_manager
#
# Does NOT:
#   - Decode messages
#   - Route messages
#   - Publish events
#   - Make decisions
#
# ============================================================

import socket
import logging
from datetime import datetime


class UDPListener:
    """
    Raw UDP packet listener.
    """

    def __init__(self, host, port, listener_manager):

        self.host = host
        self.port = port
        self.listener_manager = listener_manager

        self.running = False
        self.socket = None

    # ========================================================
    # Start Listener
    # ========================================================

    def start(self):

        self.socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        self.socket.bind((self.host, self.port))

        self.running = True

        logging.info(
            f"UDP Listener started on "
            f"{self.host}:{self.port}"
        )

        while self.running:

            try:

                data, address = self.socket.recvfrom(65535)

                packet = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "source_ip": address[0],
                    "source_port": address[1],
                    "payload": data
                }

                self.listener_manager.handle_packet(packet)

            except Exception as error:

                logging.exception(
                    f"UDP listener error: {error}"
                )

    # ========================================================
    # Stop Listener
    # ========================================================

    def stop(self):

        self.running = False

        if self.socket:

            self.socket.close()

        logging.info("UDP Listener stopped")
