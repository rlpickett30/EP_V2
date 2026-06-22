#!/usr/bin/env python3
# ============================================================
# node_register.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Node Runtime
#
# Role:
#   Helper Script
#
# Purpose:
#   Publish NODE_REGISTER after communication reports network
#   connectivity and republish NODE_REGISTER on heartbeat.
#
# Expected config source:
#   node_config.json
#
# Expected config section:
#   config["node_id"], config["node_name"], config["register"],
#   config["subsystems"]
#
# Does:
#   - Publish NODE_REGISTER after NETWORK_CONNECTED.
#   - Publish NODE_REGISTER heartbeat while network is connected.
#   - Provide server and GUI with stable node identity.
#   - Provide server and GUI with node capabilities.
#
# Does NOT:
#   - Send UDP directly.
#   - Own communication transport.
#   - Manage subsystem state.
#   - Own runtime startup.
#   - Guess a real node identity from hard-coded defaults.
#
# Owner:
#   node_main.py
#
# ============================================================

from __future__ import annotations

import json
import socket
import time

from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Dict
from typing import Optional


class NodeRegister:

    def __init__(
        self,
        event_bus,
        node_id: Optional[str] = None,
        node_name: Optional[str] = None,
        node_config: Optional[Dict[str, Any]] = None,
        node_config_path: str = "node_config.json",
        target: str = "server",
        register_heartbeat_sec: Optional[int] = None,
        debug: bool = True,
    ):

        self.event_bus = event_bus
        self.node_config_path = Path(
            node_config_path
        )

        self.node_config = (
            node_config
            if isinstance(
                node_config,
                dict,
            )
            else self.load_node_config()
        )

        self.node_id = self.resolve_node_id(
            configured_node_id=node_id,
        )

        self.node_name = self.resolve_node_name(
            configured_node_name=node_name,
        )

        self.target = target

        self.register_heartbeat_sec = self.resolve_register_heartbeat(
            configured_heartbeat=register_heartbeat_sec,
        )

        self.debug = debug

        self.running = False
        self.last_register_publish = 0.0
        self.network_connected = False

    # ============================================================
    # CONFIG
    # ============================================================

    def load_node_config(
        self,
    ) -> Dict[str, Any]:

        try:
            if not self.node_config_path.exists():
                return {}

            with self.node_config_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(
                    file
                )

            if isinstance(
                data,
                dict,
            ):
                return data

        except Exception:
            return {}

        return {}

    def resolve_node_id(
        self,
        configured_node_id: Optional[str],
    ) -> str:

        value = (
            configured_node_id
            or self.node_config.get(
                "node_id"
            )
            or self.hostname_node_id()
        )

        return str(
            value
        ).strip()

    def resolve_node_name(
        self,
        configured_node_name: Optional[str],
    ) -> str:

        value = (
            configured_node_name
            or self.node_config.get(
                "node_name"
            )
            or self.infer_node_name(
                self.node_id
            )
        )

        return str(
            value
        ).strip()

    def resolve_register_heartbeat(
        self,
        configured_heartbeat: Optional[int],
    ) -> int:

        if configured_heartbeat is not None:
            return int(
                configured_heartbeat
            )

        register_config = self.node_config.get(
            "register",
            {},
        )

        return int(
            register_config.get(
                "heartbeat_sec",
                300,
            )
        )

    def hostname_node_id(
        self,
    ) -> str:

        try:
            return socket.gethostname().replace(
                "-",
                "_",
            )

        except Exception:
            return "node_unknown"

    def infer_node_name(
        self,
        node_id: str,
    ) -> str:

        return node_id.replace(
            "_",
            " ",
        ).title()

    # ============================================================
    # DEBUG
    # ============================================================

    def log(
        self,
        message: str,
    ) -> None:

        if self.debug:
            print(
                f"[NodeRegister] {message}"
            )

    # ============================================================
    # LIFECYCLE
    # ============================================================

    def start(
        self,
    ) -> None:

        self.running = True

        self.event_bus.subscribe(
            "NETWORK_CONNECTED",
            self.handle_network_connected,
        )

        self.event_bus.subscribe(
            "NETWORK_DISCONNECTED",
            self.handle_network_disconnected,
        )

        self.log(
            f"Node register ready as {self.node_id}"
        )

        self.run()

    def stop(
        self,
    ) -> None:

        self.running = False

    # ============================================================
    # EVENT HANDLERS
    # ============================================================

    def handle_network_connected(
        self,
        event: Dict[str, Any],
    ) -> None:

        self.network_connected = True
        self.publish_node_register(
            reason="network_connected"
        )

    def handle_network_disconnected(
        self,
        event: Dict[str, Any],
    ) -> None:

        self.network_connected = False

    # ============================================================
    # PAYLOAD
    # ============================================================

    def timestamp(
        self,
    ) -> str:

        return datetime.now(
            timezone.utc
        ).isoformat()

    def hostname(
        self,
    ) -> Optional[str]:

        try:
            return socket.gethostname()

        except Exception:
            return None

    def build_capabilities(
        self,
    ) -> Dict[str, bool]:

        subsystems = self.node_config.get(
            "subsystems",
            {},
        )

        return {
            "environmental": bool(
                subsystems.get(
                    "environmental",
                    True,
                )
            ),
            "birdnet": bool(
                subsystems.get(
                    "birdnet",
                    True,
                )
            ),
            "gps": bool(
                subsystems.get(
                    "rtk",
                    True,
                )
            ),
            "rtk": bool(
                subsystems.get(
                    "rtk",
                    True,
                )
            ),
            "pps": bool(
                subsystems.get(
                    "rtk",
                    True,
                )
            ),
            "microphone": bool(
                subsystems.get(
                    "microphone",
                    True,
                )
            ),
            "tdoa_recording": bool(
                subsystems.get(
                    "microphone",
                    True,
                )
            ),
            "wifi": bool(
                subsystems.get(
                    "communication",
                    True,
                )
            ),
            "lora": False,
        }

    def build_payload(
        self,
        reason: str,
    ) -> Dict[str, Any]:

        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "hostname": self.hostname(),
            "node_type": "field_node",
            "platform": "raspberry_pi",
            "software": "EnviroPulse V2",
            "reason": reason,
            "capabilities": self.build_capabilities(),
        }

    def build_event(
        self,
        reason: str,
    ) -> Dict[str, Any]:

        return {
            "event_type": "NODE_REGISTER",
            "source": self.node_id,
            "target": self.target,
            "timestamp": self.timestamp(),
            "payload": self.build_payload(
                reason=reason,
            ),
        }

    # ============================================================
    # PUBLISHER
    # ============================================================

    def publish_node_register(
        self,
        reason: str = "heartbeat",
    ) -> None:

        event = self.build_event(
            reason=reason
        )

        self.event_bus.publish(
            event
        )

        self.last_register_publish = time.time()

        self.log(
            f"Published NODE_REGISTER: {reason}"
        )

    def heartbeat_due(
        self,
    ) -> bool:

        return (
            time.time() - self.last_register_publish
            >= self.register_heartbeat_sec
        )

    # ============================================================
    # LOOP
    # ============================================================

    def run(
        self,
    ) -> None:

        while self.running:
            try:
                if (
                    self.network_connected
                    and self.heartbeat_due()
                ):
                    self.publish_node_register(
                        reason="heartbeat"
                    )

            except Exception as error:
                self.log(
                    f"Loop error: {error}"
                )

            time.sleep(
                1.0
            )