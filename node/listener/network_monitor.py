"""
network_monitor.py

Purpose:
    Provide network status information
    to sender_dispatcher.

Responsibilities:
    - Verify network connectivity
    - Verify server reachability

Not Responsible For:
    - Routing decisions
    - Sending messages
    - Event publishing
"""
import socket


class NetworkMonitor:

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 2.0
    ):

        self.host = host
        self.port = port
        self.timeout = timeout

    # ==========================================
    # SERVER REACHABILITY
    # ==========================================

    def server_reachable(self) -> bool:

        try:

            test_socket = socket.socket(
                socket.AF_INET,
                socket.SOCK_DGRAM
            )

            test_socket.settimeout(
                self.timeout
            )

            test_socket.connect(
                (
                    self.host,
                    self.port
                )
            )

            test_socket.close()

            return True

        except Exception:

            return False

    # ==========================================
    # ONLINE STATUS
    # ==========================================

    def is_online(self) -> bool:

        return self.server_reachable()

    # ==========================================
    # STATUS REPORT
    # ==========================================

    def get_status(self) -> dict:

        online = self.is_online()

        return {

            "online": online,

            "host": self.host,

            "port": self.port
        }