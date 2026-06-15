# ============================================================
# communication_event_services.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Communication
#
# Role:
#   Event Services
#
# Purpose:
#   Connect the Communication subsystem to the GUI event bus.
#   Register Communication subscriptions.
#   Publish Communication, Listener, and Sender events.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["communication"]
#
# Does:
#   - Register Communication subsystem subscriptions
#   - Publish Communication subsystem events
#   - Preserve approved EnviroPulse event names
#   - Forward subscribed events to the Communication dispatcher
#
# Does NOT:
#   - Inspect payload contents
#   - Make routing decisions
#   - Send UDP messages
#   - Receive UDP messages
#   - Maintain subsystem state
#
# Owner:
#   communication_dispatcher.py
#
# ============================================================


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging


# ============================================================
# EVENT NAME DEFINITIONS
# ============================================================

# ----------------------------
# Communication State Events
# ----------------------------

NETWORK_CONNECTED = "NETWORK_CONNECTED"
NETWORK_DISCONNECTED = "NETWORK_DISCONNECTED"

# ----------------------------
# Communication Event Events
# ----------------------------

EVENT_SENT = "EVENT_SENT"

# ----------------------------
# Sender Event Subscriptions
# ----------------------------

GUI_REGISTER = "GUI_REGISTER"

# ----------------------------
# Sender Mode Subscriptions
# ----------------------------

NETWORK_MODE_CHANGE = "NETWORK_MODE_CHANGE"
DETECTION_MODE_CHANGE = "DETECTION_MODE_CHANGE"
FEATURE_MODE_CHANGE = "FEATURE_MODE_CHANGE"

# ----------------------------
# Listener State Publications
# ----------------------------

NODE_STATE_UPDATED = "NODE_STATE_UPDATED"

# ----------------------------
# Listener Event Publications
# ----------------------------

SERVER_NODE_REGISTER = "SERVER_NODE_REGISTER"
SERVER_ENVIRO_EVENT = "SERVER_ENVIRO_EVENT"
SERVER_TDOA_CALC = "SERVER_TDOA_CALC"
SERVER_GPS_COORD = "SERVER_GPS_COORD"
SERVER_AVIS_LITE = "SERVER_AVIS_LITE"


# ============================================================
# EVENT GROUP DEFINITIONS
# ============================================================

COMMUNICATION_SUBSCRIPTIONS = (
    NETWORK_CONNECTED,
    NETWORK_DISCONNECTED,
    GUI_REGISTER,
    NETWORK_MODE_CHANGE,
    DETECTION_MODE_CHANGE,
    FEATURE_MODE_CHANGE,
)

COMMUNICATION_PUBLICATIONS = (
    NETWORK_CONNECTED,
    NETWORK_DISCONNECTED,
    EVENT_SENT,
    NODE_STATE_UPDATED,
    SERVER_NODE_REGISTER,
    SERVER_ENVIRO_EVENT,
    SERVER_TDOA_CALC,
    SERVER_GPS_COORD,
    SERVER_AVIS_LITE,
)


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class CommunicationEventServices:
    """
    Event bus connector for the Communication subsystem.

    This class only registers subscriptions and publishes approved
    Communication events. Workflow decisions belong to the dispatcher.
    """

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
    # SUBSCRIPTION REGISTRATION
    # ========================================================

    def register_subscriptions(self):
        """
        Register all Communication subsystem subscriptions with the GUI event bus.
        """

        for event_name in COMMUNICATION_SUBSCRIPTIONS:
            self._subscribe(
                event_name=event_name,
                callback=self._build_subscription_callback(event_name)
            )

    def _subscribe(
        self,
        event_name,
        callback
    ):
        """
        Subscribe to one event on the GUI event bus.
        """

        self.event_bus.subscribe(
            event_name,
            callback
        )

        if self.debug:
            logging.info(
                "CommunicationEventServices subscribed to %s",
                event_name
            )

    def _build_subscription_callback(
        self,
        event_name
    ):
        """
        Build a simple callback that forwards the event to the dispatcher.
        """

        def callback(payload=None):
            if self.dispatcher is None:
                logging.warning(
                    "CommunicationEventServices received %s but no dispatcher is attached.",
                    event_name
                )
                return

            self.dispatcher.handle_bus_event(
                event_name=event_name,
                payload=payload
            )

        return callback

    # ========================================================
    # GENERIC PUBLICATION
    # ========================================================

    def publish(
        self,
        event_name,
        payload=None
    ):
        """
        Publish an approved Communication event to the GUI event bus.
        """

        if event_name not in COMMUNICATION_PUBLICATIONS:
            raise ValueError(
                f"CommunicationEventServices cannot publish unknown event: {event_name}"
            )

        self.event_bus.publish(
            event_name,
            payload
        )

        if self.debug:
            logging.info(
                "CommunicationEventServices published %s",
                event_name
            )

    # ========================================================
    # STATE PUBLICATIONS
    # ========================================================

    def publish_network_connected(
        self,
        payload=None
    ):
        self.publish(
            event_name=NETWORK_CONNECTED,
            payload=payload
        )

    def publish_network_disconnected(
        self,
        payload=None
    ):
        self.publish(
            event_name=NETWORK_DISCONNECTED,
            payload=payload
        )

    def publish_node_state_updated(
        self,
        payload=None
    ):
        self.publish(
            event_name=NODE_STATE_UPDATED,
            payload=payload
        )

    # ========================================================
    # EVENT PUBLICATIONS
    # ========================================================

    def publish_event_sent(
        self,
        payload=None
    ):
        self.publish(
            event_name=EVENT_SENT,
            payload=payload
        )

    def publish_server_node_register(
        self,
        payload=None
    ):
        self.publish(
            event_name=SERVER_NODE_REGISTER,
            payload=payload
        )

    def publish_server_enviro_event(
        self,
        payload=None
    ):
        self.publish(
            event_name=SERVER_ENVIRO_EVENT,
            payload=payload
        )

    def publish_server_tdoa_calc(
        self,
        payload=None
    ):
        self.publish(
            event_name=SERVER_TDOA_CALC,
            payload=payload
        )

    def publish_server_gps_coord(
        self,
        payload=None
    ):
        self.publish(
            event_name=SERVER_GPS_COORD,
            payload=payload
        )

    def publish_server_avis_lite(
        self,
        payload=None
    ):
        self.publish(
            event_name=SERVER_AVIS_LITE,
            payload=payload
        )

    # ========================================================
    # EVENT INDEX HELPERS
    # ========================================================

    def get_subscriptions(self):
        """
        Return the Communication subsystem subscription list.
        """

        return list(COMMUNICATION_SUBSCRIPTIONS)

    def get_publications(self):
        """
        Return the Communication subsystem publication list.
        """

        return list(COMMUNICATION_PUBLICATIONS)