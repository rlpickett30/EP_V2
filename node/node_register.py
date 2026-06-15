#!/usr/bin/env python3
"""
node_register.py

EnviroPulse V2 Node Registration

Responsibilities:
- Publish NODE_REGISTER after communication reports NETWORK_CONNECTED
- Republish NODE_REGISTER on heartbeat
- Provide server/GUI with stable node identity and capabilities

This class DOES NOT:
- Send UDP directly
- Own communication transport
- Manage subsystem state
"""

from __future__ import annotations

from datetime import datetime, timezone
import socket
import time
from typing import Any, Dict, Optional


class NodeRegister:

    def __init__(
        self,
        event_bus,
        node_id: str = "node_01",
        node_name: str = "EnviroPulse Node 01",
        target: str = "server",
        register_heartbeat_sec: int = 300,
        debug: bool = True
    ):
        self.event_bus = event_bus
        self.node_id = node_id
        self.node_name = node_name
        self.target = target
        self.register_heartbeat_sec = register_heartbeat_sec
        self.debug = debug

        self.running = False
        self.last_register_publish = 0.0
        self.network_connected = False

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message: str):
        if self.debug:
            print(f"[NodeRegister] {message}")

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def start(self):
        self.running = True

        self.event_bus.subscribe(
            "NETWORK_CONNECTED",
            self.handle_network_connected
        )

        self.event_bus.subscribe(
            "NETWORK_DISCONNECTED",
            self.handle_network_disconnected
        )

        self.log("Node register ready")

        self.run()

    def stop(self):
        self.running = False

    # --------------------------------------------------
    # Event Handlers
    # --------------------------------------------------

    def handle_network_connected(self, event: Dict[str, Any]):
        self.network_connected = True
        self.publish_node_register(reason="network_connected")

    def handle_network_disconnected(self, event: Dict[str, Any]):
        self.network_connected = False

    # --------------------------------------------------
    # Payload
    # --------------------------------------------------

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _hostname(self) -> str:
        try:
            return socket.gethostname()
        except Exception:
            return None

    def _build_payload(self, reason: str) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "hostname": self._hostname(),
            "node_type": "field_node",
            "platform": "raspberry_pi",
            "software": "EnviroPulse V2",
            "reason": reason,
            "capabilities": {
                "environmental": True,
                "birdnet": True,
                "gps": True,
                "rtk": True,
                "pps": True,
                "microphone": True,
                "tdoa_recording": True,
                "wifi": True,
                "lora": False
            }
        }

    def _build_event(self, reason: str) -> Dict[str, Any]:
        return {
            "event_type": "NODE_REGISTER",
            "source": self.node_id,
            "target": self.target,
            "timestamp": self._timestamp(),
            "payload": self._build_payload(reason)
        }

    # --------------------------------------------------
    # Publisher
    # --------------------------------------------------

    def publish_node_register(self, reason: str = "heartbeat"):
        event = self._build_event(reason)

        self.event_bus.publish(event)
        self.last_register_publish = time.time()

        self.log(f"Published NODE_REGISTER: {reason}")

    def _heartbeat_due(self) -> bool:
        return (
            time.time() - self.last_register_publish
            >= self.register_heartbeat_sec
        )

    # --------------------------------------------------
    # Loop
    # --------------------------------------------------

    def run(self):
        while self.running:
            try:
                if self.network_connected and self._heartbeat_due():
                    self.publish_node_register(reason="heartbeat")

            except Exception as error:
                self.log(f"Loop error: {error}")

            time.sleep(1.0)