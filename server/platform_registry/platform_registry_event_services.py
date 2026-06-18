# ============================================================
# platform_registry_event_services.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Platform Registry
#
# Role:
#   Event Services
#
# Current Purpose:
#   Connect the Platform Registry subsystem to the Event Bus.
#
# Currently Known Events:
#   Subscribes:
#       GUI_REGISTER
#
#   Publishes:
#       REGISTRY_UPDATED
#
# Philosophy:
#   This file only handles events that are currently implemented.
#   Future events should be added only when they become real.
#
# ============================================================


# ============================================================
# EVENT NAMES
# ============================================================

GUI_REGISTER = "GUI_REGISTER"
NODE_REGISTER = "NODE_REGISTER"
REGISTRY_UPDATED = "REGISTRY_UPDATED"
SERVER_NODE_REGISTER = "SERVER_NODE_REGISTER"

RTK_STATE = "RTK_STATE"
GPS_STATE = "GPS_STATE"
PPS_STATE = "PPS_STATE"
ENVIRO_STATE = "ENVIRO_STATE"
NODE_STATE_UPDATED = "NODE_STATE_UPDATED"
NODE_TDOA_STATE = "NODE_TDOA_STATE"

AVIS_LITE = "AVIS_LITE"
SERVER_AVIS_LITE = "SERVER_AVIS_LITE"
ENVIRO_EVENT = "ENVIRO_EVENT"
SERVER_ENVIRO_EVENT = "SERVER_ENVIRO_EVENT"
GPS_COORD = "GPS_COORD"
SERVER_GPS_COORD = "SERVER_GPS_COORD"

FEATURE_MODE_CHANGE = "FEATURE_MODE_CHANGE"
TDOA_CHANGE_MODE = "TDOA_CHANGE_MODE"
DETECTION_MODE_CHANGE = "DETECTION_MODE_CHANGE"
NETWORK_MODE_CHANGE = "NETWORK_MODE_CHANGE"
COMMUNICATION_CHANGE_MODE = "COMMUNICATION_CHANGE_MODE"
SEND_NODE_CHANGE_MODE = "SEND_NODE_CHANGE_MODE"


# ============================================================
# PLATFORM REGISTRY EVENT SERVICES
# ============================================================

class PlatformRegistryEventServices:
    """
    Owns Platform Registry event bus subscriptions and publications.

    Current responsibility:
        - Subscribe dispatcher to GUI_REGISTER.
        - Publish REGISTRY_UPDATED.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self, event_bus, config=None):
        self.event_bus = event_bus
        self.config = config or {}

        platform_config = self.config.get(
            "platform_registry",
            {}
        )

        self.debug = platform_config.get(
            "debug",
            False
        )

    # ========================================================
    # SUBSCRIPTIONS
    # ========================================================

    def register_subscriptions(self, dispatcher):
        """
        Register known Platform Registry subscriptions.
        """

        self.event_bus.subscribe(
            GUI_REGISTER,
            dispatcher.handle_gui_register
        )
        
        self.event_bus.subscribe(
            NODE_REGISTER,
            dispatcher.handle_node_register
        )
        
        self.event_bus.subscribe(
            FEATURE_MODE_CHANGE,
            dispatcher.handle_gui_mode_change
        )
        
        self.event_bus.subscribe(
            DETECTION_MODE_CHANGE,
            dispatcher.handle_gui_mode_change
        )
        
        self.event_bus.subscribe(
            NETWORK_MODE_CHANGE,
            dispatcher.handle_gui_mode_change
        )
        
        self.event_bus.subscribe(
            RTK_STATE,
            dispatcher.handle_node_state
        )

        self.event_bus.subscribe(
            GPS_STATE,
            dispatcher.handle_node_state
        )

        self.event_bus.subscribe(
            PPS_STATE,
            dispatcher.handle_node_state
        )

        self.event_bus.subscribe(
            ENVIRO_STATE,
            dispatcher.handle_node_state
        )
        
        self.event_bus.subscribe(
            AVIS_LITE,
            dispatcher.handle_node_event
        )
        
        self.event_bus.subscribe(
            ENVIRO_EVENT,
            dispatcher.handle_node_event
        )
        
        self.event_bus.subscribe(
            GPS_COORD,
            dispatcher.handle_node_event
        )

        self._debug_print(
            "Subscribed to GUI_REGISTER"
        )
        
        self._debug_print(
            "Subscribed to NODE_REGISTER"
        )
        
        self._debug_print(
            "Subscribed to FEATURE_MODE_CHANGE"
        )
    
        self._debug_print(
            "Subscribed to DETECTION_MODE_CHANGE"
        )
        
        self._debug_print(
            "Subscribed to NETWORK_MODE_CHANGE"
        )
        
        self._debug_print(
            "Subscribed to RTK_STATE"
        )

        self._debug_print(
            "Subscribed to GPS_STATE"
        )

        self._debug_print(
            "Subscribed to PPS_STATE"
        )

        self._debug_print(
            "Subscribed to ENVIRO_STATE"
        )
        
        self._debug_print(
            "Subscribed to ENVIRO_STATE"
        )
        
        self._debug_print(
            "Subscribed to ENVIRO_EVENT"
        )
        
        self._debug_print(
            "Subscribed to GPS_COORD"
        )
    # ========================================================
    # PUBLICATIONS
    # ========================================================
    
    def publish_registry_updated(self, registry_result, reason=GUI_REGISTER):
        """
        Publish REGISTRY_UPDATED after the registry manager accepts
        or updates a platform registration.
        """

        event_package = {
            "source": "platform_registry",
            "payload": {
                "reason": reason,
                "registry_result": registry_result
            }
        }

        self.event_bus.publish(
            REGISTRY_UPDATED,
            event_package
        )

        self._debug_print(
            "Published REGISTRY_UPDATED"
            )

    def publish_server_node_register(self, registry_result):
        """
        Publish SERVER_NODE_REGISTER after the registry manager accepts
        or refreshes a node registration.
        """

        record = registry_result.get(
            "record",
            {}
        ) or {}

        event_package = {
            "source": "platform_registry",
            "payload": {
                "reason": NODE_REGISTER,
                "action": registry_result.get("action"),
                "node_id": registry_result.get("identity_id"),
                "node_name": record.get("node_name"),
                "node_role": record.get("node_role"),
                "device_id": record.get("device_id"),
                "device_role": record.get("device_role"),
                "trust": record.get("trust"),
                "capabilities": record.get("capabilities", {}),
                "registered_at_utc": record.get("registered_at_utc"),
                "last_seen_utc": record.get("last_seen_utc"),
                "registration_count": record.get("registration_count"),
                "registry_record": record
            }
        }

        self.event_bus.publish(
            SERVER_NODE_REGISTER,
            event_package
        )

        self._debug_print(
            "Published SERVER_NODE_REGISTER"
        )
    
    def publish_tdoa_change_mode(self, mode_payload):
        """
        Publish TDOA_CHANGE_MODE after the registry accepts a GUI mode request.
        """

        event_package = {
            "event_type": TDOA_CHANGE_MODE,
            "source": "platform_registry",
            "payload": {
                "reason": mode_payload.get("source_event_type"),
                "mode_payload": mode_payload
            }
        }

        self.event_bus.publish(
            TDOA_CHANGE_MODE,
            event_package
        )
        
        self._debug_print(
            "Published TDOA_CHANGE_MODE"
        )
        
    def publish_communication_change_mode(self, mode_payload):
        """
        Publish COMMUNICATION_CHANGE_MODE after the registry accepts
        a GUI network mode request.
        """

        event_package = {
            "event_type": COMMUNICATION_CHANGE_MODE,
            "source": "platform_registry",
            "payload": {
                "reason": mode_payload.get("source_event_type"),
                "mode_payload": mode_payload
            }
        }

        self.event_bus.publish(
            COMMUNICATION_CHANGE_MODE,
            event_package
        )

        self._debug_print(
            "Published COMMUNICATION_CHANGE_MODE"
        )
        
    def publish_send_node_change_mode(self, mode_payload):
        """
        Publish SEND_NODE_CHANGE_MODE after the registry accepts
        a GUI network mode request intended for a field node.
        """

        event_package = {
            "event_type": SEND_NODE_CHANGE_MODE,
            "source": "platform_registry",
            "payload": {
                "reason": mode_payload.get("source_event_type"),
                "mode_payload": mode_payload
            }
        }

        self.event_bus.publish(
            SEND_NODE_CHANGE_MODE,
            event_package
        )

        self._debug_print(
            "Published SEND_NODE_CHANGE_MODE"
        )
    
    def publish_node_state_updated(self, state_result):
        """
        Publish NODE_STATE_UPDATED after Platform Registry accepts
        and stores a node state update.
        """

        server_payload = state_result.get(
            "server_payload",
            {}
        ) or {}

        event_package = {
            "event_type": NODE_STATE_UPDATED,
            "source": "platform_registry",
            "payload": server_payload
        }

        self.event_bus.publish(
            NODE_STATE_UPDATED,
            event_package
        )

        self._debug_print(
            "Published NODE_STATE_UPDATED"
        )
        
    def publish_node_tdoa_state(self, tdoa_result):
        """
        Publish NODE_TDOA_STATE after Platform Registry determines
        a node's TDOA readiness state.
        """

        event_package = {
            "event_type": NODE_TDOA_STATE,
            "source": "platform_registry",
            "payload": {
                "reason": tdoa_result.get(
                    "reason"
                ),
                "node_id": tdoa_result.get(
                    "node_id"
                ),
                "changed": tdoa_result.get(
                    "changed"
                ),
                "tdoa_state": tdoa_result.get(
                    "tdoa_state"
                ),
                "previous_tdoa_state": tdoa_result.get(
                    "previous_tdoa_state"
                )
            }
        }

        self.event_bus.publish(
            NODE_TDOA_STATE,
            event_package
        )

        self._debug_print(
            "Published NODE_TDOA_STATE"
        )
        
    # ========================================================
    # PUBLISH SERVER PLATFORM EVENT
    # ========================================================

    def publish_server_platform_event(self, event_result):
        """
        Publish a server-approved platform event after the event
        manager validates and converts it.
        """

        server_event_key = event_result.get(
            "server_event_key"
        )

        server_payload = event_result.get(
            "server_payload",
            {}
        ) or {}

        if not server_event_key:
            self._debug_print(
                "SERVER platform event ignored. Missing server_event_key."
            )
            return

        event_package = {
            "event_type": server_event_key,
            "source": "platform_registry",
            "payload": server_payload
        }

        self.event_bus.publish(
            server_event_key,
            event_package
        )

        self._debug_print(
            f"Published {server_event_key}"
        )
    
    # ========================================================
    # DEBUG
    # ========================================================

    def _debug_print(self, message):
        """
        Print lightweight debug output when enabled.
        """

        if self.debug:
            print(f"[PLATFORM_REGISTRY_EVENT_SERVICES] {message}")