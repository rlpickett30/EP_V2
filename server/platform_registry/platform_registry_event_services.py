# ============================================================
# platform_registry_event_services.py
#
# EnviroPulse V_2.0
#
# Subsystem:
#   Platform Registry
#
# Role:
#   Event Services
#
# Purpose:
#   Connect the Platform Registry subsystem to the Event Bus.
#   This script owns Registry event subscriptions and Registry
#   event publication helper methods.
#
# Expected config source:
#   platform_registry_config.json
#
# Expected config section:
#   config["platform_registry"]["events"]
#
# Does:
#   - Subscribe Platform Registry to known inbound events
#   - Publish validated server/platform events
#   - Keep event names centralized for the Registry subsystem
#
# Does NOT:
#   - Validate event payloads
#   - Update platform state
#   - Register nodes or interfaces
#   - Decide routing
#   - Send commands directly to field nodes
#
# Owner:
#   platform_registry_dispatcher.py
#
# ============================================================


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging


# ============================================================
# EVENT NAME CONSTANTS
# ============================================================

# ------------------------------------------------------------
# Registry inbound subscriptions
# ------------------------------------------------------------

REGISTRY_SUBSCRIPTIONS = {
    # State events from node/server listener path
    "BMP390_ONLINE": "bmp390_online",
    "BMP390_OFFLINE": "bmp390_offline",
    "SHT45_ONLINE": "sht45_online",
    "SHT45_OFFLINE": "sht45_offline",
    "PPS_LOCK": "pps_lock",
    "PPS_LOST": "pps_lost",
    "GPS_LOCK": "gps_lock",
    "GPS_LOST": "gps_lost",
    "GPS_COORD": "gps_coord",
    "RTK_ONLINE": "rtk_online",

    # Registration / platform events
    "GUI_REGISTER": "gui_register",
    "NODE_REGISTER": "node_register",

    # TDOA capability events
    "NODE_TDOA_CAPABLE": "node_tdoa_capable",
    "NODE_TDOA_CAPABLE_LOST": "node_tdoa_capable_lost",

    # Mode request events
    "ENERGY_ONSET": "energy_onset",
    "ENERGY_OFFSET": "energy_offset",
    "PATTERN_ONSET": "pattern_onset",
    "PATTERN_OFFSET": "pattern_offset",
    "ONSET_FEATURE": "onset_feature",
    "AMP_FEATURE": "amp_feature",
    "ENABLE_WIFI": "enable_wifi",
    "DISABLE_WIFI": "disable_wifi",
    "ENABLE_LORA": "enable_lora",
    "DISABLE_LORA": "disable_lora",
}


# ------------------------------------------------------------
# Registry outbound publications
# ------------------------------------------------------------

REGISTRY_PUBLICATIONS = {
    # Server-approved state publications
    "SERVER_BMP390_ONLINE": "server_bmp390_online",
    "SERVER_BMP390_OFFLINE": "server_bmp390_offline",
    "SERVER_SHT45_ONLINE": "server_sht45_online",
    "SERVER_SHT45_OFFLINE": "server_sht45_offline",
    "SERVER_PPS_LOCK": "server_pps_lock",
    "SERVER_PPS_LOST": "server_pps_lost",
    "SERVER_GPS_LOCK": "server_gps_lock",
    "SERVER_GPS_LOST": "server_gps_lost",
    "SERVER_GPS_COORD": "server_gps_coord",
    "SERVER_RTK_ONLINE": "server_rtk_online",

    # Server-approved registration publications
    "SERVER_GUI_REGISTERED": "server_gui_registered",
    "SERVER_NODE_REGISTERED": "server_node_registered",

    # Server-approved TDOA capability publications
    "SERVER_NODE_TDOA_CAPABLE": "server_node_tdoa_capable",
    "SERVER_NODE_TDOA_CAPABLE_LOST": "server_node_tdoa_capable_lost",

    # Server-approved mode/command publications
    "SERVER_ENERGY_ONSET_COMMAND": "server_energy_onset_command",
    "SERVER_ENERGY_OFFSET_COMMAND": "server_energy_offset_command",
    "SERVER_PATTERN_ONSET_COMMAND": "server_pattern_onset_command",
    "SERVER_PATTERN_OFFSET_COMMAND": "server_pattern_offset_command",
    "SERVER_ONSET_FEATURE_COMMAND": "server_onset_feature_command",
    "SERVER_AMP_FEATURE_COMMAND": "server_amp_feature_command",
    "SERVER_ENABLE_WIFI_COMMAND": "server_enable_wifi_command",
    "SERVER_DISABLE_WIFI_COMMAND": "server_disable_wifi_command",
    "SERVER_ENABLE_LORA_COMMAND": "server_enable_lora_command",
    "SERVER_DISABLE_LORA_COMMAND": "server_disable_lora_command",

    # General Registry publications
    "SERVER_REGISTRY_WARNING": "server_registry_warning",
    "SERVER_REGISTRY_VALIDATION_FAILED": "server_registry_validation_failed",
    "SERVER_PLATFORM_SNAPSHOT": "server_platform_snapshot",
}


# ============================================================
# PLATFORM REGISTRY EVENT SERVICES
# ============================================================

class PlatformRegistryEventServices:
    """
    Event Bus connection layer for Platform Registry.

    The dispatcher passes its handler methods into this class.
    This class subscribes those handlers to event names.

    The dispatcher also uses this class to publish Registry-approved
    server events back onto the Event Bus.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self, event_bus, config=None):
        self.event_bus = event_bus
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)

        self.subscriptions = REGISTRY_SUBSCRIPTIONS
        self.publications = REGISTRY_PUBLICATIONS

    # ========================================================
    # SUBSCRIPTION SETUP
    # ========================================================

    def register_subscriptions(self, dispatcher):
        """
        Register all Platform Registry subscriptions.

        The dispatcher owns the actual handler methods.
        Event Services only connects event names to handlers.
        """

        # State subscriptions
        self._subscribe("BMP390_ONLINE", dispatcher.handle_state_event)
        self._subscribe("BMP390_OFFLINE", dispatcher.handle_state_event)
        self._subscribe("SHT45_ONLINE", dispatcher.handle_state_event)
        self._subscribe("SHT45_OFFLINE", dispatcher.handle_state_event)
        self._subscribe("PPS_LOCK", dispatcher.handle_state_event)
        self._subscribe("PPS_LOST", dispatcher.handle_state_event)
        self._subscribe("GPS_LOCK", dispatcher.handle_state_event)
        self._subscribe("GPS_LOST", dispatcher.handle_state_event)
        self._subscribe("GPS_COORD", dispatcher.handle_state_event)
        self._subscribe("RTK_ONLINE", dispatcher.handle_state_event)

        # Registration subscriptions
        self._subscribe("GUI_REGISTER", dispatcher.handle_registry_event)
        self._subscribe("NODE_REGISTER", dispatcher.handle_registry_event)

        # TDOA capability subscriptions
        self._subscribe("NODE_TDOA_CAPABLE", dispatcher.handle_tdoa_event)
        self._subscribe("NODE_TDOA_CAPABLE_LOST", dispatcher.handle_tdoa_event)

        # Mode request subscriptions
        self._subscribe("ENERGY_ONSET", dispatcher.handle_mode_event)
        self._subscribe("ENERGY_OFFSET", dispatcher.handle_mode_event)
        self._subscribe("PATTERN_ONSET", dispatcher.handle_mode_event)
        self._subscribe("PATTERN_OFFSET", dispatcher.handle_mode_event)
        self._subscribe("ONSET_FEATURE", dispatcher.handle_mode_event)
        self._subscribe("AMP_FEATURE", dispatcher.handle_mode_event)
        self._subscribe("ENABLE_WIFI", dispatcher.handle_mode_event)
        self._subscribe("DISABLE_WIFI", dispatcher.handle_mode_event)
        self._subscribe("ENABLE_LORA", dispatcher.handle_mode_event)
        self._subscribe("DISABLE_LORA", dispatcher.handle_mode_event)

    # ========================================================
    # PUBLICATION METHODS
    # ========================================================

    def publish_state(self, event_key, payload):
        """
        Publish a Registry-approved server state event.
        """

        self._publish(event_key, payload)

    def publish_registry_event(self, event_key, payload):
        """
        Publish a Registry-approved server registry event.
        """

        self._publish(event_key, payload)

    def publish_tdoa_event(self, event_key, payload):
        """
        Publish a Registry-approved server TDOA event.
        """

        self._publish(event_key, payload)

    def publish_mode_command(self, event_key, payload):
        """
        Publish a Registry-approved server command event.
        Sender should subscribe to these events.
        """

        self._publish(event_key, payload)

    def publish_warning(self, message, payload=None):
        """
        Publish a Registry warning without crashing the platform.
        """

        warning_payload = {
            "message": message,
            "payload": payload or {}
        }

        self._publish("SERVER_REGISTRY_WARNING", warning_payload)

    def publish_validation_failed(self, reason, payload=None):
        """
        Publish validation failure details for debug visibility.
        """

        failure_payload = {
            "reason": reason,
            "payload": payload or {}
        }

        self._publish("SERVER_REGISTRY_VALIDATION_FAILED", failure_payload)

    def publish_platform_snapshot(self, snapshot):
        """
        Publish a current platform truth snapshot.
        """

        self._publish("SERVER_PLATFORM_SNAPSHOT", snapshot)

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _subscribe(self, event_key, handler):
        """
        Subscribe a dispatcher handler to an Event Bus event.
        """

        event_name = self.subscriptions.get(event_key)

        if event_name is None:
            self.logger.warning(
                "Subscription key not found: %s",
                event_key
            )
            return

        self.event_bus.subscribe(event_name, handler)

        self.logger.debug(
            "Platform Registry subscribed to event: %s",
            event_name
        )

    def _publish(self, event_key, payload):
        """
        Publish an event using the Registry publication index.
        """

        event_name = self.publications.get(event_key)

        if event_name is None:
            self.logger.warning(
                "Publication key not found: %s",
                event_key
            )
            return False

        self.event_bus.publish(event_name, payload)

        self.logger.debug(
            "Platform Registry published event: %s",
            event_name
        )

        return True