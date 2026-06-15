# ============================================================
# interface_event_services.py
#
# EnviroPulse V2 GUI
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
#   - Register Interface subscriptions
#   - Subscribe Interface to Node Repository publications
#   - Publish operator mode-change events
#   - Preserve existing server-facing command payload shape
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

import logging


# ============================================================
# EVENT NAME DEFINITIONS
# ============================================================

# ----------------------------
# Interface Subscriptions
# ----------------------------

REPOSITORY_STATE_UPDATE = "REPOSITORY_STATE_UPDATE"
REPOSITORY_EVENT_UPDATE = "REPOSITORY_EVENT_UPDATE"
NEW_NODE_REGISTERED = "NEW_NODE_REGISTERED"

# ----------------------------
# Interface Publications
# ----------------------------

NETWORK_MODE_CHANGE = "NETWORK_MODE_CHANGE"
DETECTION_MODE_CHANGE = "DETECTION_MODE_CHANGE"
FEATURE_MODE_CHANGE = "FEATURE_MODE_CHANGE"


# ============================================================
# EVENT GROUP DEFINITIONS
# ============================================================

INTERFACE_SUBSCRIPTIONS = (
    REPOSITORY_STATE_UPDATE,
    REPOSITORY_EVENT_UPDATE,
    NEW_NODE_REGISTERED,
)

INTERFACE_PUBLICATIONS = (
    NETWORK_MODE_CHANGE,
    DETECTION_MODE_CHANGE,
    FEATURE_MODE_CHANGE,
)


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class InterfaceEventServices:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        dispatcher=None,
        debug=False
    ):

        self.event_bus = event_bus
        self.dispatcher = dispatcher
        self.debug = debug

    # ========================================================
    # REGISTER SUBSCRIPTIONS
    # ========================================================

    def register_subscriptions(
        self,
        dispatcher=None
    ):

        if dispatcher is not None:

            self.dispatcher = dispatcher

        for event_name in INTERFACE_SUBSCRIPTIONS:

            self.event_bus.subscribe(
                event_name,
                self._build_subscription_callback(
                    event_name
                )
            )

            if self.debug:

                logging.info(
                    "InterfaceEventServices subscribed to %s",
                    event_name
                )

    def _build_subscription_callback(
        self,
        event_name
    ):

        def callback(
            payload=None
        ):

            if self.dispatcher is None:

                logging.warning(
                    "InterfaceEventServices received %s but no dispatcher is attached.",
                    event_name
                )

                return

            self.dispatcher.handle_bus_event(
                event_name=event_name,
                payload=payload
            )

        return callback

    # ========================================================
    # PUBLISH ENABLE WIFI
    # ========================================================

    def publish_enable_wifi(
        self,
        target_node: str = ""
    ):

        self._publish_mode_change(
            event_type=NETWORK_MODE_CHANGE,
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
            event_type=NETWORK_MODE_CHANGE,
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
            event_type=DETECTION_MODE_CHANGE,
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
            event_type=DETECTION_MODE_CHANGE,
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
            event_type=FEATURE_MODE_CHANGE,
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
            event_type=FEATURE_MODE_CHANGE,
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

        if event_type not in INTERFACE_PUBLICATIONS:

            raise ValueError(
                f"InterfaceEventServices cannot publish unknown event: {event_type}"
            )

        event = {

            "event_type":
                event_type,

            "source":
                "gui",

            "timestamp":
                self._utc_now(),

            "payload": {

                "mode_category":
                    mode_category,

                "command":
                    command,

                "requested_mode":
                    requested_mode,

                "target":
                    target,

                "target_node":
                    target_node
            }
        }

        self.event_bus.publish(
            event_type,
            event
        )

    # ========================================================
    # EVENT INDEX HELPERS
    # ========================================================

    def get_subscriptions(
        self
    ):

        return list(
            INTERFACE_SUBSCRIPTIONS
        )

    def get_publications(
        self
    ):

        return list(
            INTERFACE_PUBLICATIONS
        )

    # ========================================================
    # UTC NOW
    # ========================================================

    def _utc_now(
        self
    ) -> str:

        return datetime.utcnow().isoformat()