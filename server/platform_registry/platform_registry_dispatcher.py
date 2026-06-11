# ============================================================
# platform_registry_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Platform Registry
#
# Role:
#   Dispatcher
#
# Current Purpose:
#   Own the minimal Platform Registry workflow.
#
# Currently Known Events:
#   Subscribes:
#       GUI_REGISTER
#
#   Publishes:
#       REGISTRY_UPDATED
#
# Philosophy:
#   This dispatcher only handles events that are currently implemented.
#   Future events should be added only when they become real.
#
# ============================================================


# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from platform_registry.platform_registry_event_services import (
    PlatformRegistryEventServices
)

from platform_registry.platform_registry_registry_manager import (
    PlatformRegistryRegistryManager
)

from platform_registry.platform_registry_mode_manager import (
    PlatformRegistryModeManager
)

from platform_registry.platform_registry_state_manager import (
    PlatformRegistryStateManager
)
from platform_registry.platform_registry_TDOA_manager import (
    PlatformRegistryTDOAManager
)

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json
import logging
from pathlib import Path


# ============================================================
# PLATFORM REGISTRY DISPATCHER
# ============================================================

class PlatformRegistryDispatcher:
    """
    Owns the Platform Registry subsystem workflow.

    Current responsibility:
        - Start Platform Registry event subscriptions.
        - Handle GUI_REGISTER.
        - Register or update the GUI in the registry manager.
        - Publish REGISTRY_UPDATED through event services.

    This dispatcher intentionally does not handle future server events yet.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        config_path="platform_registry_config.json",
        config=None
    ):
        self.event_bus = event_bus
        self.config_path = config_path

        self.config = config or self._load_config(config_path)

        platform_config = self.config.get(
            "platform_registry",
            {}
        )

        self.debug = platform_config.get(
            "debug",
            False
        )

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

        self.event_services = PlatformRegistryEventServices(
            event_bus=self.event_bus,
            config=self.config
        )

        self.registry_manager = PlatformRegistryRegistryManager(
            config=self.config
        )

        self.mode_manager = PlatformRegistryModeManager(
            config=self.config
        )

        self.state_manager = PlatformRegistryStateManager(
            config=self.config
        )
        
        self.tdoa_manager = PlatformRegistryTDOAManager(
            config=self.config
        )
        
        self.started = False

    # ========================================================
    # PUBLIC API
    # ========================================================

    def start(self):
        """
        Start Platform Registry event subscriptions.
        """

        if self.started:
            self._debug_log(
                "Platform Registry Dispatcher already started."
            )
            return

        self.event_services.register_subscriptions(self)

        self.started = True

        self._debug_log(
            "Platform Registry Dispatcher started."
        )

    def stop(self):
        """
        Mark Platform Registry dispatcher stopped.
        """

        self.started = False

        self._debug_log(
            "Platform Registry Dispatcher stopped."
        )

    def get_platform_snapshot(self):
        """
        Return the current registry and node snapshot.
        """

        return {
            "registry": self.registry_manager.get_registry_snapshot(),
            "state": self.state_manager.get_platform_state_snapshot(),
            "tdoa": self.tdoa_manager.get_tdoa_snapshot()
        }

    # ========================================================
    # EVENT HANDLERS
    # ========================================================

    def handle_gui_register(self, *args):
        """
        Handle GUI_REGISTER.

        Expected event envelope:
            {
                "event_type": "GUI_REGISTER",
                "source": "gui",
                "payload": {
                    "gui_id": "...",
                    ...
                }
            }

        Also supports direct payload delivery:
            {
                "gui_id": "...",
                ...
            }
        """

        event_name, payload = self._parse_event_args(args)

        if not self._event_is_gui_register(event_name):
            self._debug_log(
                f"Ignored unknown registry event: {event_name}"
            )
            return

        if not payload:
            self._debug_log(
                "GUI_REGISTER ignored. Missing payload."
            )
            return

        result = self.registry_manager.register_gui(payload)

        self.event_services.publish_registry_updated(
            result
        )

        self._debug_log(
            "GUI_REGISTER handled. REGISTRY_UPDATED published."
        )
        
    def handle_gui_mode_change(self, *args):
        """
        Handle known GUI mode-change events.
        
        Current known inbound event:
            GUI_FEATURE_MODE_CHANGE

        Current outbound event:
            TDOA_CHANGE_MODE
        """

        event_name, payload = self._parse_event_args(args)

        if not self._event_is_gui_mode_change(event_name):
            self._debug_log(
                f"Ignored unknown GUI mode event: {event_name}"
            )
            return

        if not payload:
            self._debug_log(
                "GUI mode change ignored. Missing payload."
            )
            return

        mode_event_name = self._gui_command_to_mode_event(
            payload.get("command")
        )

        if mode_event_name is None:
            self._debug_log(
                f"GUI mode change ignored. Unknown command: {payload.get('command')}"
            )
            return

        mode_payload = self._build_mode_payload_from_gui_payload(
            gui_event_name=event_name,
            mode_event_name=mode_event_name,
            gui_payload=payload
        )

        result = self.mode_manager.handle_mode_event(
            event_name=mode_event_name,
            payload=mode_payload
        )

        if not result.get("success"):
            self._debug_log(
                f"Mode manager rejected mode change: {result.get('reason')}"
            )
            return

        if not result.get("publish"):
            self._debug_log(
                "Mode manager accepted mode change but did not publish because mode was unchanged."
            )
            return

        server_payload = result.get("server_payload")

        if server_payload is None:
            self._debug_log(
                "Mode manager returned no server payload."
            )
            return

        server_payload["source_event_type"] = event_name
        server_payload["source_command"] = payload.get("command")
        server_payload["source_requested_mode"] = payload.get("requested_mode")
        server_payload["source_mode_category"] = payload.get("mode_category")

        source_event_type = str(event_name).strip().upper()

        if source_event_type == "GUI_NETWORK_MODE_CHANGE":

            if self._network_mode_target_is_node(payload):
                self.event_services.publish_send_node_change_mode(
                    server_payload
                )

                self._debug_log(
                    "GUI_NETWORK_MODE_CHANGE handled. SEND_NODE_CHANGE_MODE published."
                )

                return

            self.event_services.publish_communication_change_mode(
                server_payload
            )

            self._debug_log(
                "GUI_NETWORK_MODE_CHANGE handled. COMMUNICATION_CHANGE_MODE published."
            )

            return

        self.event_services.publish_tdoa_change_mode(
            server_payload
        )

        self._debug_log(
            f"{source_event_type} handled. TDOA_CHANGE_MODE published."
        )
     
    def handle_node_register(self, *args):
        """
        Handle NODE_REGISTER.

        Expected event envelope:
            {
                "event_type": "NODE_REGISTER",
                "source": "faux_node_01",
                "source_name": "Faux Node 01",
                "payload": {
                    ...
                }
            }
        """

        event_name, payload = self._parse_event_args(args)

        if not self._event_is_node_register(event_name):
            self._debug_log(
                f"Ignored unknown registry event: {event_name}"
            )
            return

        if not payload:
            self._debug_log(
                "NODE_REGISTER ignored. Missing payload."
            )
            return

        payload.setdefault(
            "node_id",
            payload.get("source")
        )

        payload.setdefault(
            "device_id",
            payload.get("node_id")
        )

        payload.setdefault(
            "device_role",
            "NODE"
        )

        payload.setdefault(
            "node_name",
            payload.get("source_name", payload.get("node_id"))
        )

        result = self.registry_manager.register_node(payload)

        self.event_services.publish_registry_updated(
            result,
            reason="NODE_REGISTER"
        )   

        if result.get("success"):

            self.event_services.publish_server_node_register(
                result
            )

        self._debug_log(
            "NODE_REGISTER handled. REGISTRY_UPDATED and SERVER_NODE_REGISTER published."
        )
        
    def handle_node_state(self, *args):
        """
        Handle RTK_STATE, GPS_STATE, PPS_STATE, and ENVIRO_STATE.

        These are node-originated state reports. The dispatcher normalizes
        identity, passes the state update to the state manager, and publishes
        one combined NODE_STATE_UPDATED event when accepted.
        """

        event_name, payload = self._parse_event_args(args)
        
        if not self._event_is_node_state(event_name):
            self._debug_log(
                f"Ignored unknown node state event: {event_name}"
            )
            return

        if not payload:
            self._debug_log(
                f"{event_name} ignored. Missing payload."
            )
            return

        payload = self._normalize_node_state_payload(
            event_name=event_name,
            payload=payload
        )

        if not payload.get("node_id"):
            self._debug_log(
                f"{event_name} ignored. Missing node_id or source."
            )
            return

        result = self.state_manager.handle_state_event(
            event_name=event_name,
            payload=payload
        )

        if not result.get("success"):
            self._debug_log(
                f"{event_name} rejected by state manager: {result.get('reason')}"
            )
            return

        if not result.get("publish"):
            self._debug_log(
                f"{event_name} accepted but not published: {result.get('reason')}"
            )
            return

        self.event_services.publish_node_state_updated(
            result
        )

        self._debug_log(
            f"{event_name} handled. NODE_STATE_UPDATED published."
        )

        tdoa_result = self.tdoa_manager.handle_node_state_snapshot(
            node_id=result.get(
                "node_id"
            ),
            node_state_snapshot=result.get(
                "state_snapshot",
                {}
            ),
            source_event=event_name
        )

        if not tdoa_result.get(
            "success"
        ):
            self._debug_log(
                f"{event_name} TDOA readiness check failed: {tdoa_result.get('reason')}"
            )

            return

        if not tdoa_result.get(
            "publish"
        ):
            self._debug_log(
                f"{event_name} TDOA readiness accepted but not published: {tdoa_result.get('reason')}"
            )

            return

        self.event_services.publish_node_tdoa_state(
            tdoa_result
        )

        self._debug_log(
            f"{event_name} handled. NODE_TDOA_STATE published."
        )
        
    # ========================================================
    # EVENT ARGUMENT HANDLING
    # ========================================================

    def _parse_event_args(self, args):
        """
        Support both common Event Bus callback styles:

            handler(payload)

        and:

            handler(event_name, payload)

        Returns:
            event_name
            payload
        """

        if len(args) == 2:
            event_name = args[0]
            raw_payload = args[1] or {}

            return self._extract_event_name_and_payload(
                fallback_event_name=event_name,
                raw_payload=raw_payload
            )

        if len(args) == 1:
            raw_payload = args[0] or {}

            return self._extract_event_name_and_payload(
                fallback_event_name=None,
                raw_payload=raw_payload
            )

        return None, {}

    def _extract_event_name_and_payload(
        self,
        fallback_event_name,
        raw_payload
    ):
        """
        Extract the event name and payload from either:

            - a direct payload
            - an event envelope with a payload field
        """

        if not isinstance(raw_payload, dict):
            return fallback_event_name, {}

        event_name = (
            raw_payload.get("event_type")
            or raw_payload.get("event_name")
            or fallback_event_name
        )

        inner_payload = raw_payload.get("payload")

        if isinstance(inner_payload, dict):
            payload = dict(inner_payload)

            payload.setdefault(
                "event_type",
                event_name
            )

            for metadata_key in [
                    "source",
                    "source_name",
                    "target",
                    "simulated",
                    "timestamp",
                    "timestamp_utc"
                ]:
                
                if metadata_key in raw_payload and metadata_key not in payload:
                    payload[metadata_key] = raw_payload.get(metadata_key)

            return event_name, payload

        payload = dict(raw_payload)

        if event_name is not None:
            payload.setdefault(
                "event_type",
                event_name
            )

        return event_name, payload

    # ========================================================
    # EVENT TYPE CHECKS
    # ========================================================

    def _event_is_gui_register(self, event_name):
        """
        Return True when event is GUI_REGISTER.
        """

        if event_name is None:
            return False

        return str(event_name).strip().upper() == "GUI_REGISTER"
    
    def _event_is_gui_mode_change(self, event_name):
        """
        Return True when event is GUI_FEATURE_MODE_CHANGE.
        """

        if event_name is None:
            return False

        return str(event_name).strip().upper() in [
            "GUI_FEATURE_MODE_CHANGE",
            "GUI_DETECTION_MODE_CHANGE",
            "GUI_NETWORK_MODE_CHANGE"
        ]

    def _gui_command_to_mode_event(self, command):
        """
        Convert GUI command labels into mode manager event names.
        """

        if command is None:
            return None
        
        command_map = {
            "ONSET_FEATURE": "onset_feature",
            "AMP_FEATURE": "amp_feature",
            "ENERGY_ONSET": "energy_onset",
            "PATTERN_ONSET": "pattern_onset",
            "ENERGY_OFFSET": "energy_offset",
            "PATTERN_OFFSET": "pattern_offset",
            "ENABLE_WIFI": "enable_wifi",
            "DISABLE_WIFI": "disable_wifi",
            "ENABLE_LORA": "enable_lora",
            "DISABLE_LORA": "disable_lora"
        }

        return command_map.get(
            str(command).strip().upper()
        )
    def _event_is_node_register(self, event_name):
        """
        Return True when event is NODE_REGISTER.
        """

        if event_name is None:
            return False

        return str(event_name).strip().upper() == "NODE_REGISTER"
    
    def _event_is_node_state(self, event_name):
        """
        Return True when event is one of the four node state events.
        """

        if event_name is None:
            return False

        return str(event_name).strip().upper() in [
            "RTK_STATE",
            "GPS_STATE",
            "PPS_STATE",
            "ENVIRO_STATE"
        ]

    def _build_mode_payload_from_gui_payload(
        self,
            gui_event_name,
            mode_event_name,
            gui_payload
        ):
        """
        Convert GUI mode payload into the payload expected by
        PlatformRegistryModeManager.
        """

        target_node = gui_payload.get("target_node")

        if target_node:
            node_id = target_node
        else:
            node_id = "tdoa"

        return {
            "node_id": node_id,
            "destination": gui_payload.get("target", "server"),
            "requested_by": gui_payload.get("gui_id", "gui"),
            "timestamp_utc": gui_payload.get("timestamp_utc"),
            "mode_category": gui_payload.get("mode_category"),
            "command": gui_payload.get("command"),
            "requested_mode": gui_payload.get("requested_mode"),
            "target": gui_payload.get("target"),
            "target_node": target_node,
            "source_event_type": gui_event_name,
            "incoming_event": mode_event_name
        }
    
    def _network_mode_target_is_node(self, gui_payload):
        """
        Return True when a network mode command is intended for a node.

        Routing rule:
            - If target_node is populated, route to sender.
            - If target says node/nodes/field_node/field_nodes, route to sender.
            - Otherwise, treat it as a server communication mode change.
        """

        target_node = gui_payload.get("target_node")

        target = str(
            gui_payload.get("target", "")
        ).strip().lower()

        if target_node:
            return True

        return target in [
            "node",
            "nodes",
            "field_node",
            "field_nodes"
        ]

    def _normalize_node_state_payload(self, event_name, payload):
        """
        Normalize node state payloads so the state manager always receives
        a node_id and source_event_type.
        """

        normalized = dict(payload)

        node_id = (
            normalized.get("node_id")
            or normalized.get("device_id")
            or normalized.get("source")
            or normalized.get("node_name")
        )

        if node_id is not None:
            normalized["node_id"] = node_id
            
            normalized.setdefault(
                "source_event_type",
                event_name
            )

        normalized.setdefault(
            "event_type",
            event_name
        )

        return normalized
    
    # ========================================================
    # CONFIG
    # ========================================================

    def _load_config(self, config_path):
        """
        Load Platform Registry config.
        """

        path = Path(config_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Platform Registry config not found: {config_path}"
            )

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    # ========================================================
    # DEBUG
    # ========================================================

    def _debug_log(self, message):
        """
        Emit debug logs when enabled.
        """

        if self.debug:
            self.logger.debug(message)