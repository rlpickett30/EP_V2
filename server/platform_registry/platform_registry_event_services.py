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
REGISTRY_UPDATED = "REGISTRY_UPDATED"
GUI_FEATURE_MODE_CHANGE = "GUI_FEATURE_MODE_CHANGE"
TDOA_CHANGE_MODE = "TDOA_CHANGE_MODE"
GUI_DETECTION_MODE_CHANGE = "GUI_DETECTION_MODE_CHANGE"
GUI_NETWORK_MODE_CHANGE = "GUI_NETWORK_MODE_CHANGE"
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
            GUI_FEATURE_MODE_CHANGE,
            dispatcher.handle_gui_mode_change
        )
        
        self.event_bus.subscribe(
            GUI_DETECTION_MODE_CHANGE,
            dispatcher.handle_gui_mode_change
        )
        
        self.event_bus.subscribe(
            GUI_NETWORK_MODE_CHANGE,
            dispatcher.handle_gui_mode_change
        )

        self._debug_print(
            "Subscribed to GUI_REGISTER"
        )
        
        self._debug_print(
            "Subscribed to GUI_FEATURE_MODE_CHANGE"
        )
    
        self._debug_print(
            "Subscribed to GUI_DETECTION_MODE_CHANGE"
        )
        
        self._debug_print(
            "Subscribed to GUI_NETWORK_MODE_CHANGE"
        )
        
        
    # ========================================================
    # PUBLICATIONS
    # ========================================================
    
    def publish_registry_updated(self, registry_result):
        """
        Publish REGISTRY_UPDATED after the registry manager accepts
        or updates a GUI registration.
        """

        event_package = {
            "source": "platform_registry",
            "payload": {
                "reason": GUI_REGISTER,
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


    def publish_tdoa_change_mode(self, mode_payload):
        """
        Publish TDOA_CHANGE_MODE after the registry accepts a GUI mode request.
        """

        event_package = {
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
        
    # ========================================================
    # DEBUG
    # ========================================================

    def _debug_print(self, message):
        """
        Print lightweight debug output when enabled.
        """

        if self.debug:
            print(f"[PLATFORM_REGISTRY_EVENT_SERVICES] {message}")