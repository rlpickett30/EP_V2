# ============================================================
# node_route_manager.py
#
# EnviroPulse V2
#
# Subsystem:
#   Communication
#
# Role:
#   Manager
#
# Purpose:
#   Own the server runtime routing table that maps node identities to their
#   current UDP listener destinations.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["udp"]["send_port"] supplies the shared node listener port
#
# Does:
#   - Validate node identities learned from NODE_REGISTER
#   - Validate IPv4 source addresses observed by the UDP listener
#   - Bind node_id to source_ip and the shared node listener port
#   - Replace a route when a node registers from a new address
#   - Resolve individual node destinations
#   - Return safe copies of runtime route state
#   - Protect route reads and writes across listener and event-bus threads
#
# Does NOT:
#   - Persist routes across server restarts
#   - Read node IP addresses from configuration
#   - Learn routes from arbitrary non-registration events
#   - Send packets
#   - Select TDOA targets
#   - Publish events
#   - Own TDOA workflow
#
# Owner:
#   communication_dispatcher.py
#
# ============================================================

from __future__ import annotations

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import ipaddress
import threading

from copy import deepcopy
from datetime import datetime
from datetime import timezone
from typing import Dict
from typing import Optional


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class NodeRouteManager:

    def __init__(
        self,
        node_listener_port: int
    ):

        self.node_listener_port = self._validate_port(
            node_listener_port
        )

        self.routes: Dict[str, dict] = {}
        self.lock = threading.RLock()

    # ========================================================
    # LEARN ROUTE
    # ========================================================

    def learn_route(
        self,
        node_id: str,
        source_ip: str
    ) -> dict:
        """
        Store or replace one node route learned from NODE_REGISTER.
        """

        normalized_node_id = self._normalize_node_id(
            node_id
        )

        normalized_ip = self._normalize_ipv4(
            source_ip
        )

        learned_at_utc = self._utc_now()

        with self.lock:

            previous_route = self.routes.get(
                normalized_node_id
            )

            route = {
                "node_id": normalized_node_id,
                "host": normalized_ip,
                "port": self.node_listener_port,
                "learned_at_utc": learned_at_utc
            }

            self.routes[normalized_node_id] = route

            route_changed = (
                previous_route is None
                or previous_route.get("host") != normalized_ip
                or previous_route.get("port") != self.node_listener_port
            )

            return {
                "route": deepcopy(route),
                "previous_route": deepcopy(previous_route),
                "route_changed": route_changed
            }

    # ========================================================
    # RESOLVE ROUTE
    # ========================================================

    def resolve_route(
        self,
        node_id: str
    ) -> Optional[dict]:

        try:

            normalized_node_id = self._normalize_node_id(
                node_id
            )

        except (TypeError, ValueError):

            return None

        with self.lock:

            route = self.routes.get(
                normalized_node_id
            )

            return deepcopy(
                route
            )

    # ========================================================
    # SNAPSHOT
    # ========================================================

    def get_routes(
        self
    ) -> dict:

        with self.lock:

            return deepcopy(
                self.routes
            )

    # ========================================================
    # VALIDATION
    # ========================================================

    def _normalize_node_id(
        self,
        node_id
    ) -> str:

        if node_id is None:

            raise ValueError(
                "node_id is required"
            )

        normalized_node_id = str(
            node_id
        ).strip()

        if not normalized_node_id:

            raise ValueError(
                "node_id must not be empty"
            )

        return normalized_node_id

    def _normalize_ipv4(
        self,
        source_ip
    ) -> str:

        if source_ip is None:

            raise ValueError(
                "source_ip is required"
            )

        address = ipaddress.ip_address(
            str(source_ip).strip()
        )

        if address.version != 4:

            raise ValueError(
                f"Only IPv4 node routes are supported: {source_ip}"
            )

        return str(
            address
        )

    def _validate_port(
        self,
        port
    ) -> int:

        normalized_port = int(
            port
        )

        if not 1 <= normalized_port <= 65535:

            raise ValueError(
                f"Invalid UDP port: {port}"
            )

        return normalized_port

    # ========================================================
    # TIME
    # ========================================================

    def _utc_now(
        self
    ) -> str:

        return (
            datetime.now(
                timezone.utc
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z"
            )
        )
