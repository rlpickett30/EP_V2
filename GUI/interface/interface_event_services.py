# ============================================================
# interface_event_services.py
#
# EnviroPulse V2
#
# Subsystem:
#   Interface
#
# Role:
#   Event Services
#
# Purpose:
#   Own Interface event subscriptions and publications.
#
# Does:
#   - Document Interface event communication
#   - Register Interface subscriptions
#   - Publish operator mode-change events
#   - Keep GUI command payloads consistent
#
# Does NOT:
#   - Update GUI widgets
#   - Send UDP packets
#   - Make mode decisions
#   - Store state
#   - Perform Event Bus delivery logic
#
# Owner:
#   interface_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

from datetime import datetime


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class InterfaceEventServices:

    # ========================================================
    # EVENT COMMUNICATION INDEX
    # ========================================================
    #
    # SUBSCRIPTIONS
    #
    # GUI_REGISTER
    #
    # Published By:
    #     GUI registration / repository path
    #
    # Consumed By:
    #     Interface
    #
    # Purpose:
    #     Display GUI registration or repository updates.
    #
    # ========================================================
    #
    # PUBLICATIONS
    #
    # NETWORK MODE CHANGE
    #
    # Published By:
    #     Interface
    #
    # Consumed By:
    #     GUI Communication sender
    #
    # Purpose:
    #     Request a network mode change for a selected node.
    #
    # --------------------------------------------------------
    #
    # DETECTION MODE CHANGE
    #
    # Published By:
    #     Interface
    #
    # Consumed By:
    #     GUI Communication sender
    #
    # Purpose:
    #     Request a detection mode change.
    #
    # --------------------------------------------------------
    #
    # FEATURE MODE CHANGE
    #
    # Published By:
    #     Interface
    #
    # Consumed By:
    #     GUI Communication sender
    #
    # Purpose:
    #     Request a feature mode change.
    #
    # ========================================================

    SUBSCRIPTIONS = [

        "GUI_REGISTER"

    ]

    PUBLICATIONS = [

        "NETWORK_MODE_CHANGE",
        "DETECTION_MODE_CHANGE",
        "FEATURE MODE CHANGE"

    ]

    def __init__(
        self,
        event_bus
    ):

        self.event_bus = event_bus

    # ========================================================
    # REGISTER SUBSCRIPTIONS
    # ========================================================

    def register_subscriptions(
        self,
        dispatcher
    ):

        self.event_bus.subscribe(
            "GUI_REGISTER",
            dispatcher.handle_repository_update
        )

    # ========================================================
    # PUBLISH ENABLE WIFI
    # ========================================================

    def publish_enable_wifi(
        self,
        target_node: str = ""
    ):

        self._publish_mode_change(
            event_type="NETWORK_MODE_CHANGE",
            mode_category="network",
            command="ENABLE_WIFI",
            requested_mode="wifi_enabled",
            target="node",
            target_node=target_node
        )

    # ========================================================
    # PUBLISH ENABLE LORA
    # ========================================================

    def publish_enable_lora(
        self,
        target_node: str = ""
    ):

        self._publish_mode_change(
            event_type="NETWORK_MODE_CHANGE",
            mode_category="network",
            command="ENABLE_LORA",
            requested_mode="lora_enabled",
            target="node",
            target_node=target_node
        )

    # ========================================================
    # PUBLISH ENERGY ONSET
    # ========================================================

    def publish_energy_onset(
        self,
        target_node: str = ""
    ):

        self._publish_mode_change(
            event_type="DETECTION_MODE_CHANGE",
            mode_category="detection",
            command="ENERGY_ONSET",
            requested_mode="energy_onset",
            target="server",
            target_node=target_node
        )

    # ========================================================
    # PUBLISH PATTERN ONSET
    # ========================================================

    def publish_pattern_onset(
        self,
        target_node: str = ""
    ):

        self._publish_mode_change(
            event_type="DETECTION_MODE_CHANGE",
            mode_category="detection",
            command="PATTERN_ONSET",
            requested_mode="pattern_onset",
            target="server",
            target_node=target_node
        )

    # ========================================================
    # PUBLISH AMP FEATURE
    # ========================================================

    def publish_amp_feature(
        self,
        target_node: str = ""
    ):

        self._publish_mode_change(
            event_type="FEATURE_MODE_CHANGE",
            mode_category="feature",
            command="AMP_FEATURE",
            requested_mode="amplitude_feature",
            target="server",
            target_node=target_node
        )

    # ========================================================
    # PUBLISH ONSET FEATURE
    # ========================================================

    def publish_onset_feature(
        self,
        target_node: str = ""
    ):

        self._publish_mode_change(
            event_type="FEATURE_MODE_CHANGE",
            mode_category="feature",
            command="ONSET_FEATURE",
            requested_mode="onset_feature",
            target="server",
            target_node=target_node
        )

    # ========================================================
    # PUBLISH MODE CHANGE
    # ========================================================

    def _publish_mode_change(
        self,
        event_type: str,
        mode_category: str,
        command: str,
        requested_mode: str,
        target: str,
        target_node: str = ""
    ):

        event = {

            "event_type": event_type,
            "source": "gui",
            "timestamp": self._utc_now(),

            "payload": {
                "mode_category": mode_category,
                "command": command,
                "requested_mode": requested_mode,
                "target": target,
                "target_node": target_node
            }
        }

        self.event_bus.publish(
            event_type,
            event
        )

    # ========================================================
    # UTC NOW
    # ========================================================

    def _utc_now(
        self
    ) -> str:

        return datetime.utcnow().isoformat()
