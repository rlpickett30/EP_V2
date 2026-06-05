"""
UDP_sender.py

Purpose:
    Sends prepared EnviroPulse messages to a remote host
    over UDP.

Responsibilities:
    - Serialize message
    - Send packet
    - Report success/failure

Not Responsible For:
    - Retries
    - Queue management
    - Database storage
    - Delivery decisions
    - Configuration selection
"""
import json
import socket
from typing import Dict


class UDPSender:

    def __init__(self, host: str, port: int):

        self.host = host
        self.port = port

        self.socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

    def send(self, message: Dict) -> bool:

        try:

            payload = json.dumps(message).encode("utf-8")

            self.socket.sendto(
                payload,
                (self.host, self.port)
            )

            return True

        except Exception as error:

            print(
                f"[UDP Sender] Send failed: {error}"
            )

            return False