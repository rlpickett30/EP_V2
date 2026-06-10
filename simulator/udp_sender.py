"""
udp_sender.py

Small UDP sender for the faux node simulator.

Purpose:
- Accept one completed event package.
- Encode it as JSON.
- Send it to the server over UDP.
"""

import json
import socket


class UDPSender:
    def __init__(self, server_ip: str, server_port: int):
        self.server_ip = server_ip
        self.server_port = server_port

    def send(self, package: dict) -> bool:
        try:
            message = json.dumps(package).encode("utf-8")

            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(message, (self.server_ip, self.server_port))

            print(f"[UDP SENT] {package.get('event_type')} -> {self.server_ip}:{self.server_port}")
            return True

        except Exception as error:
            print(f"[UDP ERROR] Failed to send package: {error}")
            return False
