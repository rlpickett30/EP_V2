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

from platform_registry.platform_registry_event_manager import (
    PlatformRegistryEventManager
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
        
        self.event_manager = PlatformRegistryEventManager(
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
        
        print(
            "[REGISTRY TRACE] handle_gui_mode_change entered:",
            event_name,
            payload
        )
        
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
        Handle canonical GUI mode-change events.
            
        Canonical inbound events:
            NETWORK_MODE_CHANGE
            DETECTION_MODE_CHANGE
            FEATURE_MODE_CHANGE

        Outbound events:
            SEND_NODE_CHANGE_MODE
            COMMUNICATION_CHANGE_MODE
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
        
        payload = self._normalize_gui_mode_payload(
            event_name=event_name,
            payload=payload
        )

        print(
            "[REGISTRY TRACE] normalized GUI mode payload:",
            payload
        )
        
        command = (
            payload.get("command")
            or payload.get("requested_mode")
        )
        
        print(
            "[REGISTRY TRACE] command:",
            command
        )   

        mode_event_name = self._gui_command_to_mode_event(
            command
        )
        
        print(
            "[REGISTRY TRACE] mode_event_name:",
            mode_event_name
        )
        
        if mode_event_name is None:
            self._debug_log(
                f"GUI mode change ignored. Unknown command/requested_mode: {command}"
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
        
        print(
            "[REGISTRY TRACE] mode_manager result:",
            result
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

        if source_event_type in [
            "NETWORK_MODE_CHANGE"
        ]:

            if self._network_mode_target_is_node(payload):
                self.event_services.publish_send_node_change_mode(
                    server_payload
                )

                self._debug_log(
                    f"{source_event_type} handled. SEND_NODE_CHANGE_MODE published."
                )

                return

            self.event_services.publish_communication_change_mode(
                server_payload
            )

            self._debug_log(
                f"{source_event_type} handled. COMMUNICATION_CHANGE_MODE published."
            )

            return

        self.event_services.publish_tdoa_change_mode(
            server_payload
        )
        
        print(
            "[REGISTRY TRACE] publishing TDOA_CHANGE_MODE:",
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
        
    def handle_node_event(self, *args):
        """
        Handle node-originated occurrence events.

        Current events:
            AVIS_LITE

        Purpose:
            Normalize node event payloads, validate them through the
            Platform Registry event manager, and publish server-approved
            event packages such as SERVER_AVIS_LITE.
        """

        event_name, payload = self._parse_event_args(args)

        if not self._event_is_node_event(event_name):
            self._debug_log(
                f"Ignored unknown node event: {event_name}"
            )
            return

        if not payload:
            self._debug_log(
                f"{event_name} ignored. Missing payload."
            )
            return

        payload = self._normalize_node_event_payload(
            event_name=event_name,
            payload=payload
        )

        if not payload.get("node_id"):
            self._debug_log(
                f"{event_name} ignored. Missing node_id or source."
            )
            return

        registry_event_name = str(
            event_name
        ).strip().lower()

        result = self.event_manager.handle_platform_event(
            event_name=registry_event_name,
            payload=payload
        )

        if not result.get("success"):
            self._debug_log(
                f"{event_name} rejected by event manager: {result.get('reason')}"
            )
            return

        if not result.get("publish"):
            self._debug_log(
                f"{event_name} accepted but not published: {result.get('reason')}"
            )
            return

        self.event_services.publish_server_platform_event(
            result
        )

        self._debug_log(
            f"{event_name} handled. {result.get('server_event_key')} published."
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
                    "event_id",
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
        Return True when event is FEATURE_MODE_CHANGE.
        """

        if event_name is None:
            return False

        return str(event_name).strip().upper() in [
            "FEATURE_MODE_CHANGE",
            "DETECTION_MODE_CHANGE",
            "NETWORK_MODE_CHANGE"
        ]
    
    def _gui_command_to_mode_event(self, command):
        """
        Validate canonical GUI mode payload values and return the
        internal PlatformRegistryModeManager mode name.

        Clean contract:
            event_type tells the command category.
            command/requested_mode carries the lowercase mode value.
        """

        if command is None:
            return None

        mode_name = str(
            command
        ).strip().lower()

        valid_modes = {
            "energy_onset",
            "pattern_onset",
            "energy_offset",
            "pattern_offset",
            "onset_feature",
            "amp_feature",
            "enable_wifi",
            "disable_wifi",
            "enable_lora",
            "disable_lora"
        }

        if mode_name not in valid_modes:
            return None

        return mode_name
   
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
    
    def _event_is_node_event(self, event_name):
        """
        Return True when event is a node-originated occurrence event.
        """

        if event_name is None:
            return False

        return str(event_name).strip().upper() in [
            "AVIS_LITE",
            "ENVIRO_EVENT",
            "GPS_COORD"
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
            "timestamp_utc": gui_payload.get("timestamp_utc") or gui_payload.get("timestamp"),
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
    
    def _normalize_node_event_payload(self, event_name, payload):
        """
        Normalize node occurrence event payloads so the event manager
        receives stable field names.
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

        if str(event_name).strip().upper() == "AVIS_LITE":

            normalized.setdefault(
                "common_name",
                normalized.get("species_common")
            )

            normalized.setdefault(
                "scientific_name",
                normalized.get("species_scientific")
            )

            normalized.setdefault(
                "species",
                normalized.get("common_name")
            )

            normalized.setdefault(
                "detection_time",
                normalized.get("detection_time_utc")
            )

            normalized.setdefault(
                "audio_path",
                normalized.get("recording_path")
            )
        
        if str(event_name).strip().upper() == "ENVIRO_EVENT":

            normalized.setdefault(
                "temperature_c",
                normalized.get("temp_c")
            )

            normalized.setdefault(
                "humidity_percent",
                normalized.get("humidity")
            )

            normalized.setdefault(
                "pressure_hpa",
                normalized.get("pressure")
            )
        
        return normalized

        if str(event_name).strip().upper() == "GPS_COORD":

            normalized.setdefault(
                "lat",
                normalized.get("latitude")
            )

            normalized.setdefault(
                "lon",
                normalized.get("longitude")
            )

            normalized.setdefault(
                "alt",
                normalized.get("altitude")
            )    
    def _normalize_gui_mode_payload(
        self,
        event_name,
        payload
    ):
        """
        Normalize GUI mode-change payloads so handle_gui_mode_change()
        receives the actual command fields.
        
        Expected clean command fields:
            mode_category
            command
            requested_mode
            target
            target_node

        This handles the case where Communication republishes the full
        GUI event envelope as the server-bus payload.
        """

        if not isinstance(payload, dict):
            return {}

        normalized = dict(payload)

        while (
           isinstance(normalized.get("payload"), dict)
           and not normalized.get("command")
           and not normalized.get("requested_mode")
        ):

            outer = dict(normalized)
            inner = dict(
                outer.get("payload", {})
            )

            inner.setdefault(
                "event_type",
                outer.get("event_type", event_name)
            )

            for metadata_key in [
                "event_id",
                "source",
                "source_name",
                "target",
                "simulated",
                "timestamp",
                "timestamp_utc"
            ]:

                if metadata_key in outer and metadata_key not in inner:
                    inner[metadata_key] = outer.get(metadata_key)

            normalized = inner

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